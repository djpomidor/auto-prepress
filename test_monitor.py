"""
Тест мониторинга папки.
Запуск: python test_monitor.py
Затем скопируйте любой PDF в папку in заказа на диске P:
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from db.database import init_db, get_session
from db.models import Order

print("=" * 55)
print("  ImpoReader — Тест мониторинга")
print("=" * 55)

# Показываем конфиг
print(f"\n[Конфиг]")
print(f"  pitstop_in  = {config.CFG['pitstop_in']}")
print(f"  pitstop_log = {config.CFG['pitstop_log']}")

# Показываем заказы с мониторингом
init_db()
session = get_session()
orders = session.query(Order).all()
session.close()

print(f"\n[Заказы в БД: {len(orders)}]")
for o in orders:
    mon = "● МОН" if o.monitoring else "  ---"
    print(f"  {mon}  #{o.number:04d}  {o.name}  →  {o.folder_path or '(нет пути)'}")

# Выбираем заказ для теста
monitored = [o for o in orders if o.monitoring and o.folder_path]
if not monitored:
    print("\n⚠ Нет заказов с включённым мониторингом.")
    print("  Включите мониторинг на странице заказа и запустите снова.")
    sys.exit(0)

order = monitored[0]
in_path = os.path.join(order.folder_path, "in")
folder_name = os.path.basename(order.folder_path)
pitstop_out = os.path.join(config.CFG["pitstop_in"], folder_name)

print(f"\n[Тестируем заказ #{order.number:04d} {order.name}]")
print(f"  Папка in    : {in_path}")
print(f"  PitStop out : {pitstop_out}")
print(f"  in существует: {os.path.isdir(in_path)}")
print(f"  P: доступен  : {os.path.isdir(os.path.dirname(in_path))}")

# Проверяем доступность pitstop_out
try:
    os.makedirs(pitstop_out, exist_ok=True)
    test_file = os.path.join(pitstop_out, "_test_write.tmp")
    with open(test_file, "w") as f:
        f.write("test")
    os.remove(test_file)
    print(f"  D: запись   : ✓ OK")
except Exception as e:
    print(f"  D: запись   : ✗ ОШИБКА — {e}")
    sys.exit(1)

# Запускаем монитор
print(f"\n[Запускаю PollingObserver...]")
print(f"  Скопируйте PDF в: {in_path}")
print(f"  Нажмите Ctrl+C для выхода\n")

from services.folder_monitor import FolderMonitor
import time

def on_log(log_dir):
    print(f"\n✓ XML лог найден: {log_dir}")

monitor = FolderMonitor(
    in_path=in_path,
    order_folder_name=folder_name,
    callback=on_log,
)
monitor.start()

try:
    while True:
        # Каждые 5 сек показываем содержимое папки
        if os.path.isdir(in_path):
            files = os.listdir(in_path)
            pdfs = [f for f in files if f.lower().endswith(".pdf")]
            print(f"  [{time.strftime('%H:%M:%S')}] PDF в папке in: {pdfs or '(пусто)'}")
        time.sleep(5)
except KeyboardInterrupt:
    monitor.stop()
    print("\nОстановлено.")