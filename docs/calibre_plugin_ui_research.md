# Calibre plugin UI research

**Date:** 2026-10-10
**Checked against:** calibre 8.11.1 (installed locally, Qt 6.8.2), its source at tag `v8.11.1`, the official plugin manual, and two installed plugins (Find Duplicates, KFX Output). Module imports were tested with `calibre-debug -c`.
**Purpose:** input for the v0.5 Calibre plugin (see `v1_release_definition.md` §2).

---

## 1. How an interface plugin works

- A plugin is a `.zip` of Python files. It runs inside the calibre process, with calibre's bundled Python and Qt 6.
- A plugin that adds something to the main window is an **interface action**. It has two classes:
  - `InterfaceActionBase` in `__init__.py`. It loads without GUI libraries and points to the real class via `actual_plugin = 'calibre_plugins.<name>.ui:<Class>'`.
  - `InterfaceAction` in `ui.py`. It is created once at startup and receives the main window as `self.gui`.
- `action_spec = (text, icon, tooltip, shortcut)` defines one `QAction`. It becomes `self.qaction`, the clickable button or menu item.
- With `action_add_menu = True`, the button gets a dropdown menu. `popup_type` controls whether a click runs the action or opens the menu.
- Lifecycle hooks:
  - `genesis()`: build menus and connect signals.
  - `initialization_complete()` and `gui_layout_complete()`.
  - `library_changed(db)`.
  - `location_selected(loc)`: switch between library and device views. Enable or disable actions here.
  - `shutting_down()`.
  - `tag_browser_context_action(index)`: add items to the Tag browser right-click menu.
  - `accepts_drops`, with `accept_enter_event`, `accept_drag_move_event` and `drop_event`. Drop handlers must return quickly.
- `create_menu_action()` adds sub-actions. Each registers a rebindable keyboard shortcut under a globally unique name.

## 2. Where a user can reach a plugin

Ten placement locations (`InterfaceAction.all_locations`, labels from `preferences/toolbar.py`):

| Key | Location |
|---|---|
| `toolbar` | Main toolbar |
| `toolbar-device` | Main toolbar when a device is connected |
| `toolbar-child` | Optional second toolbar |
| `searchbar` | Buttons on the search bar |
| `menubar` | Menu bar (top of screen on macOS) |
| `menubar-device` | Menu bar when a device is connected |
| `context-menu` | Right-click menu on books in the library |
| `context-menu-split` | Right-click menu on the split book list |
| `context-menu-device` | Right-click menu on books on the device |
| `context-menu-cover-browser` | Right-click menu on the Cover browser |

- **The user chooses placement.** On first install, calibre shows a dialog asking where to add the action (`check_for_add_to_toolbars` in `preferences/plugins.py`). Updates never ask again. The user can change placement later under Preferences → Toolbars & menus.
- The plugin can only restrict placement: `dont_add_to` blocks locations and `dont_remove_from` pins them.
- **Other access paths:**
  - **Keyboard shortcut:** a default comes from `action_spec`, and the user can rebind it under Preferences → Shortcuts.
  - **Tag browser:** right-click items, added through `tag_browser_context_action`.
  - **Drag and drop:** books or files dropped onto the plugin's button.
  - **Plugin's own dialogs:** any dialog the plugin opens from its action.
  - **Settings:** Preferences → Plugins → *Customize plugin*.
- **Settings dialog:** `is_customizable()`, `config_widget()` and `save_settings()`. Calibre wraps the widget in a resizable, scrolling dialog with OK and Cancel, and saves its geometry. An optional `validate()` can block saving. `do_user_config()` opens the same dialog from the plugin's own menu. Settings are stored with `JSONConfig('plugins/<name>')`.

## 3. Components available

Verified importable in calibre 8.11.1:

- **Qt Widgets**, imported from `qt.core`: any dialog, form, list, table, tab, progress bar or file picker. The Qt version is 6.8.2.
- **Calibre helpers:**
  - `error_dialog`, `warning_dialog`, `info_dialog` and `question_dialog`, each with an expandable details box;
  - `calibre.gui2.dialogs.progress.ProgressDialog`;
  - `calibre.gui2.widgets2.Dialog`, which remembers its size and position;
  - `choose_files` and `choose_dir`, which remember the last location;
  - `gprefs` and `JSONConfig`.
- **Background jobs**, both shown in the bottom-right Jobs indicator and the Jobs dialog, with progress, a cancel button and a viewable log:
  - `ThreadedJob`: runs in a thread inside calibre. The job function receives `abort` (an Event to poll), `log`, and `notifications` (a queue of `(fraction, message)` tuples). `max_concurrent_count` limits jobs of the same type. `killable` controls cancel. The completion callback is not called when the user kills the job.
  - `gui.job_manager.run_job(...)`: runs in a separate calibre worker process.
- **QtWebEngine** (`qt.webengine`) is importable.
- **QtMultimedia** is not exposed through the `qt.*` shim, but `PyQt6.QtMultimedia` imports. Audio playback inside the plugin is therefore technically possible.
- **Icons and translations:** `get_icons()` and `get_resources()` load files from the zip. Calibre's built-in icons can also be used by name. Strings are wrapped in `_()`, `load_translations()` is called per file, and compiled `.mo` files go in `translations/`.

