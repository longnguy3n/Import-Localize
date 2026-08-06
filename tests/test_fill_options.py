from import_localize.services.fill_service import (
    build_fill_copy_requests,
    column_letters_to_number,
    column_number_to_letters,
    normalize_column_selection,
    parse_column_selection,
)


def test_column_round_trip():
    for number, letters in ((1, "A"), (26, "Z"), (27, "AA"), (703, "AAA")):
        assert column_number_to_letters(number) == letters
        assert column_letters_to_number(letters) == number


def test_parse_column_selection_supports_ranges_and_groups():
    assert parse_column_selection("D:I") == (4, 5, 6, 7, 8, 9)
    assert parse_column_selection("D,F,H:J") == (4, 6, 8, 9, 10)
    assert parse_column_selection("I:D") == (4, 5, 6, 7, 8, 9)
    assert normalize_column_selection("D,E,F,H:J") == "D:F,H:J"


def test_copy_requests_group_consecutive_columns():
    requests = build_fill_copy_requests(
        sheet_id=123,
        source_row=2,
        last_row=100,
        selected_columns=(4, 5, 6, 8, 9),
    )
    assert len(requests) == 2
    first = requests[0]["copyPaste"]
    second = requests[1]["copyPaste"]
    assert first["source"]["startRowIndex"] == 1
    assert first["source"]["startColumnIndex"] == 3
    assert first["source"]["endColumnIndex"] == 6
    assert first["destination"]["startRowIndex"] == 2
    assert first["destination"]["endRowIndex"] == 100
    assert second["source"]["startColumnIndex"] == 7
    assert second["source"]["endColumnIndex"] == 9
