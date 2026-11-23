"""Build the clickable locale variants with the first record as the reference."""
from html import escape

from .line_diff import field_diff


def variant_documents(variants, languages, full=False):
    documents = [[] for _ in variants]
    for column, language in enumerate(languages):
        texts = [v.term["Languages"][column] for v in variants]
        base = texts[0]
        label = escape(f"{language['Name']} ({language['Code']})")
        for index, text in enumerate(texts):
            different = len(set(texts)) > 1 if index == 0 else text != base
            state = "Có khác biệt" if different else "Giống nhau"
            parts = documents[index]
            parts.append(f"<p><b>{label}</b> · {state}</p>")
            if not text:
                parts.append("<p><i>Ô trống</i></p>")
            if index == 0 and different:
                # Each comparison uses the same baseline even with three or more variants.
                for n, candidate in enumerate(texts[1:], 2):
                    if candidate == base:
                        continue
                    if len(texts) > 2:
                        parts.append(f"<p>So với Bản {n}</p>")
                    parts.append(field_diff(base, candidate, full, before_only=True))
            elif full or different or len(variants) == 1:
                parts.append(field_diff(base, text, full))
    return ["".join(parts) for parts in documents]
