from html import escape
from types import SimpleNamespace

from import_localize.ui.locale_diff import variant_documents
from import_localize.ui.change_colors import status_colors


def documents(*texts):
    variants = [SimpleNamespace(term={"Languages": [text, "Giống"]}) for text in texts]
    return variant_documents(variants, [{"Name": "English", "Code": "en"}, {"Name": "Việt", "Code": "vi"}])


def test_compare_lines_first_and_preserve_literal_text():
    old, new = documents("Hello <b>one</b> {0}\nKeep\nLast", "Hello <b>two</b> {0}\nKeep\nAdded\nLast")
    for html in (old, new):
        assert "[không có]" not in html and "[xuống dòng]" not in html
        assert "Keep" in html and escape("</b> {0}") in html
        assert "Việt (vi)</b> · Giống nhau" in html
    assert ">one</b>" in old and ">two</b>" in new and "Added" in new and "Added" not in old
    assert status_colors()["removed"][0] in old and status_colors()["added"][0] in new


def test_all_variants_compare_with_first_and_empty_has_no_placeholder_in_text():
    base, blank, extended = documents("Hi 😀", "", "Hi 😀!")
    assert "Ô trống" in blank and "−" in blank and "Hi" in blank
    assert "😀" in base and "😀" in extended and "<b>!</b>" in extended
    assert status_colors()["removed"][0] in base


def test_long_variants_fold_and_expand_the_same_lines():
    text = "\n".join(f"line {i}" for i in range(20))
    variants = [SimpleNamespace(term={"Languages": [v]}) for v in (text, text.replace("line 10", "line X"))]
    languages = [{"Name": "English", "Code": "en"}]
    for html in variant_documents(variants, languages):
        assert "dòng không đổi" in html and "line 0" not in html
    for html in variant_documents(variants, languages, True):
        assert "line 0" in html and "line 19" in html
