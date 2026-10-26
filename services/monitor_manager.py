"""
Менеджер мониторинга — запускает слежение за всеми заказами
у которых monitoring=True при старте приложения.
"""
import os
import logging
from typing import Callable

log = logging.getLogger("MonitorManager")


class MonitorManager:
    """Singleton — хранит все активные мониторы."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._monitors = {}  # order_id → FolderMonitor
            cls._instance._refine_router = None
            cls._instance._pitstop_log_archiver = None
        return cls._instance

    def start_all(self, callback: Callable = None):
        """Запускает мониторинг всех заказов с monitoring=True, а
        также единственный на всё приложение RefineRouter (не привязан
        к конкретному заказу — маршрутизирует отрефайненные Prinergy
        файлы по всем заказам сразу, независимо от их тумблера
        "Мониторинг")."""
        self.start_refine_router()
        self.start_pitstop_log_archiver()

        from db.database import get_session
        from db.models import Order

        session = get_session()
        try:
            orders = session.query(Order).filter(
                Order.monitoring == True,
                Order.folder_path != None,
                Order.folder_path != "",
            ).all()
        finally:
            session.close()

        log.info(f"Автозапуск мониторинга: {len(orders)} заказов")

        for order in orders:
            self.start_order(order.id, order.folder_path, callback)

    def start_refine_router(self):
        """Запускает единственный (не per-order) наблюдатель за общей
        папкой вывода Prinergy Refine — см. services.folder_monitor.RefineRouter."""
        if self._refine_router is not None:
            return  # уже запущен
        from services.folder_monitor import RefineRouter
        try:
            router = RefineRouter()
            router.start()
            self._refine_router = router
            log.info("✓ RefineRouter запущен")
        except Exception as e:
            log.error(f"Ошибка запуска RefineRouter: {e}")

    def stop_refine_router(self):
        if self._refine_router:
            self._refine_router.stop()
            self._refine_router = None
            log.info("RefineRouter остановлен")

    def start_pitstop_log_archiver(self):
        """Архивирует отчёты из общей папки PitStop в папки заказов."""
        if self._pitstop_log_archiver is not None:
            return
        from services.folder_monitor import PitStopLogArchiver
        try:
            archiver = PitStopLogArchiver()
            archiver.start()
            self._pitstop_log_archiver = archiver
        except Exception as e:
            log.error(f"Ошибка запуска PitStopLogArchiver: {e}")

    def stop_pitstop_log_archiver(self):
        if self._pitstop_log_archiver:
            self._pitstop_log_archiver.stop()
            self._pitstop_log_archiver = None

    def start_order(self, order_id: int, folder_path: str,
                    callback: Callable = None):
        """Запускает мониторинг одного заказа."""
        from services.folder_monitor import FolderMonitor

        if order_id in self._monitors:
            return  # уже запущен

        in_path     = os.path.join(folder_path, "in")
        folder_name = os.path.basename(folder_path)

        if not os.path.isdir(in_path):
            log.warning(f"Папка не найдена, пропускаем: {in_path}")
            return

        try:
            monitor = FolderMonitor(
                in_path=in_path,
                order_folder_name=folder_name,
                callback=callback,
            )
            monitor.start()
            self._monitors[order_id] = monitor
            log.info(f"✓ Запущен #{order_id}: {in_path}")
        except Exception as e:
            log.error(f"Ошибка запуска #{order_id}: {e}")

    def stop_order(self, order_id: int):
        monitor = self._monitors.pop(order_id, None)
        if monitor:
            monitor.stop()
            log.info(f"Остановлен #{order_id}")

    def stop_all(self):
        for order_id, monitor in list(self._monitors.items()):
            monitor.stop()
        self._monitors.clear()
        self.stop_refine_router()
        self.stop_pitstop_log_archiver()
        log.info("Все мониторы остановлены")

    def is_running(self, order_id: int) -> bool:
        return order_id in self._monitors
