from __future__ import annotations

import sys

def main() -> int:
    # Handle diagnostics before importing Qt so DLL failures become a report
    # and a nonzero exit code instead of a windowed bootloader error dialog.
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from import_localize.app.self_test import run_self_test
        return run_self_test(sys.argv[2])

    from import_localize.app.bootstrap import create_application
    from import_localize.ui.main_window import MainWindow

    app = create_application(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
