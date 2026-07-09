"""
Мониторинг папки P:\\<order>\\in.

Пайплайн:
  1. Новый "сырой" PDF от заказчика в in\\:
       а) отправляется в hot-папку Prinergy Evo Refine
          (config.prinergy_refine_in);
       б) ОДНОВРЕМЕННО отправляется на проверку в PitStop —
          проверяется именно файл заказчика, отрефайненные файлы
          PitStop больше не проверяет.
  2. Результат проверки (ошибки есть / нет) запоминается по "стему"
     имени файла (без расширения), например "block" для "block.pdf".
  3. Prinergy обрабатывает файл и кладёт результат ОБРАТНО в ту же
     папку in\\ (так настроена сама hot-папка Prinergy):
       многостраничный  → block.p0001.pdf, block.p0002.pdf, ...
       одностраничный   → календарь.новый.pdf
  4. Когда такой отрефайненный файл появляется — PitStop НЕ вызываем.
     Смотрим на сохранённый результат проверки исходного файла с тем
     же "стемом":
       ошибок не было → переносим файл из in\\ в корень папки заказа;
       были ошибки    → оставляем файл в in\\ как есть.
  5. Если исходный файл заказчика в in\\ изменился (новый размер/дата
     изменения) — проверка запускается заново.

ВАЖНО: для сетевых дисков (SMB/UNC) используем PollingObserver
вместо стандартного Observer — он не зависит от уведомлений ОС.
"""
import os
import re
import json
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

# Имена файлов, которые Prinergy Evo кладёт обратно после Refine
_REFINED_MULTI  = re.compile(r"^(?P<stem>.+)\.p(?P<num>\d{4,})\.pdf$", re.IGNORECASE)
_REFINED_SINGLE = re.compile(r"^(?P<stem>.+)\.новый\.pdf$", re.IGNORECASE)


def _refined_match(fname: str):
    return _REFINED_MULTI.match(fname) or _REFINED_SINGLE.match(fname)


def _is_refined(fname: str) -> bool:
    return bool(_refined_match(fname))


