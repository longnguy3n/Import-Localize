"""Find duplicate keys per asset and remove only the discarded YAML records."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .unity_locale_service import FileChange, LocaleAsset, LocalePlan, UnityLocaleError, read_asset


@dataclass
class DuplicateVariant:
    term: dict
    indices: list[int]


@dataclass
class DuplicateGroup:
    path: Path
    key: str
    variants: list[DuplicateVariant]

    @property
    def count(self):
        return sum(len(variant.indices) for variant in self.variants)

    @property
    def conflict(self):
        return len(self.variants) > 1


@dataclass
class DuplicateScan:
    assets: list[LocaleAsset]
    groups: list[DuplicateGroup]
    # Character spans in decoded original text, including each sequence dash.
    term_spans: dict[Path, list[tuple[int, int]]]


def scan_duplicates(paths: list[Path]) -> DuplicateScan:
    paths = list(dict.fromkeys(Path(path).resolve() for path in paths))
    if not paths:
        raise UnityLocaleError("Chọn ít nhất một file locale*.asset để kiểm tra.")
    assets, groups, spans = [], [], {}
    for path in paths:
        asset = read_asset(path)
        start, end = asset.spans["mTerms"]
        section = asset.text[start:end]
        loader = getattr(yaml, "CBaseLoader", yaml.BaseLoader)
        # Reparse raw data: read_asset applies a legacy Touch fallback for CSV.
        # Compare the original Languages values without that conversion.
        terms = yaml.load(section, Loader=loader)["mTerms"]
        node = yaml.compose(section, Loader=loader).value[0][1]
        offsets = [0]
        for line in section.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        starts = []
        for item in node.value:
            position = offsets[item.start_mark.line]
            if not re.match(r" *-\s", section[position:]):
                raise UnityLocaleError(f"{path.name}: chỉ hỗ trợ mTerms dạng danh sách YAML theo dòng.")
            starts.append(start + position)
        if len(set(starts)) != len(terms):
            raise UnityLocaleError(f"{path.name}: không xác định được ranh giới từng term.")
        spans[path] = list(zip(starts, starts[1:] + [end]))
        by_key = {}
        for index, term in enumerate(terms):
            # Flags (including New), type, description and other metadata do not
            # make a different translation. Preserve the first full raw record.
            signature = tuple(term["Languages"])
            variants = by_key.setdefault(term["Term"], {})
            variant = variants.setdefault(signature, DuplicateVariant(term, []))
            variant.indices.append(index)
        groups.extend(DuplicateGroup(path, key, list(variants.values()))
                      for key, variants in by_key.items()
                      if sum(len(v.indices) for v in variants.values()) > 1)
        assets.append(asset)
    return DuplicateScan(assets, groups, spans)


def prepare_duplicate_cleanup(scan: DuplicateScan, choices: dict[tuple[Path, str], int]) -> LocalePlan:
    """Require an explicit variant choice for every conflict before any write."""
    discard = {}
    for group in scan.groups:
        choice = choices.get((group.path, group.key)) if group.conflict else 0
        if type(choice) is not int or not 0 <= choice < len(group.variants):
            raise UnityLocaleError(f"{group.path.name} · {group.key}: cần chọn bản muốn giữ lại.")
        keep = group.variants[choice].indices[0]
        discard.setdefault(group.path, set()).update(
            index for variant in group.variants for index in variant.indices if index != keep)
    changes = []
    for asset in scan.assets:
        removed = discard.get(asset.path, set())
        if not removed:
            continue
        after = asset.text
        for index in sorted(removed, reverse=True):
            start, end = scan.term_spans[asset.path][index]
            after = after[:start] + after[end:]
        raw = after.encode("utf-8")
        if asset.original.startswith(b"\xef\xbb\xbf"):
            raw = b"\xef\xbb\xbf" + raw
        changes.append(FileChange(asset.path, asset.original, raw,
                                  f"Xóa {len(removed)} bản ghi trùng; giữ {len(asset.terms) - len(removed)} term."))
    if not changes:
        raise UnityLocaleError("Không có key trùng cần xóa.")
    return LocalePlan(changes, {asset.path: asset.original for asset in scan.assets})
