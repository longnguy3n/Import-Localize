"""Side-by-side, line-first diff of complete locale variants against the first record."""
from difflib import SequenceMatcher
from html import escape
import re

from .change_colors import status_colors


TOKEN = re.compile(r"<[^<>\n]+>|\{[^{}\n]*\}|\w+|\s+|[^\w\s]")


def _word_ranges(left, right):
    sequences = [list(TOKEN.finditer(line)) for line in (left, right)]
    matcher = SequenceMatcher(None, *[[m.group() for m in seq] for seq in sequences], autojunk=False)
    if matcher.ratio() < 0.5:
        return [(0, len(left))], [(0, len(right))]
    ranges = ([], [])
    for op, a, b, c, d in matcher.get_opcodes():
        if op != "equal":
            for result, seq, start, end in zip(ranges, sequences, (a, c), (b, d)):
                if start < end:
                    result.append((seq[start].start(), seq[end - 1].end()))
    return ranges


def _compare(lines, other, left, right):
    for op, a, b, c, d in SequenceMatcher(None, lines, other, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        for offset in range(max(b - a, d - c)):
            i, j = a + offset, c + offset
            if i < b and j < d:
                old, new = _word_ranges(lines[i], other[j])
                left.setdefault(i, []).extend(old)
                right[j] = new
            elif i < b:
                left.setdefault(i, []).append((0, len(lines[i])))
            else:
                right[j] = [(0, len(other[j]))]


def _line_html(text, ranges, status):
    if ranges is None:
        return "  " + escape(text)
    background, foreground = status_colors()[status]
    prefix = "− " if status == "removed" else "+ "
    style = f'background-color:{background};color:{foreground}'
    parts = [f'<span style="{style}">{prefix}</span>']
    pos = 0
    for start, end in sorted(ranges):
        if end <= pos:
            continue
        parts.append(escape(text[pos:start]))
        parts.append(f'<span style="{style}"><b>{escape(text[max(pos, start):end])}</b></span>')
        pos = end
    return "".join(parts) + escape(text[pos:])


def variant_documents(variants, languages):
    documents = [[] for _ in variants]
    for column, language in enumerate(languages):
        texts = [v.term["Languages"][column] for v in variants]
        lines = [text.splitlines(keepends=True) for text in texts]
        marks = [{} for _ in texts]
        for index in range(1, len(texts)):
            _compare(lines[0], lines[index], marks[0], marks[index])
        for index, text in enumerate(texts):
            label = escape(f"{language['Name']} ({language['Code']})")
            different = len(set(texts)) > 1 if index == 0 else texts[index] != texts[0]
            state = "Có khác biệt" if different else "Giống nhau"
            status = "removed" if index == 0 else "added"
            body = "".join(_line_html(line, marks[index].get(i), status) for i, line in enumerate(lines[index]))
            documents[index].append(f"<p><b>{label}</b> · {state}</p>"
                                    + (f'<p style="white-space:pre-wrap">{body}</p>' if text else "<p><i>Ô trống</i></p>"))
    return ["<html><body>" + "".join(parts) + "</body></html>" for parts in documents]
