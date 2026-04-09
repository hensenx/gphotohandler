"""Google Photos Downloader — Tkinter GUI.

Layout:
  ┌─ Account ────────────────────────────────────────────┐
  │  Status label              [Login / Re-authenticate] │
  ├─ Source ─────────────────────────────────────────────┤
  │  ● All Photos                                        │
  │  ○ Specific Album  [dropdown ▼]  [Refresh Albums]    │
  ├─ Filters ────────────────────────────────────────────┤
  │  Date from  [YYYY-MM-DD]  to  [YYYY-MM-DD]           │
  │  Media type  [All ▼]                                 │
  ├─ Destination ────────────────────────────────────────┤
  │  [path entry                              ] [Browse] │
  ├─ Controls ───────────────────────────────────────────┤
  │  [  Start Download  ]          [  Cancel  ]          │
  ├─ Progress ───────────────────────────────────────────┤
  │  ████████░░░░░░░  42 / 150                           │
  │  Current: IMG_20230812.jpg                           │
  │  ┌─ Log ─────────────────────────────────────────┐   │
  │  │ 17:23:01  Downloaded: IMG_20230812.jpg         │   │
  │  └───────────────────────────────────────────────┘   │
  └──────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from datetime import datetime, date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import auth
import client as gphotos_client
import downloader


# ── Constants ─────────────────────────────────────────────────────────────────

APP_TITLE = "Google Photos Downloader"
WIN_WIDTH = 620
WIN_HEIGHT = 640

_ALBUM_PLACEHOLDER = "— select an album —"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts_from_date_str(s: str, end_of_day: bool = False) -> int | None:
    """Parse 'YYYY-MM-DD' → epoch seconds, or None if blank/invalid."""
    s = s.strip()
    if not s:
        return None
    try:
        d = date.fromisoformat(s)
        if end_of_day:
            return int(datetime(d.year, d.month, d.day, 23, 59, 59).timestamp())
        return int(datetime(d.year, d.month, d.day, 0, 0, 0).timestamp())
    except ValueError:
        return None


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── Main application ──────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(True, True)
        self.minsize(WIN_WIDTH, WIN_HEIGHT)

        # State
        self._albums: list[gphotos_client.Album] = []
        self._progress_queue: queue.Queue = queue.Queue()
        self._cancel_event: threading.Event = threading.Event()
        self._job_thread: threading.Thread | None = None
        self._inhibit_proc: subprocess.Popen | None = None

        self._build_ui()
        self._refresh_auth_status()
        self.after(200, self._poll_progress)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        """Clean up inhibitor and exit when the window is closed."""
        self._cancel_event.set()
        self._stop_inhibit()
        self.destroy()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}

        # ── Account ──────────────────────────────────────────────────────────
        account_frame = ttk.LabelFrame(self, text="Account")
        account_frame.pack(fill="x", **pad)

        self._auth_status_var = tk.StringVar(value="Checking…")
        ttk.Label(account_frame, textvariable=self._auth_status_var).pack(
            side="left", padx=8, pady=6
        )
        self._login_btn = ttk.Button(
            account_frame, text="Login / Re-authenticate", command=self._on_login
        )
        self._login_btn.pack(side="right", padx=8, pady=6)

        # ── Source ────────────────────────────────────────────────────────────
        source_frame = ttk.LabelFrame(self, text="Source")
        source_frame.pack(fill="x", **pad)

        self._source_var = tk.StringVar(value="all")
        ttk.Radiobutton(
            source_frame,
            text="All Photos",
            variable=self._source_var,
            value="all",
            command=self._on_source_change,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=4)

        ttk.Radiobutton(
            source_frame,
            text="Specific Album",
            variable=self._source_var,
            value="album",
            command=self._on_source_change,
        ).grid(row=1, column=0, sticky="w", padx=8, pady=4)

        self._album_var = tk.StringVar(value=_ALBUM_PLACEHOLDER)
        self._album_combo = ttk.Combobox(
            source_frame,
            textvariable=self._album_var,
            state="disabled",
            width=34,
        )
        self._album_combo.grid(row=1, column=1, padx=4, pady=4, sticky="w")

        self._refresh_albums_btn = ttk.Button(
            source_frame,
            text="Refresh Albums",
            command=self._on_refresh_albums,
            state="disabled",
        )
        self._refresh_albums_btn.grid(row=1, column=2, padx=4, pady=4)

        source_frame.columnconfigure(1, weight=1)

        # ── Filters ───────────────────────────────────────────────────────────
        filter_frame = ttk.LabelFrame(self, text="Filters")
        filter_frame.pack(fill="x", **pad)

        ttk.Label(filter_frame, text="Date from").grid(
            row=0, column=0, padx=8, pady=4, sticky="w"
        )
        self._date_from_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._date_from_var, width=14).grid(
            row=0, column=1, padx=4, pady=4, sticky="w"
        )
        ttk.Label(filter_frame, text="to").grid(row=0, column=2, padx=4)
        self._date_to_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._date_to_var, width=14).grid(
            row=0, column=3, padx=4, pady=4, sticky="w"
        )
        ttk.Label(filter_frame, text="(YYYY-MM-DD, leave blank for no limit)").grid(
            row=0, column=4, padx=8, pady=4, sticky="w"
        )

        ttk.Label(filter_frame, text="Media type").grid(
            row=1, column=0, padx=8, pady=4, sticky="w"
        )
        self._media_type_var = tk.StringVar(value="All")
        ttk.Combobox(
            filter_frame,
            textvariable=self._media_type_var,
            values=["All", "Photos only", "Videos only"],
            state="readonly",
            width=14,
        ).grid(row=1, column=1, padx=4, pady=4, sticky="w")

        # ── Destination ───────────────────────────────────────────────────────
        dest_frame = ttk.LabelFrame(self, text="Destination Folder")
        dest_frame.pack(fill="x", **pad)

        self._dest_var = tk.StringVar()
        ttk.Entry(dest_frame, textvariable=self._dest_var).pack(
            side="left", fill="x", expand=True, padx=8, pady=6
        )
        ttk.Button(dest_frame, text="Browse…", command=self._on_browse).pack(
            side="right", padx=8, pady=6
        )

        # ── Controls ──────────────────────────────────────────────────────────
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", padx=10, pady=6)

        self._start_btn = ttk.Button(
            ctrl_frame, text="Start Download", command=self._on_start
        )
        self._start_btn.pack(side="left", padx=4)

        self._cancel_btn = ttk.Button(
            ctrl_frame, text="Cancel", command=self._on_cancel, state="disabled"
        )
        self._cancel_btn.pack(side="left", padx=4)

        # ── Progress ──────────────────────────────────────────────────────────
        prog_frame = ttk.LabelFrame(self, text="Progress")
        prog_frame.pack(fill="both", expand=True, **pad)

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            prog_frame,
            variable=self._progress_var,
            maximum=100.0,
            mode="determinate",
        )
        self._progress_bar.pack(fill="x", padx=8, pady=(8, 2))

        self._progress_label_var = tk.StringVar(value="")
        ttk.Label(prog_frame, textvariable=self._progress_label_var).pack(
            anchor="w", padx=8, pady=2
        )

        self._current_file_var = tk.StringVar(value="")
        ttk.Label(
            prog_frame,
            textvariable=self._current_file_var,
            foreground="gray",
        ).pack(anchor="w", padx=8, pady=2)

        log_frame = ttk.Frame(prog_frame)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self._log = tk.Text(
            log_frame, height=10, state="disabled", wrap="word", relief="sunken",
            background="#1e1e1e", foreground="#d4d4d4", font=("Courier", 9),
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _refresh_auth_status(self) -> None:
        if auth.is_authenticated():
            self._auth_status_var.set("● Logged in")
        else:
            self._auth_status_var.set("○ Not logged in")

    def _on_login(self) -> None:
        self._auth_status_var.set("Opening browser…")
        self._login_btn.config(state="disabled")
        auth.do_login(
            on_complete=lambda: self.after(0, self._on_login_complete),
            on_error=lambda msg: self.after(0, lambda: self._on_login_error(msg)),
        )

    def _on_login_complete(self) -> None:
        self._auth_status_var.set("● Logged in")
        self._login_btn.config(state="normal")
        self._log_line("Authenticated successfully.")

    def _on_login_error(self, msg: str) -> None:
        self._auth_status_var.set("○ Login failed")
        self._login_btn.config(state="normal")
        self._log_line(f"Login error: {msg}")
        messagebox.showerror("Login failed", msg)

    # ── Source ────────────────────────────────────────────────────────────────

    def _on_source_change(self) -> None:
        if self._source_var.get() == "album":
            self._album_combo.config(state="readonly")
            self._refresh_albums_btn.config(state="normal")
        else:
            self._album_combo.config(state="disabled")
            self._refresh_albums_btn.config(state="disabled")

    def _on_refresh_albums(self) -> None:
        if not auth.is_authenticated():
            messagebox.showwarning("Not logged in", "Please log in first.")
            return
        self._refresh_albums_btn.config(state="disabled", text="Loading…")
        self._log_line("Fetching albums…")
        threading.Thread(target=self._fetch_albums_thread, daemon=True).start()

    def _fetch_albums_thread(self) -> None:
        try:
            albums = gphotos_client.list_albums(auth.COOKIES_PATH)
            self.after(0, lambda: self._on_albums_loaded(albums))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._on_albums_error(str(exc)))

    def _on_albums_loaded(self, albums: list[gphotos_client.Album]) -> None:
        self._albums = albums
        names = [f"{a.title} ({a.item_count})" for a in albums]
        self._album_combo["values"] = names
        if names:
            self._album_var.set(names[0])
        self._refresh_albums_btn.config(state="normal", text="Refresh Albums")
        self._log_line(f"Found {len(albums)} album(s).")

    def _on_albums_error(self, msg: str) -> None:
        self._refresh_albums_btn.config(state="normal", text="Refresh Albums")
        self._log_line(f"Error loading albums: {msg}")
        messagebox.showerror("Album error", msg)

    # ── Destination ───────────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        path = filedialog.askdirectory(title="Select destination folder")
        if path:
            self._dest_var.set(path)

    # ── Download ──────────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if not auth.is_authenticated():
            messagebox.showwarning("Not logged in", "Please log in before downloading.")
            return

        dest_str = self._dest_var.get().strip()
        if not dest_str:
            messagebox.showwarning("No destination", "Please choose a destination folder.")
            return
        dest_dir = Path(dest_str)

        # Validate date entries (if filled in).
        from_str = self._date_from_var.get().strip()
        to_str = self._date_to_var.get().strip()
        if from_str and _ts_from_date_str(from_str) is None:
            messagebox.showerror("Invalid date", f"Date from '{from_str}' is not YYYY-MM-DD.")
            return
        if to_str and _ts_from_date_str(to_str) is None:
            messagebox.showerror("Invalid date", f"Date to '{to_str}' is not YYYY-MM-DD.")
            return

        start_ts = _ts_from_date_str(from_str) if from_str else None
        end_ts = _ts_from_date_str(to_str, end_of_day=True) if to_str else None

        mt_label = self._media_type_var.get()
        media_type_map = {"All": "ALL", "Photos only": "PHOTO", "Videos only": "VIDEO"}
        media_type = media_type_map.get(mt_label, "ALL")

        # Determine source iterator.
        if self._source_var.get() == "album":
            album_label = self._album_var.get()
            if album_label == _ALBUM_PLACEHOLDER:
                messagebox.showwarning("No album selected", "Please select an album.")
                return
            # Find album_media_key by matching the displayed label.
            try:
                idx = list(self._album_combo["values"]).index(album_label)
                album_key = self._albums[idx].media_key
            except (ValueError, IndexError):
                messagebox.showerror("Album error", "Could not find the selected album.")
                return
            items_iter = gphotos_client.list_album_media(
                auth.COOKIES_PATH,
                album_media_key=album_key,
                media_type=media_type,
                cancel_event=self._cancel_event,
            )
        else:
            items_iter = gphotos_client.list_all_media(
                auth.COOKIES_PATH,
                start_ts=start_ts,
                end_ts=end_ts,
                media_type=media_type,
                cancel_event=self._cancel_event,
            )

        # Clear progress UI and start.
        self._cancel_event.clear()
        self._progress_var.set(0.0)
        self._progress_label_var.set("Starting…")
        self._current_file_var.set("")
        self._start_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._log_line("─" * 50)
        self._log_line(f"Starting download → {dest_dir}")

        self._start_inhibit()
        self._job_thread = threading.Thread(
            target=downloader.run_download_job,
            kwargs={
                "cookies_path": auth.COOKIES_PATH,
                "items": items_iter,
                "dest_dir": dest_dir,
                "progress_queue": self._progress_queue,
                "cancel_event": self._cancel_event,
            },
            daemon=True,
        )
        self._job_thread.start()

    def _start_inhibit(self) -> None:
        """Ask systemd to block sleep/idle for the duration of the download."""
        try:
            self._inhibit_proc = subprocess.Popen(
                [
                    "systemd-inhibit",
                    "--what=sleep:idle",
                    "--who=Google Photos Downloader",
                    "--why=Download in progress",
                    "--mode=block",
                    "sleep", "infinity",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._inhibit_proc = None  # systemd-inhibit not available

    def _stop_inhibit(self) -> None:
        """Release the sleep inhibitor lock."""
        if self._inhibit_proc is not None:
            self._inhibit_proc.terminate()
            self._inhibit_proc = None

    def _on_cancel(self) -> None:
        self._cancel_event.set()
        self._cancel_btn.config(state="disabled")
        self._log_line("Cancelling…")

    # ── Progress polling ──────────────────────────────────────────────────────

    def _poll_progress(self) -> None:
        try:
            while True:
                msg = self._progress_queue.get_nowait()
                self._handle_progress(msg)
        except queue.Empty:
            pass
        self.after(200, self._poll_progress)

    def _handle_progress(self, msg: dict) -> None:
        phase = msg.get("phase")

        if phase == "dl":
            done = msg["done"]
            enumerated = msg["enumerated"]
            skipped = msg["skipped"]
            errors = msg["errors"]
            status = msg["status"]
            current = msg["current"]

            # Progress bar is indeterminate until enumeration catches up;
            # once we know we've seen every item we switch to determinate
            # — but since enumeration and downloading run together we just
            # show a pulse bar with a text counter throughout.
            self._progress_bar.config(mode="indeterminate")
            self._progress_bar.start(10)
            self._progress_label_var.set(
                f"Downloaded {done} / {enumerated} seen  —  "
                f"skipped: {skipped}  errors: {errors}"
            )
            self._current_file_var.set(f"↳ {current}")
            self._log_line(status)

        elif phase == "enum_done":
            n = msg["enumerated"]
            self._log_line(f"Enumeration complete — {n} items found. Downloading remaining…")

        elif phase == "enum_error":
            n = msg["enumerated"]
            err = msg["error"]
            self._log_line(f"Enumeration stopped after {n} items: {err}")
            self._progress_label_var.set(f"Enumeration error after {n} items — see log")

        elif phase == "done":
            self._stop_inhibit()
            self._progress_bar.stop()
            self._progress_bar.config(mode="determinate")
            cancelled = msg.get("cancelled", False)
            done = msg.get("done", 0)
            skipped = msg.get("skipped", 0)
            errors = msg.get("errors", 0)
            fatal = msg.get("fatal_error")
            if fatal:
                self._progress_label_var.set(f"Failed: {fatal}")
                self._log_line(f"FATAL ERROR: {fatal}")
                messagebox.showerror("Download failed", fatal)
            elif cancelled:
                self._progress_label_var.set(
                    f"Cancelled — downloaded {done}, skipped {skipped}, errors {errors}."
                )
                self._log_line("Download cancelled.")
            else:
                self._progress_var.set(100.0)
                self._progress_label_var.set(
                    f"Done — downloaded {done}, skipped {skipped}, errors {errors}."
                )
                self._log_line("Download complete.")
            self._current_file_var.set("")
            self._start_btn.config(state="normal")
            self._cancel_btn.config(state="disabled")

    # ── Log ───────────────────────────────────────────────────────────────────

    def _log_line(self, text: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", f"[{_now_str()}] {text}\n")
        self._log.see("end")
        self._log.config(state="disabled")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
