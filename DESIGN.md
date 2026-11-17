# Import Localize — desktop UI

The application is an operating tool for CSV localization, Unity locale assets and Google Sheets. Its primary design goal is to make the next action and its data target clear, while leaving most space to the files or records being reviewed.

## Structure

- Keep **CSV ↔ Sheet**, **CSV ↔ Unity**, and **Sheet ↔ Unity** visible as the three workflow selectors. Each workflow offers both directions within its own view. Keep its source and destination controls together with its live status and primary action. Nested reviews return to their calling workflow.
- Place the spreadsheet link, transfer folders and settings outside individual workflows. Give upload CSVs, export CSVs and Unity assets distinct labeled folder fields. Show each scan's file count, names and errors. Allow upload and export to share a directory.
- Pair endpoints by their role and full locale code. Show the resolved pairs before applying Unity changes. A reordered list must still write to the same locale. Keep settings accessible from every idle view.
- Retain all existing import/export semantics, confirmation dialogs, backup paths and worker behavior.
- Show a concise summary first. Place lengthy instructions, advanced CSV settings and detailed logs behind labeled disclosure controls. Errors reveal relevant detail automatically.
- Distinguish pending Desc annotations from an applied export. Review decisions belong to the current spreadsheet session, language and key.
- Reserve the main accent for the next action. In Unity the emphasis changes from preview to apply only after a valid plan exists. Close/cancel remain neutral; stop/destructive actions are distinct.

## Visual system

- Native Windows/PySide6 controls and Segoe UI; retain the green product identity with restrained neutral light/dark surfaces.
- The optional **UU DS · Cam** theme uses the UU brand and Compact desktop density. The product mark and workflow layout come from the existing desktop screens. The Qt adapter resolves semantic color roles from the UU DS native token export (`semantic.color.uu` and its primitive references) stored in `src/themes/uu/colors.json`. Its QSS template and foreground state layers live in `src/themes/uu.qss` and `ui/uu_theme.py`. Keep the three choices independent of window size and workflow state.
- Global states live in `src/themes/light.qss` and `dark.qss`. Use `primaryAction`, `dangerAction`, and `muted` properties instead of new local color systems.
- Visible header separators, resize affordances and scrollbars; readable selected/disabled/focus states in both themes. Semantic table colors require readable foregrounds.
- No decorative shadows on top of bordered main panels. Use spacing and labels to separate controls.
- Preserve user-adjusted column widths, key/file selection and scroll position where possible. Do not rebuild tables just to update write status.

## Validation

Review actual rendering at 660×700 and 1100×850 for the main workspace, plus normal/narrow/expanded feature dialogs. Check both themes and empty, populated, selected, busy, completed and error states. Run the UI regressions and all service tests; bundled Windows/offscreen EXE self-tests remain required before release. Visual checks use isolated settings and synthetic write results and never mutate a live Sheet or Unity project.
