"""Download logic: stream files from the Google Photos CDN.

Each photo is fetched at base_url + "=d" (original full-res).
Each video is fetched at base_url + "=dv" (high-quality transcode).

Deduplication strategy
----------------------
* Files are saved into date subfolders: dest_dir/YYYY/YYYY-MM/filename
* A manifest file (dest_dir/.gphoto_manifest.json) maps media_key → relative
  path.  Skipping is based on media_key, NOT filename, so two different photos
  that happen to share a filename are never conflated.
* On a filename collision within the same date folder (different media_key but
  identical name), a short media_key suffix is appended before the extension:
  IMG_0001_a3f2c1b0.jpg
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Callable

import requests

from client import MediaItem

_CHUNK_SIZE = 256 * 1024  # 256 KB read chunks
_TIMEOUT = 60             # seconds per request
_MANIFEST_NAME = ".gphoto_manifest.json"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _load_manifest(dest_dir: Path) -> dict[str, str]:
    """Load {media_key: relative_path} manifest from dest_dir."""
    path = dest_dir / _MANIFEST_NAME
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_manifest(dest_dir: Path, manifest: dict[str, str]) -> None:
    path = dest_dir / _MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ── Path helpers ──────────────────────────────────────────────────────────────

def _date_subdir(dest_dir: Path, ts: int) -> Path:
    """Return dest_dir/YYYY/YYYY-MM/ for the given epoch-seconds timestamp."""
    if ts:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dest_dir / f"{dt.year:04d}" / f"{dt.year:04d}-{dt.month:02d}"
    return dest_dir / "unknown-date"


def _unique_path(folder: Path, filename: str, media_key: str) -> Path:
    """Return a path that does not collide with existing files."""
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    # Collision: insert short media_key before extension
    stem = Path(filename).stem
    ext = Path(filename).suffix
    return folder / f"{stem}_{media_key[:8]}{ext}"


# ── Session ───────────────────────────────────────────────────────────────────

def _build_session(cookies_path: Path) -> requests.Session:
    """Return a requests.Session loaded with cookies from cookies.txt."""
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    jar = MozillaCookieJar(str(cookies_path))
    jar.load(ignore_discard=True, ignore_expires=True)
    session.cookies.update(jar)
    return session


# ── Core download ─────────────────────────────────────────────────────────────

def download_item(
    session: requests.Session,
    item: MediaItem,
    dest_dir: Path,
    manifest: dict[str, str],
) -> tuple[str, bool, str]:
    """Download one media item.

    Returns:
        (relative_path_str, was_skipped, error_message)
        error_message is empty on success or skip.
    """
    # Check manifest first — skip by media_key, not filename.
    if item.media_key in manifest:
        existing = dest_dir / manifest[item.media_key]
        if existing.exists():
            return manifest[item.media_key], True, ""
        # Manifest entry exists but file was deleted — re-download.

    folder = _date_subdir(dest_dir, item.creation_timestamp)
    folder.mkdir(parents=True, exist_ok=True)
    dest_path = _unique_path(folder, item.filename, item.media_key)
    rel_path = dest_path.relative_to(dest_dir).as_posix()

    suffix = "=dv" if item.is_video else "=d"
    url = item.base_url + suffix

    try:
        resp = session.get(url, stream=True, timeout=_TIMEOUT)
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if chunk:
                    fh.write(chunk)
        manifest[item.media_key] = rel_path
        return rel_path, False, ""
    except Exception as exc:  # noqa: BLE001
        dest_path.unlink(missing_ok=True)
        return item.filename, False, str(exc)


def run_download_job(
    cookies_path: Path,
    items: list[MediaItem],
    dest_dir: Path,
    progress_queue: queue.Queue,
    cancel_event: threading.Event,
    on_enumerate_progress: Callable[[int], None] | None = None,
) -> None:
    """Execute a pipelined download job in the calling (background) thread.

    Items are downloaded as soon as they are yielded by the iterator —
    enumeration and downloading run concurrently (no separate phases).

    Progress queue message shapes:
      {"phase": "dl",   "done": int, "enumerated": int,
       "current": str, "status": str, "skipped": int, "errors": int}
      {"phase": "done", "cancelled": bool,
       "done": int, "skipped": int, "errors": int}
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = _build_session(cookies_path)
    manifest = _load_manifest(dest_dir)

    done = skipped = errors = enumerated = 0
    fatal_error: str | None = None

    try:
        for item in items:
            if cancel_event.is_set():
                break

            enumerated += 1
            rel_path, was_skipped, error = download_item(session, item, dest_dir, manifest)

            if error:
                errors += 1
                status = f"ERROR — {rel_path}: {error}"
            elif was_skipped:
                skipped += 1
                status = f"Skipped (exists): {rel_path}"
            else:
                done += 1
                status = f"Downloaded: {rel_path}"
                _save_manifest(dest_dir, manifest)
            progress_queue.put({
                "phase": "dl",
                "done": done,
                "enumerated": enumerated,
                "current": rel_path,
                "status": status,
                "skipped": skipped,
                "errors": errors,
            })
    except Exception as exc:  # noqa: BLE001
        fatal_error = str(exc)

    _save_manifest(dest_dir, manifest)
    progress_queue.put({
        "phase": "done",
        "cancelled": cancel_event.is_set(),
        "done": done,
        "skipped": skipped,
        "errors": errors,
        "fatal_error": fatal_error,
    })
