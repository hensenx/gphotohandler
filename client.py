"""Google Photos library/album enumeration via the gpwc batchexecute client.

LibraryItem and AlbumItem from gpwc do not include filenames, so we batch-fetch
them via GetBatchMediaInfo before yielding each MediaItem.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

# ── Helpers ──────────────────────────────────────────────────────────────────

# Timestamps from the Google Photos batchexecute API are in milliseconds.
# _to_seconds() converts them to epoch seconds for use with datetime / filters.
_MS_THRESHOLD = 1_000_000_000_000  # anything > 10^12 is almost certainly ms

def _to_seconds(ts: int | None) -> int:
    if not ts:
        return 0
    return ts // 1000 if ts > _MS_THRESHOLD else ts


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class MediaItem:
    media_key: str
    filename: str
    base_url: str           # lh3.googleusercontent.com/… — append =d or =dv
    creation_timestamp: int  # Unix epoch seconds
    is_video: bool


@dataclass
class Album:
    media_key: str
    title: str
    item_count: int


# ── Internal helpers ──────────────────────────────────────────────────────────

_BATCH_SIZE = 50  # items per GetBatchMediaInfo call


def _make_client(cookies_path: Path):
    """Instantiate gpwc.Client; raises RuntimeError if authentication fails."""
    try:
        from gpwc import Client  # type: ignore
        return Client(str(cookies_path))
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Google Photos — "
            f"try re-authenticating. ({exc})"
        ) from exc


def _fetch_filenames(gpwc_client, media_keys: list[str]) -> dict[str, str]:
    """Return {media_key: filename} for a list of media keys."""
    from gpwc import payloads  # type: ignore

    result: dict[str, str] = {}
    for i in range(0, len(media_keys), _BATCH_SIZE):
        chunk = media_keys[i : i + _BATCH_SIZE]
        resp = payloads.GetBatchMediaInfo(chunk).execute(gpwc_client)
        if resp.success and resp.data:
            for info in resp.data:
                if info.file_name:
                    result[info.media_key] = info.file_name
    return result


def _fallback_filename(media_key: str, is_video: bool) -> str:
    ext = ".mp4" if is_video else ".jpg"
    return f"{media_key}{ext}"


# ── Public API ────────────────────────────────────────────────────────────────

def list_albums(
    cookies_path: Path,
    cancel_event: threading.Event | None = None,
) -> list[Album]:
    """Return all albums in the user's Google Photos library."""
    from gpwc import payloads  # type: ignore

    client = _make_client(cookies_path)
    albums: list[Album] = []
    page_id = None

    while True:
        if cancel_event and cancel_event.is_set():
            break
        resp = payloads.GetAlbumsPage(page_id=page_id).execute(client)
        if not resp.success or not resp.data or not resp.data.items:
            break
        for album in resp.data.items:
            albums.append(Album(
                media_key=album.media_key,
                title=album.title or "(untitled)",
                item_count=album.item_count or 0,
            ))
        page_id = resp.data.next_page_id
        if not page_id:
            break

    return albums


def list_all_media(
    cookies_path: Path,
    start_ts: int | None = None,
    end_ts: int | None = None,
    media_type: str = "ALL",
    progress_cb: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Iterator[MediaItem]:
    """Yield every MediaItem in the library, applying optional filters.

    Args:
        start_ts: Earliest creation timestamp to include (epoch seconds, inclusive).
        end_ts:   Latest creation timestamp to include (epoch seconds, inclusive).
        media_type: One of "ALL", "PHOTO", "VIDEO".
        progress_cb: Called with a running count of items yielded so far.
        cancel_event: Set this to abort the iteration early.
    """
    from gpwc import payloads  # type: ignore

    client = _make_client(cookies_path)
    page_id = None
    count = 0

    while True:
        if cancel_event and cancel_event.is_set():
            return

        resp = payloads.GetLibraryPageByTakenDate(page_id=page_id).execute(client)
        if not resp.success or not resp.data or not resp.data.items:
            return

        page_items = resp.data.items
        media_keys = [item.media_key for item in page_items]
        filenames = _fetch_filenames(client, media_keys)

        for item in page_items:
            if cancel_event and cancel_event.is_set():
                return

            ts = _to_seconds(item.creation_timestamp or item.timestamp or 0)
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue

            is_video = item.video_duration is not None
            if media_type == "PHOTO" and is_video:
                continue
            if media_type == "VIDEO" and not is_video:
                continue

            filename = filenames.get(
                item.media_key,
                _fallback_filename(item.media_key, is_video),
            )
            yield MediaItem(
                media_key=item.media_key,
                filename=filename,
                base_url=item.thumbnail_url,
                creation_timestamp=ts,
                is_video=is_video,
            )
            count += 1
            if progress_cb:
                progress_cb(count)

        page_id = resp.data.next_page_id
        if not page_id:
            return


def list_album_media(
    cookies_path: Path,
    album_media_key: str,
    media_type: str = "ALL",
    progress_cb: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Iterator[MediaItem]:
    """Yield every MediaItem in a specific album."""
    from gpwc import payloads  # type: ignore

    client = _make_client(cookies_path)
    page_id = None
    count = 0

    while True:
        if cancel_event and cancel_event.is_set():
            return

        resp = payloads.GetAlbumPage(
            media_key=album_media_key,
            page_id=page_id,
        ).execute(client)
        if not resp.success or not resp.data or not resp.data.items:
            return

        page_items = resp.data.items
        media_keys = [item.media_key for item in page_items]
        filenames = _fetch_filenames(client, media_keys)

        for item in page_items:
            if cancel_event and cancel_event.is_set():
                return

            is_video = item.video_duration is not None
            if media_type == "PHOTO" and is_video:
                continue
            if media_type == "VIDEO" and not is_video:
                continue

            ts = _to_seconds(item.creation_timestamp or item.timestamp or 0)
            filename = filenames.get(
                item.media_key,
                _fallback_filename(item.media_key, is_video),
            )
            yield MediaItem(
                media_key=item.media_key,
                filename=filename,
                base_url=item.thumbnail_url,
                creation_timestamp=ts,
                is_video=is_video,
            )
            count += 1
            if progress_cb:
                progress_cb(count)

        page_id = resp.data.next_page_id
        if not page_id:
            return
