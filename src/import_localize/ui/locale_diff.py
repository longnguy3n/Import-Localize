"""Presentation-only differences; never normalize or change saved translations."""
from difflib import SequenceMatcher
from html import escape
from itertools import combinations
import re


FORMAT_TAG = re.compile(r"</?(?:color|size|b|i|u|s|font|align|mark|indent|line-height|cspace|mspace|voffset|link|style|nobr|sup|sub|uppercase|lowercase|smallcaps|pos|width|margin|br)(?=[\s=>/])[^>]*>", re.IGNORECASE)


def difference_marks(texts):
    """Union differences against every other version, including missing passages."""
    ranges = [[] for _ in texts]
    gaps = [set() for _ in texts]
    # Keep rich-text tags atomic so inserting <br> does not split a shared
    # closing tag into misleading partial differences.
    tokens = [re.findall(r"</?[A-Za-z][^>]*>|[\s\S]", text) for text in texts]
    offsets = []
    for sequence in tokens:
        positions = [0]
        for token in sequence:
            positions.append(positions[-1] + len(token))
        offsets.append(positions)
    for left, right in combinations(range(len(texts)), 2):
        if texts[left] == texts[right]:
            continue
        for kind, a, b, c, d in SequenceMatcher(None, tokens[left], tokens[right], autojunk=False).get_opcodes():
            if kind == "equal":
                continue
            for index, start, end in ((left, a, b), (right, c, d)):
                start, end = offsets[index][start], offsets[index][end]
                if start == end:
                    gaps[index].add(start)
                else:
                    ranges[index].append((start, end))
    return list(zip(ranges, gaps))


def highlighted_text(text, ranges, gaps, hide_shared_markup=False):
    hidden = {match.start(): match for match in FORMAT_TAG.finditer(text)
              if hide_shared_markup and not any(a < match.end() and b > match.start() for a, b in ranges)
              and not any(match.start() < gap < match.end() for gap in gaps)}
    boundaries = sorted({0, len(text), *gaps, *(point for span in ranges for point in span),
                         *(point for match in hidden.values() for point in (match.start(), match.end()))})
    parts = []
    for offset, start in enumerate(boundaries):
        if start in gaps:
            parts.append('<span style="background-color:#e2e7ee;color:#526172;">[không có]</span>')
        if offset + 1 == len(boundaries):
            break
        end = boundaries[offset + 1]
        if start in hidden:
            if re.match(r"<br\s*/?>", hidden[start][0], re.IGNORECASE):
                parts.append('<br/>')
            continue
        different = any(a <= start < b for a, b in ranges)
        value = escape(text[start:end])
        if different:
            value = value.replace(" ", "·").replace("\t", "[tab]").replace("\r", "[CR]").replace("\n", "[xuống dòng]<br/>")
            value = f'<span style="background-color:#ffe7a3;color:#603e00;">{value}</span>'
        else:
            value = value.replace("\n", "<br/>").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
        parts.append(value)
    if not text and not gaps:
        parts.append('<span style="color:#798591;"><i>Chưa có nội dung</i></span>')
    return "".join(parts)


def variant_documents(variants, languages, show_markup=False):
    documents = [[] for _ in variants]
    for language_index, language in enumerate(languages):
        texts = [variant.term["Languages"][language_index] for variant in variants]
        marks = difference_marks(texts)
        different = len(set(texts)) > 1
        for index, text in enumerate(texts):
            label = escape(f"{language['Name']} ({language['Code']})")
            state = "Có khác biệt" if different else "Giống nhau"
            documents[index].append(
                f'<p style="margin-top:16px;margin-bottom:8px;color:#526172;font-size:10pt;"><b>{label}</b> · {state}</p>'
                '<p style="white-space:pre-wrap;margin-top:0;margin-bottom:20px;font-size:12pt;">'
                + highlighted_text(text, *marks[index], hide_shared_markup=not show_markup) + '</p>')
    return ['<html><body style="color:#24352f;">' + "".join(parts) + '</body></html>' for parts in documents]
