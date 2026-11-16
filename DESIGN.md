# Import Localize — desktop UI

The application is an operating tool for CSV localization, Unity locale assets and Google Sheets. Its primary design goal is to make the next action and its data target clear, while leaving most space to the files or records being reviewed.

## Structure

- Keep **CSV ↔ Sheet**, **CSV ↔ Unity**, and **Sheet ↔ Unity** visible as the three workflow selectors. Each workflow offers both directions within its own view. Keep its source and destination controls together with its live status and primary action. Nested reviews return to their calling workflow.
- Place the spreadsheet link, shared file picker and settings outside individual workflows. Keep settings accessible from any idle view. Reuse the ordered asset list across Unity workflows. Keep translated import CSVs separate from upload CSVs. Allow the operator to reuse the upload list explicitly as the destination for Unity export.
- Retain all existing import/export semantics, confirmation dialogs, backup paths and worker behavior.
- Show a concise summary first. Place lengthy instructions, advanced CSV settings and detailed logs behind labeled disclosure controls. Errors reveal relevant detail automatically.
- Distinguish pending Desc annotations from an applied export. Review decisions belong to the current spreadsheet session, language and key.
- Reserve the main accent for the next action. In Unity the emphasis changes from preview to apply only after a valid plan exists. Close/cancel remain neutral; stop/destructive actions are distinct.

## Visual system

- Native Windows/PySide6 controls and Segoe UI; retain the green product identity with restrained neutral light/dark surfaces.
- Global states live in `src/themes/light.qss` and `dark.qss`. Use `primaryAction`, `dangerAction`, and `muted` properties instead of new local color systems.
- Visible header separators, resize affordances and scrollbars; readable selected/disabled/focus states in both themes. Semantic table colors require readable foregrounds.
- No decorative shadows on top of bordered main panels. Use spacing and labels to separate controls.
- Preserve user-adjusted column widths, key/file selection and scroll position where possible. Do not rebuild tables just to update write status.

## Validation

Review actual rendering at 660×700 and 1100×850 for the main workspace, plus normal/narrow/expanded feature dialogs. Check both themes and empty, populated, selected, busy, completed and error states. Run the UI regressions and all service tests; bundled Windows/offscreen EXE self-tests remain required before release. Visual checks use isolated settings and synthetic write results and never mutate a live Sheet or Unity project.
