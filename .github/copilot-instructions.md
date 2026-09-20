# Copilot instructions for auto-prepress

## Build, run, test, and lint

This is a Windows Python desktop application. There is no project build system, test runner configuration, or lint configuration in the repository.

Install the Python dependencies from the repository root:

```powershell
python -m pip install -r requirements.txt
```

Run the application:

```powershell
python main.py
```

`run.bat` and `run_prem.bat` are machine-specific launchers with hard-coded working directories; use them only after checking their paths.

Useful validation commands:

```powershell
python -m compileall -q main.py config.py binding_types.py db ui services
python test_monitor.py
```

`test_monitor.py` is an interactive integration probe for the order-folder/PitStop monitor. It reads the configured database, requires a monitored order with an existing `in` directory, and waits for a PDF to be copied into that directory.

The `tests/` directory contains standalone OCR and GUI experiments rather than a test suite. Run one script at a time, for example:

```powershell
python tests\test4_totext.py
```

These scripts may require the sample files in `tests\`, Tesseract with Russian language data, Poppler, and the other external tools described in `README.md`. There is no supported single-test selector because the repository does not use pytest/unittest discovery.

## Architecture

- `main.py` is the entry point. It configures logging and the CustomTkinter theme, creates the drag-and-drop-capable `ui.app.App` when `tkinterdnd2` is available, and starts the Tk event loop.
- `ui/app.py` owns top-level navigation between `OrdersPage`, `OrderPage`, and `ImpositionPage`. `App` initializes the database and starts background order monitoring during startup; it stops all monitors on shutdown.
- `ui/order_page.py` manages the order form and specification workflow. A dropped/selected PDF or image is previewed, parsed by `services.spec_reader.read_spec`, and then saved as an `Order` plus related files under the configured order root. It also controls per-order monitoring and displays PitStop results.
- `services/spec_reader.py` first attempts PDF text extraction, then falls back to Poppler rendering and Tesseract/OpenCV OCR. It has separate parsing paths for the standard specification form and the Eksmo AIP form. Keep parser field names aligned with the `Order` model and the form's expectations.
- `services/monitor_manager.py` is the singleton lifecycle manager. It starts one `FolderMonitor` per monitored order and one application-wide `RefineRouter`.
- `services/folder_monitor.py` implements the production file pipeline:
  1. raw customer PDFs arriving under an order's `in` folder are copied to the shared Prinergy Refine hot folder and to the order-specific PitStop input;
  2. PitStop status is persisted in `.impo_status.json` by source filename stem/signature;
  3. `RefineRouter` uses the `<order-folder>~~` prefix to route Prinergy output back to the correct order's `in` folder;
  4. refined files are moved to the order root only when the original PitStop result is clean.
  It deliberately uses `PollingObserver` because order and hot folders may be on network/UNC paths.
- `ui/imposition_page.py` handles imposition photos, grid/signature editing, OCR/vision-assisted recognition, saved imposition JSON, and Preps template selection/generation. Local template directories are scanned live with a short TTL cache; slow archive directories are cached in `preps_template_cache` and refreshed only by the explicit archive refresh action.
- `services/tpl_generator.py` emits Preps 5 `.tpl`/`.job` text using the Preps-specific markers and CRLF output conventions. `ui/imposition_page.py` also parses real `.tpl` files and copies selected signature blocks into new templates.
- `db/models.py` mirrors the shared Printery/Django schema (`printery_*` tables) and adds ImpoFlow-specific order, imposition, and template-cache fields. `db/database.py` chooses SQLite or PostgreSQL from `config.CFG`, creates missing tables, and applies additive compatibility columns for an existing Printery database.

## Repository-specific conventions

- Configuration is loaded from `config.json` and merged over `config.py:DEFAULTS`. Runtime settings include Windows drive/UNC paths, database selection, Prinergy/PitStop folders, Poppler, Acrobat, Preps, Ollama, theme, and window dimensions. Do not hard-code a local developer's path into application logic; add or use a config key instead.
- Treat `config.json` as local deployment state. Preserve existing values when changing configuration behavior, and keep Windows paths correctly escaped in JSON. `config.save()` writes UTF-8 JSON with non-ASCII characters preserved.
- Database changes must remain compatible with the shared Printery schema. Prefer additive nullable columns and update both the SQLAlchemy model and `_migrate_extra_columns()` when an existing database needs a new ImpoFlow field. Do not drop or recreate shared tables.
- `Order.binding` is a `VARCHAR(4)` compatibility field, not the UI label. Use `binding_types.py` to normalize labels and convert them to/from codes (`SKR`, `KBS`, `HARD`, `SHT`, `SHK`, `REZ`, `PRU`, `FALC`). New UI/parser code should not invent a second binding mapping.
- Order folders are derived from the order number/name and are used as routing identifiers. Keep the actual `order.folder_path` as the source of truth; template naming code intentionally derives the folder-name component from that path so generated template names match monitor routing.
- Preps template matching depends on the filename shape `<number>_<name>_<trim WxH>_<paper WxH>_<binding>.tpl`. Matching normalizes Cyrillic/transliteration and uses binding-code-specific aliases. Preserve this convention when generating or renaming templates.
- Preps files are legacy Windows artifacts: generated `.tpl`/`.job` content uses CRLF; empty `.job` files are encoded as CP1251; template source is read/written with preserved newlines. Avoid normalizing these files through generic formatters.
- The monitor pipeline is asynchronous and idempotent by design. Preserve file-stability waits, source-stem status tracking, the `~~` routing separator, and the distinction between raw customer PDFs and Prinergy-refined PDFs. Do not send refined files through PitStop a second time.
- UI work runs on Tk's main thread, while OCR, monitor startup, and long-running external-file operations may run in background threads. Marshal widget updates back through Tk scheduling (`after`) and ensure monitor threads/observers are stopped on shutdown.
- External integrations are optional only at the UI/runtime boundary: Tesseract and Poppler are needed for OCR/PDF rendering, Ollama is used by imposition recognition, and Acrobat/Preps/Prinergy/PitStop are configured Windows applications/services. Report unavailable tools explicitly rather than silently treating an operation as successful.
- Keep user-facing text and existing domain terminology consistent with the current Russian UI and README. Avoid changing field meanings merely to make parser or database names look more generic.