## 4. Limits

1. **No plugin UI in the e-book viewer or the content server (web UI).** `calibre.customize` has no viewer plugin class. The e-book editor has its own separate type (`EditBookToolPlugin`).
2. **No supported API for docked panels, new views, or Book details layout.** A plugin runs in-process and can reach `self.gui`, so changes are technically possible. They are undocumented and can break between calibre versions.
3. **Never block the GUI thread.** Long work belongs in a job.
4. **Shortcut collisions** are resolved silently. The manual advises choosing unusual key combinations.
5. **Compiled Python packages do not load reliably in calibre's Python.** This is why the engine runs outside calibre (see `v1_release_definition.md` §1).
6. **Shared namespaces:** the plugin import name and the `plugins/<name>` config name must be globally unique.

## 5. UI standards

Calibre has **no official UI guideline** for plugins. Neither the manual nor MobileRead offers one. The de facto conventions come from long-standing plugins, especially kiwidude's (Find Duplicates ships shared `common_menus`, `common_dialogs` and `common_widgets` modules):

- One toolbar button with a dropdown of sub-actions.
- Menu items that open a dialog end with "…".
- "Customize plugin…" and "Help" are the last menu items.
- Calibre built-in icons are preferred where they fit.
- Strings are translatable.
- Results and errors go through calibre's own dialogs and the Jobs list.

## 6. Alternative plugin type: conversion output

An `OutputFormatPlugin` would make "M4B" an output format in calibre's own *Convert books* dialog. Its options would appear there through `gui_configuration_widget`. KFX Output uses this pattern and calls an external program (Kindle Previewer). It would feel native, but it gives less control over jobs and progress, and its options live inside the conversion dialog. **Not chosen for v1.0.** The interface action stays.

## 7. Implications for the v0.5 plugin

- **Entry points:** one "Convert to Audiobook" action with a short dropdown, offered for the toolbar and the book-list right-click menu. `dont_add_to` should cover the device locations, because the plugin converts library books only.
- **Jobs:** one `ThreadedJob` per book with `max_concurrent_count=1`. The job runs the engine as a subprocess, maps `--progress json` lines to `(fraction, message)` notifications, maps `abort` to SIGTERM, and writes engine stderr to the job log.
- **Settings:** the standard *Customize plugin* dialog, also linked from the dropdown.

## 8. Owner decisions (2026-10-10)

- Save this research: **yes** (this file).
- Voice preview: **kept as approved** in `v1_release_definition.md` §2 ("Preview a voice on a short sample"). An earlier "no" was based on a recommendation that missed the approved scope.
- One-page interface spec for v0.5: **not yet**.

### Configuration and prompting (2026-10-10)

Approved by the owner. These add to the v1.0 scope and were written into `v1_release_definition.md` (§2, §5 and §6) on 2026-10-10.

**Visual identity:** the plugin gets its own identity, not a brand borrowed from another project. **UI direction:** not chosen yet. The explorations are in `design/`.

1. **Saved defaults** in the *Customize plugin* dialog: the four approved settings (engine path, backend, voice per language, speed), plus:
   - **Existing M4B:** ask / replace / skip. The default is **ask**.
   - **Save a copy to a folder:** already in scope. Off by default.
2. **"Convert with options…"** in the dropdown: voice, speed and language for one batch, without changing the saved defaults.
3. **Metadata from the calibre record:** title, author and cover come from calibre, not from the ePub. This needs engine flags in the v0.4 plugin contract.
4. **When the plugin asks:**
   - **First click after install (once):** run `doctor`; show engine setup if the engine is missing; show the model-download size notice; summarize the defaults, with "Change settings…".
   - **Before each batch, only when a decision is needed:** language not detected or unsupported; M4B already present; no ePub format. All questions go in **one** dialog.
   - **During a job:** never. Errors go to the job log.
   - **After the first finished audiobook (once):** the result notice, with "Change defaults…".
5. **Not in v1.0:** per-book saved settings, because they would need a custom column or a private store.
6. **Fixed, not configurable, in v1.0:** bitrate, mono, sample rate, loudness target, pause lengths, front-matter dropping, worker count.

## Sources

- calibre manual, *Writing your own plugins*: https://manual.calibre-ebook.com/creating_plugins.html
- calibre API documentation for plugins: https://manual.calibre-ebook.com/plugins.html
- calibre source `v8.11.1`:
  - `src/calibre/gui2/actions/__init__.py`
  - `src/calibre/gui2/preferences/toolbar.py`
  - `src/calibre/gui2/preferences/plugins.py`
  - `src/calibre/gui2/threaded_jobs.py`
  - `src/calibre/gui2/jobs.py`
  - `src/calibre/customize/__init__.py`
- Installed plugins inspected: Find Duplicates (`action.py`, `common_menus.py`), KFX Output (`__init__.py`).
- MobileRead: https://www.mobileread.com/forums/showthread.php?p=1240062 and https://www.mobileread.com/forums/showthread.php?p=2969941
