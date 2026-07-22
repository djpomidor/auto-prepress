"""
Мониторинг папки P:\\<order>\\in + маршрутизация файлов через общую
hot-папку Prinergy Evo Refine.

Пайплайн:
  1. Новый "сырой" PDF от заказчика в in\\:
       а) отправляется в ОБЩУЮ (одну на всё приложение) hot-папку
          Prinergy Evo Refine (config.prinergy_refine_in). Так как
          hot-папка общая для всех заказов, имя файла дополняется
          префиксом "<папка_заказа>~~" — чтобы потом можно было
          понять, какому заказу принадлежит результат;
       б) ОДНОВРЕМЕННО отправляется на проверку в PitStop —
          проверяется именно файл заказчика, отрефайненные файлы
          PitStop больше не проверяет.
  2. Результат проверки PitStop (ошибки есть/нет) запоминается по
     "стему" исходного имени файла (без расширения и без префикса),
     например "block" для "block.pdf".
  3. Prinergy обрабатывает файл и кладёт результат в свою общую папку
     вывода (config.prinergy_refine_out):
       многостраничный  → 0913_Заказ~~block.p0001.pdf, ...p0002.pdf...
       одностраничный   → 0913_Заказ~~календарь.новый.pdf
     Класс RefineRouter (отдельный, общий на всё приложение — не
     привязан к конкретному заказу) следит за этой папкой, по
     префиксу "<папка_заказа>~~" определяет нужный заказ, СНИМАЕТ
     префикс и переносит файл обратно в его in\\ под чистым именем
     (block.p0001.pdf). Дальше это уже подхватывает обычный
     FolderMonitor этого заказа — как если бы Prinergy сама вернула
     файл прямо в in\\.
  4. Когда очищенный отрефайненный файл появляется в in\\ — PitStop НЕ
     вызываем повторно. Смотрим на сохранённый результат проверки
     исходного файла с тем же "стемом":
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

# Разделитель между именем папки заказа и исходным именем файла,
# добавляется при отправке в общую hot-папку Prinergy Refine, чтобы
# потом сопоставить результат с нужным заказом. Символы "~~" валидны
# в именах файлов Windows и практически никогда не встречаются в
# реальных именах файлов заказчиков.
PREFIX_SEP = "~~"

# Имена файлов, которые Prinergy Evo кладёт после Refine
_REFINED_MULTI  = re.compile(r"^(?P<stem>.+)\.p(?P<num>\d{4,})\.pdf$", re.IGNORECASE)
_REFINED_SINGLE = re.compile(r"^(?P<stem>.+)\.новый\.pdf$", re.IGNORECASE)


def _refined_match(fname: str):
    return _REFINED_MULTI.match(fname) or _REFINED_SINGLE.match(fname)


def _is_refined(fname: str) -> bool:
    return bool(_refined_match(fname))


def _wait_file_stable_path(path: str, stable_secs: float = 2.0):
    """Ждём пока размер файла перестанет меняться (общая функция,
    используется и FolderMonitor, и RefineRouter)."""
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
                return
        else:
            unchanged = 0
        prev_size = size
        time.sleep(stable_secs)


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

        # Запоминаем что уже было (включая подпапки New, New1, New2...
        # — некоторые FTP/приёмники кладут обновлённые версии файла
        # именно туда, вместо перезаписи файла в корне in\)
        if os.path.isdir(in_path):
            self._known_files = set(self._scan_pdfs(in_path))
            log.debug(f"Уже в папке (рекурсивно): {self._known_files}")

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
        # Работает с сетевыми дисками, медленнее обычного Observer.
        # recursive=True — чтобы видеть файлы в подпапках New,
        # New1, New2... (некоторые приёмники/FTP кладут туда
        # обновлённые версии файла вместо перезаписи в корне in\).
        self._observer = PollingObserver(timeout=5)
        self._observer.schedule(Handler(), self.in_path, recursive=True)
        self._observer.start()
        log.info(f"Мониторинг запущен (PollingObserver, 5 сек, рекурсивно): {self.in_path}")

        # ВАЖНО: watchdog сообщает только о файлах, появившихся ПОСЛЕ
        # старта наблюдения. Файлы, которые уже лежали в in\ до
        # включения мониторинга (например, заказчик закинул их раньше,
        # чем был нажат тумблер "Мониторинг"), никогда не попадут в
        # on_created/on_modified — и раньше просто повисали в in\
        # навсегда. Поэтому сразу после старта явно проверяем и
        # обрабатываем такие "старые" необработанные файлы.
        self._process_existing_files()

    @staticmethod
    def _scan_pdfs(root_dir: str):
        """Рекурсивно находит все .pdf в папке (включая New/New1/...).
        Возвращает список ИМЁН файлов (basename)."""
        found = []
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for fn in filenames:
                if fn.lower().endswith(".pdf"):
                    found.append(fn)
        return found

    def _process_existing_files(self):
        if not os.path.isdir(self.in_path):
            return
        for dirpath, _dirnames, filenames in os.walk(self.in_path):
            for fname in filenames:
                if not fname.lower().endswith(".pdf"):
                    continue
                path = os.path.join(dirpath, fname)
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
                    log.info(f"Обрабатываю файл, обнаруженный при старте мониторинга: {path}")
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

        # 1) Отправляем в Prinergy Refine — с префиксом папки заказа,
        #    т.к. hot-папка ОБЩАЯ для всех заказов (см. RefineRouter)
        refine_in = config.CFG.get("prinergy_refine_in", "")
        if refine_in:
            try:
                os.makedirs(refine_in, exist_ok=True)
                prefixed_name = f"{self.order_folder_name}{PREFIX_SEP}{fname}"
                dst = os.path.join(refine_in, prefixed_name)
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

        log.info(f"Жду результат PitStop для {fname} (папки Log и Ok)")
        result = self._wait_for_pitstop_result(self.order_folder_name, fname, timeout=600)

        if result is True:
            self._mark_stem_status(stem, path, "ok")
            log.info(f"✓ PitStop: ошибок нет ({fname}) — жду отрефайненные файлы от Prinergy")
        elif result is False:
            self._mark_stem_status(stem, path, "error")
            log.warning(f"⚠ PitStop нашёл ошибки в {fname} — отрефайненные файлы останутся в in\\ без проверки")
        else:
            log.warning(f"Таймаут ожидания PitStop для {fname}")

        if self.callback:
            log_dir = os.path.join(config.CFG["pitstop_log"], self.order_folder_name)
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

    def _wait_for_pitstop_result(self, order_folder_name: str, fname: str, timeout: int = 600):
        """
        Ждём новый XML лог PitStop для файла заказчика — сразу в ДВУХ
        местах: pitstop_log (туда попадают проверки С ошибками) и
        pitstop_ok (туда PitStop Server кладёт оригинал + XML, когда
        ошибок НЕТ — pitstop_log в этом случае вообще не используется).
        Возвращаем:
          True  — ошибок не найдено
          False — есть ошибки
          None  — таймаут, лог не появился ни там, ни там
        """
        from services.pitstop_parser import list_pitstop_reports_for_order

        stem = os.path.splitext(fname)[0]
        deadline = time.time() + timeout
        seen_before = {r["fname"] for r in list_pitstop_reports_for_order(order_folder_name)}

        while time.time() < deadline:
            reports = list_pitstop_reports_for_order(order_folder_name)
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
        _wait_file_stable_path(path, stable_secs)


class RefineRouter:
    """
    Общий (НЕ привязанный к конкретному заказу) наблюдатель за папкой,
    куда Prinergy Evo Refine складывает отрефайненные файлы
    (config.prinergy_refine_out) — одна hot-папка Prinergy обслуживает
    все заказы сразу.

    Имя каждого отрефайненного файла начинается с префикса
    "<папка_заказа>~~" (см. FolderMonitor._handle_raw_file — именно
    так файл был отправлен на Refine). RefineRouter:
      1. по префиксу определяет папку нужного заказа;
      2. проверяет, что такая папка реально существует на диске;
      3. снимает префикс и переносит файл в in\\ этого заказа под
         чистым именем — дальше его подхватывает обычный
         FolderMonitor этого заказа, как будто Prinergy сама вернула
         файл прямо в in\\.

    Запускается один раз при старте приложения (см. MonitorManager),
    независимо от того, для каких заказов включён мониторинг —
    маршрутизация Refine-результатов не должна зависеть от тумблера
    "Мониторинг" на конкретном заказе.
    """

    def __init__(self):
        self._observer   = None
        self._processing = set()
        self.out_dir      = None

    def start(self):
        import config

        out_dir = (config.CFG.get("prinergy_refine_out") or "").strip()
        if not out_dir:
            log.warning(
                "prinergy_refine_out не задан в config.json — "
                "маршрутизация отрефайненных файлов от Prinergy ОТКЛЮЧЕНА"
            )
            return

        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            log.error(f"RefineRouter: не удалось открыть/создать {out_dir}: {e}")
            return
        self.out_dir = out_dir

        try:
            from watchdog.observers.polling import PollingObserver
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise RuntimeError("pip install watchdog")

        router = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                router._on_fs_event(event.src_path)

            def on_modified(self, event):
                router._on_fs_event(event.src_path)

            def on_moved(self, event):
                router._on_fs_event(event.dest_path)

        self._observer = PollingObserver(timeout=5)
        self._observer.schedule(Handler(), out_dir, recursive=False)
        self._observer.start()
        log.info(f"RefineRouter запущен (PollingObserver, 5 сек): {out_dir}")

        # Файлы, которые уже лежали в папке на момент старта — тоже
        # нужно разложить по заказам (см. аналогичную логику в
        # FolderMonitor.start / _process_existing_files).
        self._process_existing()

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            log.info("RefineRouter остановлен")

    def _process_existing(self):
        if not self.out_dir or not os.path.isdir(self.out_dir):
            return
        for fname in os.listdir(self.out_dir):
            if fname.lower().endswith(".pdf"):
                self._on_fs_event(os.path.join(self.out_dir, fname))

    def _on_fs_event(self, path: str):
        if not path.lower().endswith(".pdf"):
            return
        fname = os.path.basename(path)
        if fname in self._processing:
            return
        self._processing.add(fname)
        threading.Thread(target=self._route, args=(path, fname), daemon=True).start()

    def _route(self, path: str, fname: str):
        try:
            _wait_file_stable_path(path)

            if not os.path.isfile(path):
                return  # файл уже унесли (двойное срабатывание события)

            if PREFIX_SEP not in fname:
                log.warning(
                    f"RefineRouter: файл без префикса заказа, "
                    f"не могу определить получателя, пропускаю: {fname}"
                )
                return

            order_folder, real_name = fname.split(PREFIX_SEP, 1)

            # ВАЖНО: при рефайне ОДНОСТРАНИЧНОГО PDF в этой настройке
            # Prinergy НЕ дописывает суффикс — просто кладёт файл с
            # ТЕМ ЖЕ именем, что и на входе. Без явного суффикса
            # FolderMonitor не отличит такой результат от нового
            # "сырого" файла заказчика и отправит его на рефайн ещё
            # раз — зацикливание. Поэтому если имя не похоже ни на
            # многостраничный (.pNNNN.pdf), ни на уже промаркированный
            # одностраничный (.новый.pdf) результат — маркируем сами.
            if not _is_refined(real_name):
                _stem, _ext = os.path.splitext(real_name)
                real_name = f"{_stem}.новый{_ext}"
                log.info(f"RefineRouter: Prinergy не добавил суффикс — помечаю сам: {real_name}")

            import config
            orders_root = config.CFG.get("orders_root", "")
            target_dir = os.path.join(orders_root, order_folder)
            if not os.path.isdir(target_dir):
                log.error(
                    f"RefineRouter: папка заказа '{order_folder}' не найдена "
                    f"на диске — файл {fname} остаётся в {self.out_dir}"
                )
                return

            in_dir = os.path.join(target_dir, "in")
            try:
                os.makedirs(in_dir, exist_ok=True)
                dst = os.path.join(in_dir, real_name)
                shutil.move(path, dst)
                log.info(f"✓ RefineRouter: {fname} → {dst}")
            except Exception as e:
                log.error(f"RefineRouter: не удалось перенести {fname} в {in_dir}: {e}")
        except Exception as e:
            log.error(f"RefineRouter: ошибка маршрутизации {fname}: {e}")
        finally:
            self._processing.discard(fname)
