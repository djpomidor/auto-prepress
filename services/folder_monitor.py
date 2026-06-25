"""
Мониторинг папки P:\<order>\in
При появлении PDF копирует в D:\Pitstop_\out\<order_folder>
Затем ждёт XML лог от PitStop и вызывает callback.
"""
import os
import shutil
import threading
import time
from typing import Callable


class FolderMonitor:
    def __init__(self, in_path: str, order_folder_name: str,
                 callback: Callable = None):
        self.in_path           = in_path
        self.order_folder_name = order_folder_name
        self.callback          = callback
        self._observer         = None
        self._known_files      = set()

        # Запоминаем файлы которые уже были до старта мониторинга
        if os.path.isdir(in_path):
            self._known_files = set(os.listdir(in_path))

    def start(self):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise RuntimeError("pip install watchdog")

        monitor = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                fname = os.path.basename(event.src_path)
                ext   = os.path.splitext(fname)[1].lower()
                if ext == ".pdf" and fname not in monitor._known_files:
                    monitor._known_files.add(fname)
                    threading.Thread(
                        target=monitor._handle_new_pdf,
                        args=(event.src_path,),
                        daemon=True
                    ).start()

            # on_modified тоже ловим — некоторые программы сначала создают
            # пустой файл, потом дописывают
            def on_modified(self, event):
                self.on_created(event)

        self._observer = Observer()
        self._observer.schedule(Handler(), self.in_path, recursive=False)
        self._observer.start()
        print(f"[Monitor] Слежу за: {self.in_path}")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            print(f"[Monitor] Остановлен: {self.in_path}")

    def _handle_new_pdf(self, pdf_path: str):
        import config

        # Ждём пока файл полностью скопируется (размер не меняется 2 сек)
        self._wait_file_stable(pdf_path)

        # 1. Копируем в D:\Pitstop_\out\<order_folder>\
        pitstop_out = os.path.join(
            config.CFG["pitstop_in"],
            self.order_folder_name
        )
        try:
            os.makedirs(pitstop_out, exist_ok=True)
            dst = os.path.join(pitstop_out, os.path.basename(pdf_path))
            shutil.copy2(pdf_path, dst)
            print(f"[Monitor] ✓ Скопировано в PitStop Out: {dst}")
        except Exception as e:
            print(f"[Monitor] ✗ Ошибка копирования: {e}")
            return

        # 2. Ждём XML лог от PitStop (до 10 минут)
        if self.callback:
            log_dir = os.path.join(
                config.CFG["pitstop_log"],
                self.order_folder_name
            )
            self._wait_for_log(log_dir, timeout=600)

    def _wait_file_stable(self, path: str, stable_secs: int = 2):
        """Ждём пока размер файла не перестанет меняться."""
        prev_size = -1
        for _ in range(30):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size == prev_size and size > 0:
                return
            prev_size = size
            time.sleep(stable_secs)

    def _wait_for_log(self, log_dir: str, timeout: int = 600):
        """Ждём появления XML файла в папке лога PitStop."""
        deadline = time.time() + timeout
        seen_xml = set()
        while time.time() < deadline:
            if os.path.isdir(log_dir):
                xmls = {f for f in os.listdir(log_dir)
                        if f.lower().endswith(".xml")}
                new = xmls - seen_xml
                if new:
                    seen_xml.update(new)
                    time.sleep(1)  # файл может ещё писаться
                    if self.callback:
                        self.callback(log_dir)
                    return
            time.sleep(3)
        print(f"[Monitor] Таймаут ожидания лога: {log_dir}")
