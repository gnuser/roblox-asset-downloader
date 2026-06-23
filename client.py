import asyncio
import logging
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import END, Text
from tkinter import IntVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

from module.roblox import AsyncRobloxDownloader


APP_NAME = "Roblox Asset Downloader"


class QueueLogHandler(logging.Handler):
    def __init__(self, event_queue):
        super().__init__()
        self.event_queue = event_queue

    def emit(self, record):
        self.event_queue.put(("log", self.format(record)))


class DownloaderClient:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("860x620")
        self.root.minsize(760, 540)

        self.event_queue = queue.Queue()
        self.worker = None

        self.runtime_dir = StringVar(value=str(Path.home() / "RobloxAssetDownloader"))
        self.cookie = StringVar(value="")
        self.group_id = StringVar(value="")
        self.group_limit = IntVar(value=20)
        self.status = StringVar(value="Ready")

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        self.source_tabs = ttk.Notebook(main)
        self.source_tabs.grid(row=0, column=0, sticky="nsew")

        self.asset_tab = ttk.Frame(self.source_tabs, padding=12)
        self.asset_tab.columnconfigure(0, weight=1)
        self.asset_tab.rowconfigure(1, weight=1)
        self.source_tabs.add(self.asset_tab, text="Asset IDs")

        ttk.Label(self.asset_tab, text="Asset IDs").grid(row=0, column=0, sticky="w")
        self.asset_ids = Text(self.asset_tab, height=8, wrap="word", undo=True)
        self.asset_ids.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.asset_ids.insert("1.0", "rbxassetid://5603258258\n9924398681\n")

        self.group_tab = ttk.Frame(self.source_tabs, padding=12)
        self.group_tab.columnconfigure(1, weight=1)
        self.source_tabs.add(self.group_tab, text="Group")

        ttk.Label(self.group_tab, text="Group ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.group_tab, textvariable=self.group_id).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(10, 0),
        )
        ttk.Label(self.group_tab, text="Limit").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(10, 0),
        )
        ttk.Spinbox(
            self.group_tab,
            from_=1,
            to=500,
            textvariable=self.group_limit,
            width=10,
        ).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        settings = ttk.LabelFrame(main, text="Settings", padding=12)
        settings.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Output folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.runtime_dir).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(10, 8),
        )
        ttk.Button(settings, text="Browse", command=self._choose_output_dir).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        ttk.Label(settings, text="Cookie").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(10, 0),
        )
        ttk.Entry(settings, textvariable=self.cookie, show="*").grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(10, 0),
            pady=(10, 0),
        )

        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)

        ttk.Label(actions, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Open Folder", command=self._open_output_dir).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )
        self.start_button = ttk.Button(
            actions,
            text="Download",
            command=self._start_download,
        )
        self.start_button.grid(row=0, column=2, padx=(8, 0))

        log_frame = ttk.LabelFrame(main, text="Log", padding=12)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _choose_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.runtime_dir.get() or str(Path.home()))
        if selected:
            self.runtime_dir.set(selected)

    def _open_output_dir(self):
        folder = Path(self.runtime_dir.get().strip() or Path.home())
        folder.mkdir(parents=True, exist_ok=True)

        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _start_download(self):
        if self.worker and self.worker.is_alive():
            return

        try:
            config = self._collect_config()
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return

        self._clear_log()
        self.status.set("Downloading...")
        self.start_button.configure(state="disabled")
        self._append_log("Starting download...")

        self.worker = threading.Thread(
            target=self._worker_main,
            args=(config,),
            daemon=True,
        )
        self.worker.start()

    def _collect_config(self):
        runtime_dir = self.runtime_dir.get().strip()
        if not runtime_dir:
            raise ValueError("Choose an output folder.")

        config = {
            "runtime_dir": runtime_dir,
            "cookie": self.cookie.get().strip() or None,
            "mode": self._current_mode(),
        }

        if config["mode"] == "assets":
            text = self.asset_ids.get("1.0", END)
            asset_ids = [part for part in re.split(r"[\s,;]+", text.strip()) if part]
            if not asset_ids:
                raise ValueError("Enter at least one asset ID.")
            config["asset_ids"] = asset_ids
            return config

        group_id = self.group_id.get().strip()
        if not group_id:
            raise ValueError("Enter a group ID.")

        limit = int(self.group_limit.get())
        if limit < 1:
            raise ValueError("Limit must be at least 1.")

        config.update({"group_id": group_id, "group_limit": limit})
        return config

    def _current_mode(self):
        selected = self.source_tabs.select()
        return "assets" if selected == str(self.asset_tab) else "group"

    def _worker_main(self, config):
        handler = QueueLogHandler(self.event_queue)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        root_logger = logging.getLogger()
        old_level = root_logger.level
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

        try:
            paths = asyncio.run(self._run_download(config))
            self.event_queue.put(("done", paths))
        except Exception as e:
            self.event_queue.put(("error", str(e)))
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(old_level)

    async def _run_download(self, config):
        downloader = AsyncRobloxDownloader(
            runtime_dir=config["runtime_dir"],
            max_concurrent=8,
            apply_template_to_images=False,
            cookie=config["cookie"],
        )

        if config["mode"] == "assets":
            return await downloader.download_assets(config["asset_ids"])

        return await downloader.download_group_items(
            config["group_id"],
            limit=config["group_limit"],
            category="All",
        )

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self.start_button.configure(state="normal")
                    self.status.set(f"Saved {len(payload)} file(s)")
                    self._append_log("")
                    self._append_log(f"Done. Saved {len(payload)} file(s).")
                    for path in payload:
                        self._append_log(path)
                    messagebox.showinfo(APP_NAME, f"Saved {len(payload)} file(s).")
                elif kind == "error":
                    self.start_button.configure(state="normal")
                    self.status.set("Failed")
                    self._append_log(f"ERROR: {payload}")
                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_events)

    def _append_log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"{message}\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")


def main():
    root = Tk()
    DownloaderClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()
