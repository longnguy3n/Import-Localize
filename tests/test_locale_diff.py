from types import SimpleNamespace

from import_localize.ui.locale_diff import difference_marks, highlighted_text, variant_documents


def test_insert_delete_replace_and_unicode():
    marks = difference_marks(["Ability", "Ability:"])
    assert marks == [([], {7}), ([(7, 8)], set())]
    assert "không có" in highlighted_text("Ability", *marks[0])
    assert '<span style="background-color:#ffe7a3;color:#603e00;">:</span>' in highlighted_text("Ability:", *marks[1])
    assert difference_marks(["xin chào 😀", "xin chào 🌟"]) == [([(9, 10)], set()), ([(9, 10)], set())]


def test_identical_and_three_variants_are_compared_against_each_other():
    assert difference_marks(["same", "same"]) == [([], set()), ([], set())]
    marks = difference_marks(["abc", "axc", "abz"])
    # The third variant differs in b as well as z when compared with variant 2.
    assert (1, 2) in marks[0][0] and (2, 3) in marks[0][0]
    assert any(start <= 1 and end >= 3 for start, end in marks[2][0])


def test_whitespace_and_missing_or_empty_content_are_visible():
    marks = difference_marks(["hello", "hello \n"])
    html = highlighted_text("hello \n", *marks[1])
    assert "·[xuống dòng]<br/>" in html
    assert "Chưa có nội dung" in highlighted_text("", [], set())
    marks = difference_marks(["", "new"])
    assert "không có" in highlighted_text("", *marks[0])
    assert "#ffe7a3" in highlighted_text("new", *marks[1])


def test_language_sections_escape_tags_and_label_unchanged_languages():
    variants = [SimpleNamespace(term={"Languages": [value, "xin chào"]})
                for value in ('Text <br> {0}', 'Text {0}')]
    docs = variant_documents(variants, [{"Name": "English", "Code": "en"}, {"Name": "Tiếng Việt", "Code": "vi"}])
    assert "English (en)" in docs[0] and "Tiếng Việt (vi)" in docs[0]
    assert "Có khác biệt" in docs[0] and "Giống nhau" in docs[0]
    assert "&lt;br&gt;" in docs[0] and "<br>" not in docs[0]
    assert "không có" in docs[1]


def test_shared_formatting_hidden_but_different_formatting_remains_visible():
    variants = [SimpleNamespace(term={"Languages": [value]}) for value in (
        '<color=red><b>Hello</b></color>', '<color=red><b>Hello!</b></color>')]
    languages = [{"Name": "English", "Code": "en"}]
    compact = variant_documents(variants, languages)
    full = variant_documents(variants, languages, show_markup=True)
    assert "&lt;color" not in compact[0] and "Hello" in compact[0]
    assert "&lt;color=red&gt;" in full[0]
    variants[1].term["Languages"][0] = '<color=blue><b>Hello</b></color>'
    docs = variant_documents(variants, languages)
    assert "&lt;color=" in docs[0] and "#ffe7a3" in docs[0]
    assert "&lt;b&gt;" not in docs[0]


def test_inserted_break_does_not_split_shared_closing_tag():
    variants = [SimpleNamespace(term={"Languages": [value]}) for value in (
        '<color=red>Hello</color>', '<color=red>Hello<br></color>')]
    docs = variant_documents(variants, [{"Name": "English", "Code": "en"}])
    assert "&lt;/color&gt;" not in docs[0]
    assert "&lt;/color&gt;" not in docs[1]
    assert "&lt;br&gt;" in docs[1] and "không có" in docs[0]
