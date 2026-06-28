"""
Мониторинг папки P:\<order>\in
При появлении PDF копирует в D:\Pitstop_\out\<order_folder>\
Затем ждёт XML лог от PitStop и вызывает callback.

ВАЖНО: для сетевых дисков (SMB/UNC) используем PollingObserver
вместо стандартного Observer — он не зависит от уведомлений ОС.
"""
import os
import shutil
import threading
import time
import logging
from typing import Callable

log = logging.getLogger("FolderMonitor")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


class FolderMonitor:
    def __init__(self, in_path: str, order_folder_name: str,
                 callback: Callable = None):
        self.in_path            = in_path
        self.order_folder_name  = order_folder_name
        self.callback           = callback
        self._observer          = None
        self._known_files       = set()
        self._processing        = set()  # файлы в процессе обработки

        # Запоминаем что уже было
        if os.path.isdir(in_path):
            self._known_files = set(
                f for f in os.listdir(in_path)
                if f.lower().endswith(".pdf")
            )
            log.debug(f"Уже в папке: {self._known_files}")

    def start(self):
        try:
            from watchdog.observers.polling import PollingObserver
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise RuntimeError("pip install watchdog")

        monitor = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                monitor._on_fs_event(event.src_path)

            def on_modified(self, event):
                monitor._on_fs_event(event.src_path)

            def on_moved(self, event):
                monitor._on_fs_event(event.dest_path)

        # PollingObserver — опрашивает папку каждые N секунд
        # Работает с сетевыми дисками, медленнее обычного Observer
        self._observer = PollingObserver(timeout=5)
        self._observer.schedule(Handler(), self.in_path, recursive=False)
        self._observer.start()
        log.info(f"Мониторинг запущен (PollingObserver, 5 сек): {self.in_path}")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            log.info(f"Мониторинг остановлен: {self.in_path}")

    def _on_fs_event(self, path: str):
        if not path.lower().endswith(".pdf"):
            return
        fname = os.path.basename(path)
        if fname in self._known_files or fname in self._processing:
            return
        self._known_files.add(fname)
        self._processing.add(fname)
        log.info(f"Новый PDF: {fname}")
        threading.Thread(
            target=self._handle_new_pdf,
            args=(path, fname),
            daemon=True,
        ).start()

    def _handle_new_pdf(self, pdf_path: str, fname: str):
        import config

        try:
            # Ждём пока файл полностью скопируется
            self._wait_file_stable(pdf_path)

            # Путь назначения
            pitstop_out = os.path.join(
                config.CFG["pitstop_in"],
                self.order_folder_name,
            )
            log.info(f"Копирую {fname} → {pitstop_out}")

            os.makedirs(pitstop_out, exist_ok=True)
            dst = os.path.join(pitstop_out, fname)

            if os.path.exists(dst):
                log.info(f"Файл уже есть в PitStop Out: {dst}")
            else:
                shutil.copy2(pdf_path, dst)
                log.info(f"✓ Скопировано: {dst}")

            # Ждём XML лог
            if self.callback:
                log_dir = os.path.join(
                    config.CFG["pitstop_log"],
                    self.order_folder_name,
                )
                log.info(f"Жду XML лог в: {log_dir}")
                self._wait_for_log(log_dir, timeout=600)

        except Exception as e:
            log.error(f"Ошибка обработки {fname}: {e}")
        finally:
            self._processing.discard(fname)

    def _wait_file_stable(self, path: str, stable_secs: float = 2.0):
        """Ждём пока размер файла перестанет меняться."""
        prev_size = -1
        unchanged = 0
        for _ in range(60):
            try:
                size = os.path.getsize(path)
            except OSError:
                time.sleep(1)
                continue
            if size > 0 and size == prev_size:
                unchanged += 1
                if unchanged >= 2:
                    log.debug(f"Файл стабилен ({size} байт): {path}")
                    return
            else:
                unchanged = 0
            prev_size = size
            time.sleep(stable_secs)

    def _wait_for_log(self, log_dir: str, timeout: int = 600):
        """Ждём XML файл в папке лога PitStop."""
        deadline = time.time() + timeout
        seen = set()
        while time.time() < deadline:
            if os.path.isdir(log_dir):
                xmls = {
                    f for f in os.listdir(log_dir)
                    if f.lower().endswith(".xml")
                }
                new = xmls - seen
                if new:
                    seen.update(new)
                    time.sleep(1)
                    log.info(f"XML лог найден: {new}")
                    if self.callback:
                        self.callback(log_dir)
                    return
            time.sleep(3)
        log.warning(f"Таймаут ожидания XML лога: {log_dir}")
