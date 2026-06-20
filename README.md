# ImpoReader Desktop v1.0

## Установка

```bash
pip install -r requirements.txt
```

### Tesseract OCR (для распознавания спецификаций)
1. Скачайте: https://github.com/UB-Mannheim/tesseract/wiki
2. Установите с языками **Russian + English**
3. Добавьте в PATH или укажите путь в pytesseract:
   ```python
   pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
   ```

### Poppler (для PDF → изображение)
Скачайте: https://github.com/oschwartz10612/poppler-windows/releases
Распакуйте, добавьте `bin\` в PATH.

### Ollama + qwen2-vl
```
ollama pull qwen2-vl:7b
```

## Запуск

```bash
python main.py
```

## Структура файлов

```
impo_app/
├── main.py                  # Точка входа
├── config.py                # Пути и настройки
├── config.json              # Сохранённые настройки (создаётся автоматически)
├── impo_reader.db           # SQLite база данных
├── requirements.txt
├── db/
│   ├── models.py            # SQLAlchemy модели
│   └── database.py          # Соединение с БД
├── ui/
│   ├── app.py               # Главное окно + навигация
│   ├── orders_page.py       # Список заказов
│   ├── order_page.py        # Страница заказа
│   └── imposition_page.py   # Спуск полос
├── services/
│   ├── spec_reader.py       # OCR спецификации
│   ├── folder_monitor.py    # Watchdog мониторинг папок
│   ├── pitstop_parser.py    # Парсинг логов PitStop
│   └── tpl_generator.py     # Генерация .tpl и .job для Preps 5
└── assets/
    ├── smartmarks.txt        # SmartMark блоки из test.tpl
    └── matrix.txt            # Matrix строки из test.tpl
```

## Настройка путей (config.py)

```python
"orders_root":    r"P:\\",
"preps_templates": [r"P:\\Preps\\Templates", r"\\\\NAS-PREPRESS\\Archives\\..."],
"pitstop_in":     r"D:\\Pitstop_\\out",
"pitstop_log":    r"D:\\Pitstop_\\Log",
"ollama_url":     "http://localhost:11434/api/generate",
"ollama_model":   "qwen2-vl:7b",
```

## Перенос SmartMarks из test.tpl

Скопируйте блоки `%SSiSmartMarkStart...%SSiSmartMarkEnd` из вашего шаблона
в файл `assets/smartmarks.txt`. Матрицы `%SSiPrshMatrix` → `assets/matrix.txt`.
