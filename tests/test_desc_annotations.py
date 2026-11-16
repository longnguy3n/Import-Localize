from import_localize.services.desc_annotations import DescAnnotations, WRONG_MAPPING, WRONG_LANGUAGE, locales_for_table


def test_marked_desc_is_locale_specific_additive_and_idempotent():
    rows = [["Key", "Desc", "Vietnamese"], ["k", "new", "Xin chào"], ["K", "priority", "Một"]]
    notes = DescAnnotations()
    for reason in (WRONG_MAPPING, WRONG_LANGUAGE):
        notes.set_mark("vi", "k", reason)
    assert notes.apply_rows(rows, ["en"]) is rows
    result = notes.apply_rows(rows, ["vi"])
    assert result[1] == ["k", "new\nWrong mapping\nWrong languague", "Xin chào"]
    assert result[2] == rows[2] and rows[1][1] == "new"
    assert notes.apply_rows(result, ["vi"]) is result
    saved = notes.snapshot()
    notes.clear()
    assert saved.apply_rows(rows, ["vi"]) == result


def test_missing_desc_only_inserted_when_needed_in_i2_column_order():
    rows = [["Key", "Type", "Portuguese [pt-BR]"], ["k", "Text", "Olá"], ["other", "Text", "Sim"]]
    notes = DescAnnotations()
    notes.set_mark("pt-BR", "k", WRONG_MAPPING)
    assert locales_for_table(rows[0], "upload_pt-BR") == ("pt-br",)
    assert notes.apply_rows(rows, ["pt-PT"]) is rows
    output = notes.apply_rows(rows, ["pt_br"])
    assert output == [["Key", "Type", "Desc", "Portuguese [pt-BR]"], ["k", "Text", "Wrong mapping", "Olá"], ["other", "Text", "", "Sim"]]
