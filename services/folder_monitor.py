"""
Мониторинг папки заказа (P:\XXXX\in).
Использует watchdog. При появлении PDF запускает callback.
"""
import os
import threading
from typing import Callable


class FolderMonitor:
    def __init__(self, path: str, callback: Callable[[str], None]):
        self.path = path
        self.callback = callback
        self._observer = None

    def start(self):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            monitor = self

            class Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory:
                        ext = os.path.splitext(event.src_path)[1].lower()
                        if ext in (".pdf", ".PDF"):
                            monitor.callback(event.src_path)

            self._observer = Observer()
            self._observer.schedule(Handler(), self.path, recursive=False)
            self._observer.start()
        except ImportError:
            raise RuntimeError("pip install watchdog")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