class FolderMonitor:
    def __init__(self, in_path: str, order_folder_name: str,
                 callback: Callable = None):
        self.in_path            = in_path
        self.order_folder_name  = order_folder_name
        self.callback           = callback
        self._observer          = None
        self._known_files       = set()
        self._processing        = set()  # файлы в процессе обработки

        # Статусы проверки PitStop, ключ — "стем" имени файла
        # заказчика (без расширения), например "block" для "block.pdf".
        # Отрефайненные файлы (block.p0001.pdf...) используют этот же
        # статус — сами PitStop не проходят.
        self._status_path = os.path.join(
            os.path.dirname(in_path.rstrip("\\/")), ".impo_status.json"
        )
        self._status = self._load_status()

        # Запоминаем что уже было
        if os.path.isdir(in_path):
            self._known_files = set(
                f for f in os.listdir(in_path)
                if f.lower().endswith(".pdf")
            )
            log.debug(f"Уже в папке: {self._known_files}")

    # ── СТАТУСЫ (для правила "не проверять повторно") ───────────────
    def _load_status(self) -> dict:
        try:
            with open(self._status_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_status(self):
        try:
            with open(self._status_path, "w", encoding="utf-8") as f:
                json.dump(self._status, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _file_signature(self, path: str):
        try:
            st = os.stat(path)
            return f"{st.st_size}:{int(st.st_mtime)}"
        except OSError:
            return None

    def _mark_stem_status(self, stem: str, raw_path: str, status: str):
        """status: 'ok' | 'error'"""
        self._status[stem] = {
            "signature": self._file_signature(raw_path),
            "status":    status,
            "checked":   time.time(),
        }
        self._save_status()

    def _already_checked_with_errors(self, stem: str, raw_path: str) -> bool:
        """True — файл заказчика с этим стемом уже проверялся с этой
        же сигнатурой (размер+дата) и по нему были ошибки."""
        info = self._status.get(stem)
        if not info:
            return False
        return (info.get("status") == "error"
                and info.get("signature") == self._file_signature(raw_path))

    def _raw_file_changed(self, stem: str, raw_path: str) -> bool:
        info = self._status.get(stem)
        if not info:
            return False
        return info.get("signature") != self._file_signature(raw_path)

    # ── НАБЛЮДЕНИЕ ЗА ПАПКОЙ ─────────────────────────────────────────
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

        # ВАЖНО: watchdog сообщает только о файлах, появившихся ПОСЛЕ
        # старта наблюдения. Файлы, которые уже лежали в in\ до
        # включения мониторинга (например, заказчик закинул их раньше,
        # чем был нажат тумблер "Мониторинг"), никогда не попадут в
        # on_created/on_modified — и раньше просто повисали в in\
        # навсегда. Поэтому сразу после старта явно проверяем и
        # обрабатываем такие "старые" необработанные файлы.
        self._process_existing_files()

    def _process_existing_files(self):
        if not os.path.isdir(self.in_path):
            return
        for fname in os.listdir(self.in_path):
            if not fname.lower().endswith(".pdf"):
                continue
            path = os.path.join(self.in_path, fname)
            if fname in self._processing:
                continue

            if _is_refined(fname):
                needs_processing = True  # решение всегда по статусу родителя — безопасно повторить
            else:
                stem = os.path.splitext(fname)[0]
                info = self._status.get(stem)
                needs_processing = (
                    not info or info.get("signature") != self._file_signature(path)
                )

            if needs_processing:
                log.info(f"Обрабатываю файл, обнаруженный при старте мониторинга: {fname}")
                self._processing.add(fname)
                threading.Thread(
                    target=self._route_new_file, args=(path, fname), daemon=True
                ).start()

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
        if fname in self._processing:
            return

        if _is_refined(fname):
            # Отрефайненные файлы обрабатываем идемпотентно при
            # каждом появлении/изменении — PitStop они не проходят,
            # просто смотрим статус исходного файла-родителя.
            self._processing.add(fname)
            threading.Thread(
                target=self._route_new_file, args=(path, fname), daemon=True
            ).start()
            return

        # Файл заказчика (не отрефайненный)
        stem = os.path.splitext(fname)[0]
        if fname in self._known_files:
            if not self._raw_file_changed(stem, path):
                return  # уже видели, не менялся — пропускаем
        else:
            self._known_files.add(fname)

        self._processing.add(fname)
        log.info(f"Файл заказчика к обработке: {fname}")
        threading.Thread(
            target=self._route_new_file, args=(path, fname), daemon=True
        ).start()

    def _route_new_file(self, path: str, fname: str):
        try:
            self._wait_file_stable(path)

            if _is_refined(fname):
                self._handle_refined_file(path, fname)
            else:
                stem = os.path.splitext(fname)[0]
                if self._already_checked_with_errors(stem, path):
                    log.info(f"Пропускаю — уже проверялся, ошибки, файл не менялся: {fname}")
                    return
                self._handle_raw_file(path, fname)
        except Exception as e:
            log.error(f"Ошибка обработки {fname}: {e}")
        finally:
            self._processing.discard(fname)

    # ── ФАЙЛ ЗАКАЗЧИКА: Refine + PitStop (проверяем ИСХОДНЫЙ файл) ───
    def _handle_raw_file(self, path: str, fname: str):
        import config

        stem = os.path.splitext(fname)[0]

        # 1) Отправляем в Prinergy Refine
        refine_in = config.CFG.get("prinergy_refine_in", "")
        if refine_in:
            try:
                os.makedirs(refine_in, exist_ok=True)
                dst = os.path.join(refine_in, fname)
                if os.path.exists(dst):
                    log.info(f"Уже отправлен в Refine ранее: {dst}")
                else:
                    shutil.copy2(path, dst)
                    log.info(f"→ Отправлено в Prinergy Refine: {dst}")
            except Exception as e:
                log.error(f"Не удалось отправить {fname} в Prinergy Refine: {e}")
        else:
            log.warning(
                "prinergy_refine_in не задан в config.json — "
                f"файл {fname} НЕ отправлен на Refine"
            )

        # 2) Отправляем ИСХОДНЫЙ файл заказчика на проверку PitStop
        #    (отрефайненные файлы PitStop больше не проверяет)
        pitstop_out = os.path.join(config.CFG["pitstop_in"], self.order_folder_name)
        try:
            os.makedirs(pitstop_out, exist_ok=True)
            dst = os.path.join(pitstop_out, fname)
            if os.path.exists(dst):
                log.info(f"Уже отправлен в PitStop ранее: {dst}")
            else:
                shutil.copy2(path, dst)
                log.info(f"→ Отправлено в PitStop: {dst}")
        except Exception as e:
            log.error(f"Не удалось скопировать {fname} в PitStop: {e}")
            return

        log_dir = os.path.join(config.CFG["pitstop_log"], self.order_folder_name)
        log.info(f"Жду результат PitStop для {fname} в: {log_dir}")
        result = self._wait_for_pitstop_result(log_dir, fname, timeout=600)

        if result is True:
            self._mark_stem_status(stem, path, "ok")
            log.info(f"✓ PitStop: ошибок нет ({fname}) — жду отрефайненные файлы от Prinergy")
        elif result is False:
            self._mark_stem_status(stem, path, "error")
            log.warning(f"⚠ PitStop нашёл ошибки в {fname} — отрефайненные файлы останутся в in\\ без проверки")
        else:
            log.warning(f"Таймаут ожидания PitStop для {fname}")

        if self.callback:
            self.callback(log_dir)

    # ── ОТРЕФАЙНЕННЫЙ ФАЙЛ: без PitStop, решение по статусу родителя ─
    def _handle_refined_file(self, path: str, fname: str):
        m = _refined_match(fname)
        stem = m.group("stem")

        status = self._wait_for_stem_status(stem, timeout=600)

        if status == "ok":
            self._move_to_order_root(path, fname)
        elif status == "error":
            log.info(f"Оставляю в in\\ (у исходного файла заказчика были ошибки): {fname}")
        else:
            log.warning(
                f"Не удалось получить результат проверки исходного файла "
                f"для {fname} (таймаут) — файл остаётся в in\\"
            )

    def _wait_for_stem_status(self, stem: str, timeout: int = 600):
        """Ждём пока для данного стема появится результат проверки
        PitStop (сохранённый _handle_raw_file). Возвращает 'ok',
        'error' или None по таймауту."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            info = self._status.get(stem)
            if info and info.get("status") in ("ok", "error"):
                return info["status"]
            time.sleep(3)
        return None

    def _wait_for_pitstop_result(self, log_dir: str, fname: str, timeout: int = 600):
        """
        Ждём новый XML лог PitStop для файла заказчика и возвращаем:
          True  — ошибок не найдено
          False — есть ошибки
          None  — таймаут, лог не появился
        """
        from services.pitstop_parser import list_pitstop_reports

        stem = os.path.splitext(fname)[0]
        deadline = time.time() + timeout
        seen_before = {r["fname"] for r in list_pitstop_reports(log_dir)}

        while time.time() < deadline:
            reports = list_pitstop_reports(log_dir)
            new = [r for r in reports if r["fname"] not in seen_before]
            if new:
                # Предпочитаем отчёт с тем же именем (без расширения),
                # что и PDF — иначе берём просто самый свежий новый
                matched = [r for r in new
                           if os.path.splitext(r["fname"])[0] == stem]
                newest = max(matched or new, key=lambda r: r["dt"])
                log.info(f"XML лог найден для {fname}: {newest['fname']}")
                return newest["errors"] == 0
            time.sleep(3)
        return None

    def _move_to_order_root(self, path: str, fname: str):
        """Переносит отрефайненный файл (после успешной проверки
        исходника PitStop) из in\\ в корень папки заказа P:\\<order>\\."""
        order_root = os.path.dirname(self.in_path.rstrip("\\/"))
        try:
            dst = os.path.join(order_root, fname)
            shutil.move(path, dst)
            log.info(f"✓ Ошибок нет — перенесено в корень заказа: {dst}")
        except Exception as e:
            log.error(f"Не удалось перенести {fname} в корень заказа: {e}")

    # ── ОБЩЕЕ ─────────────────────────────────────────────────────
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
