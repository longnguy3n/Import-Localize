from pathlib import Path
from concurrent.futures import CancelledError

from .feature_workspace import open_child_feature
from import_localize.services.unity_locale_service import export_csv, read_asset


def asset_audit_sources(paths, progress=None, cancelled=None):
    """Give audit dialogs the exact unmarked Unity export, held in memory."""
    sources = {}
    for index, path in enumerate(paths):
        if cancelled and cancelled():
            raise CancelledError("Đã dừng đọc asset.")
        asset = read_asset(path)
        code = asset.languages[0]["Code"] if len(asset.languages) == 1 else path.stem
        name = Path(f"upload_{code}.csv")
        if name in sources:
            raise ValueError(f"Nhiều asset cùng tạo {name}. Hãy chọn một asset cho mỗi mã ngôn ngữ.")
        sources[name] = export_csv(asset)
        if progress:
            progress((index + 1) * 100 // len(paths), f"Đã đọc {path.name}")
    return sources


def review_sources(kind, parent, settings, sources, annotations):
    if kind == "mapping":
        from .mapping_dialog import MappingDialog
        dialog = MappingDialog(settings, parent=parent, sources=sources, annotations=annotations)
    else:
        from .csv_language_dialog import CsvLanguageDialog
        dialog = CsvLanguageDialog(parent=parent, sources=sources, annotations=annotations)
    open_child_feature(parent, dialog)
