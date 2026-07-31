# Screenshot inventory

This documents every screenshot in `docs/screenshots/` that's referenced from
the [README](../README.md) or elsewhere in `docs/`, per the standard fields
below. If you add, replace, or remove a screenshot, update this file in the
same change.

**About "application version" below:** these screenshots were captured from
a source checkout, not from a packaged release build. `chirp/__init__.py`
hardcodes `CHIRP_VERSION = "py3dev"`, and that string is what the running
app's Help > About dialog shows in these captures — it is **not** updated by
the AppImage or macOS packaging steps (see
[macos-packaging.md](macos-packaging.md)). The UI/feature content shown is
still current as of the commit noted for each screenshot; only the literal
version string differs from a packaged release like `1.12.0`.

**About "platform" below:** all current screenshots were captured on Linux,
using the same wx/GTK3 rendering the AppImage ships (light system-gray
window chrome, generic Linux widget styling). None have been captured on
native Windows or macOS rendering — see "Known limitations" on each entry
and the manual capture checklist at the bottom of this file.

**Fictitious data note:** several screenshots reuse the placeholder
callsign `K7ARS` as demo data across multiple captures (a syntactically
valid-format but not-specifically-verified-as-unassigned US amateur
callsign pattern, not a real operator's data tied to this project). This is
flagged per-screenshot below rather than silently accepted, per this
project's screenshot-privacy review process. It is not real personal
information, but a distinct, clearly-fictitious placeholder (e.g. `TEST1`,
as `customize-menus.png` already uses) would be preferable if any of these
screenshots are recaptured.

---

### `memory-color-coding.png`

- **Feature/workflow:** Configurable memory color coding — main memory grid
  color-coded by service/type, with the color legend open.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-27, commit `3b5e16c2`
  ("Add a screenshot for Configurable memory color coding")
- **Purpose:** primary illustrative screenshot for the color-coding feature;
  also used as this README's top-of-page representative screenshot.
- **Used in:** `README.md` (Configurable memory color coding section, and
  the primary screenshot near the top of the README)
- **Fictitious sample data:** generic frequencies/labels, no real callsigns
  or personal data.
- **Known limitations:** none identified.
- **Replacement criteria:** recapture if the color-coding legend, category
  set, or default color scheme changes.

### `column-context-menu.png`

- **Feature/workflow:** Column hiding/reordering — right-click context menu
  on a memory list column header.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `b8a2bb71`
  ("Document this fork's feature additions in the README, with
  screenshots")
- **Purpose:** shows the Hide / Choose Columns / Add Custom Column context
  menu.
- **Used in:** `README.md` (Column hiding, reordering, and custom columns
  section)
- **Fictitious sample data:** contains the placeholder callsign `K7ARS` in
  background grid rows (see note above).
- **Known limitations:** placeholder callsign reuse (see note above); not
  functionally required for this screenshot's purpose (the context menu is
  what's illustrated).
- **Replacement criteria:** recapture if the context menu's items change,
  or opportunistically if this file is regenerated for another reason.

### `custom-column.png`

- **Feature/workflow:** Column hiding/reordering — a custom "Priority"
  column added and filled in, with a trimmed column set.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `b8a2bb71`
- **Purpose:** shows a populated custom column alongside a reduced column
  set.
- **Used in:** `README.md` (Column hiding, reordering, and custom columns
  section)
- **Fictitious sample data:** contains the placeholder callsign `K7ARS`
  (see note above).
- **Known limitations:** placeholder callsign reuse (see note above).
- **Replacement criteria:** recapture if custom-column behavior or the
  default column set changes.

### `columns-and-wordwrap.png`

- **Feature/workflow:** Word-wrapped Comment column.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `b8a2bb71`
- **Purpose:** shows the Comment column wrapping across multiple lines.
- **Used in:** `README.md` (Word-wrapped Comment column section)
- **Fictitious sample data:** contains the placeholder callsign `K7ARS`
  (see note above).
- **Known limitations:** placeholder callsign reuse (see note above); this
  capture's window chrome is a darker background than the other
  screenshots (a minor, cosmetic capture-environment inconsistency, not a
  UI change) — not blocking, but worth normalizing if recaptured.
- **Replacement criteria:** recapture if word-wrap behavior changes, or to
  normalize the window-chrome inconsistency noted above.

### `insert-rows-prompt.png`

- **Feature/workflow:** Insert multiple rows at once — "Insert Rows Above"
  prompt.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `898a97a1`
  ("Add screenshots for Insert Rows Above and paste-anyway prompts")
- **Purpose:** shows the row-count prompt dialog.
- **Used in:** `README.md` (Insert multiple rows at once section)
- **Fictitious sample data:** an almost-empty `Generic_CSV.csv` grid with
  faint placeholder rows (`H-TAC1`, `H-TAC2`); no real callsigns or
  personal data.
- **Known limitations:** none identified.
- **Replacement criteria:** recapture if the prompt's wording or layout
  changes.

### `find-duplicate-memories.png`

- **Feature/workflow:** Find Duplicate Memories — results dialog listing
  matched duplicate groups.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `b8a2bb71`
- **Purpose:** shows duplicate-group detection results, including which
  memory is kept by default.
- **Used in:** `README.md` (Find Duplicate Memories section)
- **Fictitious sample data:** contains the placeholder callsigns `K7ARS` /
  `K7ARS-B` (see note above), plus generic `GMRS1` / `FRS1` labels.
- **Known limitations:** placeholder callsign reuse (see note above).
- **Replacement criteria:** recapture if the duplicate-detection dialog's
  layout or default-keep logic changes.

### `paste-incompatible-prompt.png`

- **Feature/workflow:** Option to paste incompatible memories anyway —
  validation-failure prompt.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `898a97a1`
- **Purpose:** shows the "N memories failed validation ... Add them
  anyway?" prompt over a `Boblov_X3Plus.img` memory grid.
- **Used in:** `README.md` (Option to paste incompatible memories anyway
  section)
- **Fictitious sample data:** generic frequencies, no real callsigns or
  personal data.
- **Known limitations:** none identified.
- **Replacement criteria:** recapture if the prompt's wording changes.

### `repeaterbook-miles.png`

- **Feature/workflow:** RepeaterBook distance in miles — RepeaterBook query
  dialog showing the "Distance (mi)" field.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `b8a2bb71`
- **Purpose:** shows the miles-based distance field in the query dialog,
  over a memory grid with existing query results.
- **Used in:** `README.md` (RepeaterBook distance in miles section)
- **Fictitious sample data:** contains the placeholder callsigns `K7ARS` /
  `K7ARS-B` (see note above).
- **Known limitations:** placeholder callsign reuse (see note above).
- **Replacement criteria:** recapture if the query dialog's fields or
  layout change.

### `check-updates-menu.png`

- **Feature/workflow:** Manual "Check for Updates" — Help menu showing the
  item.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-26, commit `a3702c07`
  ("Replace automatic update check with Help > Check for Updates...")
- **Purpose:** shows the Help menu with "Check for Updates..." below
  "About".
- **Used in:** `README.md` (Manual "Check for Updates" instead of automatic
  section)
- **Fictitious sample data:** none — welcome screen, no memory data shown.
- **Known limitations:** none identified.
- **Replacement criteria:** recapture if the Help menu's item order or
  wording changes.

### `customize-menus.png`

- **Feature/workflow:** Customize Menus — File tab of the tabbed
  show/hide-menu-items dialog.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-27, commit `fe18ab4e`
  ("Add Help > Customize Menus... to hide/show menu items")
- **Purpose:** shows the dialog's File tab with all items checked, over a
  `menutest.csv` grid.
- **Used in:** `README.md` (Customize Menus section)
- **Fictitious sample data:** generic `TEST1`/`TEST2`/`TEST3` labels; no
  real callsigns or personal data.
- **Known limitations:** none identified.
- **Replacement criteria:** recapture if the dialog's tabs or default
  checked state change.

### `open-recent-cleanup.png`

- **Feature/workflow:** Open Recent cleanup — File > Open Recent submenu
  showing "Remove from Recent Files..." and "Clear Recent Files".
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-27, commit `e29dc932`
  ("Add README screenshots for the Linux launcher and Open Recent
  cleanup")
- **Purpose:** shows the submenu with three recent-file entries above the
  new cleanup items.
- **Used in:** `README.md` (Open Recent cleanup section)
- **Fictitious sample data:** the three "recent file" paths are generic and
  sanitized (`/tmp/home/user/radios/*.img`) — not a real home directory or
  username.
- **Known limitations:** none identified.
- **Replacement criteria:** recapture if the submenu's items or ordering
  change.

### `install-linux-launcher.png`

- **Feature/workflow:** AppImage "Install Linux Launcher..." dialog.
- **Application version:** `py3dev` (source checkout)
- **Platform:** Linux (wx/GTK3)
- **Capture date / source commit:** 2026-07-27, commit `e29dc932`
- **Purpose:** shows the detected AppImage path, its executable status, and
  the application-menu/desktop checkboxes.
- **Used in:** `README.md` (AppImage builds > Installing a launcher
  section)
- **Fictitious sample data:** a generic/sanitized AppImage file path; no
  real username or home directory.
- **Known limitations:** captured under a source-checkout-driven simulation
  of the AppImage launcher flow rather than a real packaged AppImage
  binary; behavior matches the shipped feature but the exact path string
  shown is illustrative.
- **Replacement criteria:** recapture if the dialog's layout, wording, or
  checkbox options change.

---

## Manual screenshot capture checklist (Windows, macOS)

This repository's automation environment for this documentation update is
Linux-only, with no GUI/display server and no Windows or macOS host
available — so no new Windows- or macOS-native screenshots could be
captured for this update, and none of the screenshots above claim to be.
CHIRP's UI is nearly identical across platforms (it's the same wx toolkit
and application code), so the existing Linux screenshots remain
representative of the *features*, but not of native Windows/macOS window
chrome, menu bar placement, or DMG/installer visuals. If you have access to
a Windows or macOS machine, the following would round out this
documentation:

- **Windows:** main window and memory grid, running via `run-chirp.ps1`,
  showing native Windows window chrome/title bar and menu bar.
- **macOS:** main window and memory grid, running the Community Edition
  `CHIRP.app`, showing the native macOS menu bar (top of screen, not
  in-window) and traffic-light window controls.
- **macOS:** the mounted DMG's Finder window (showing `CHIRP.app` next to
  the `Applications` shortcut), to illustrate the drag-to-install step.
- **macOS:** the Gatekeeper "can't be opened" / "Open Anyway" dialogs
  referenced in
  [macos-community-installation.md](macos-community-installation.md).

Follow the same standards as the existing set when capturing: current app
version, a clean/default window state, fictitious sample data only (no
real callsigns, frequencies, paths, or usernames), a descriptive filename
(not `screenshot1.png`/`new.png`), and an entry added to this file
documenting the same fields used above.
