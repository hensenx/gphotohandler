# gphotohandler — Project Guidelines

A Python 3.10+ Tkinter GUI app that downloads a Google Photos library using a reverse-engineered batchexecute API (`gpwc`). No official Google API — all auth is cookie-based from a real browser session.

## Architecture

| File | Role |
|------|------|
| `auth.py` | Playwright browser login → `~/.gphotohandler/cookies.txt` (Netscape format) |
| `client.py` | Enumerate library/albums via `gpwc.Client`; yields `MediaItem` / `Album` dataclasses |
| `downloader.py` | Producer-consumer download pipeline; dedup via `.gphoto_manifest.json` |
| `main.py` | Tkinter `App(tk.Tk)` — all UI; polls `progress_queue` every 200 ms |

Config and cookies are stored under `~/.gphotohandler/`. No environment variables.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Threading Model

- **Main thread**: Tkinter event loop only — never block it.
- **Auth / album fetch / download job**: Daemon threads; results surfaced via callbacks or `progress_queue`.
- **Inside `run_download_job`**: producer thread (enumeration) + consumer thread (downloads) share an `item_queue`; use the `_SENTINEL` object to signal end of enumeration.
- **Cancellation**: check `cancel_event.is_set()` in all loops; never use `thread.kill()`.
- **UI updates from threads**: always use `self.after(0, callback)`, never direct widget writes.

## Key Conventions

- **Progress messages** are dicts on `progress_queue`: `"dl"`, `"enum_done"`, `"enum_error"`, `"done"`.
- **Deduplication** tracks `media_key` (not filename) in `.gphoto_manifest.json`; use `_unique_path()` to resolve collisions.
- **Download URLs**: photos → `base_url + "=d"`, videos → `base_url + "=dv"`.
- **Date sub-directory**: `YYYY/YYYY-MM/` computed by `_date_subdir()` from epoch seconds.
- **Timestamp normalization**: call `_to_seconds()` before any epoch math — the API returns milliseconds when value > 10¹².
- **Batch filename resolution**: `_fetch_filenames()` sends 50 keys per call; fall back to `media_key + extension` on failure.
- **Private helpers**: prefix with `_`; constants in `UPPER_CASE` at module top.
- **Exception handling**: bare `except Exception` in thread bodies is intentional (marked `# noqa: BLE001`); surface to caller via callback or queue message.

## Common Pitfalls

- **Re-login**: cookies expire in ~3–6 months; `RuntimeError` from `_make_client()` usually means expired cookies, not a code bug.
- **Playwright headless**: `headless=False` is required — Google blocks headless Chrome for auth.
- **`systemd-inhibit` availability**: `_start_inhibit()` in `main.py` is non-critical; skip gracefully on non-Linux systems.
- **No test suite**: verify changes manually by running the app; focus on thread safety and queue message contracts.
