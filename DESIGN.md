# Import Localize — desktop UI

The application is an operating tool for CSV localization, Unity locale assets and Google Sheets. Its primary design goal is to make the next action and its data target clear, while leaving most space to the files or records being reviewed.

## Structure

- Keep Unity tools, mapping audit and CSV analysis together in a toolbar. Keep CSV-to-Sheets operations together with their visible Sheet target.
- Retain all existing import/export semantics, confirmation dialogs, backup paths and worker behavior.
- Show a concise summary first. Place lengthy instructions, advanced CSV settings and detailed logs behind labeled disclosure controls. Errors reveal relevant detail automatically.
- Use separate labels for audit findings and confirmed Sheet-write state. Cached history is explicitly the last observation, never a substitute for a fresh read before writing.
- Reserve the main accent for the next action. In Unity the emphasis changes from preview to apply only after a valid plan exists. Close/cancel remain neutral; stop/destructive actions are distinct.

## Visual system

- Native Windows/PySide6 controls and Segoe UI; retain the green product identity with restrained neutral light/dark surfaces.
- Global states live in `src/themes/light.qss` and `dark.qss`. Use `primaryAction`, `dangerAction`, and `muted` properties instead of new local color systems.
- Visible header separators, resize affordances and scrollbars; readable selected/disabled/focus states in both themes. Semantic table colors require readable foregrounds.
- No decorative shadows on top of bordered main panels. Use spacing and labels to separate controls.
- Preserve user-adjusted column widths, key/file selection and scroll position where possible. Do not rebuild tables just to update write status.

## Validation

Review actual rendering at 660×700 and 1100×850 for the main workspace, plus normal/narrow/expanded feature dialogs. Check both themes and empty, populated, selected, busy, completed and error states. Run the UI regressions and all service tests; bundled Windows/offscreen EXE self-tests remain required before release. Visual checks use isolated settings and synthetic write results and never mutate a live Sheet or Unity project.
