from __future__ import annotations

import copy
import csv
import json
from concurrent.futures import CancelledError
from pathlib import Path

import pytest

from import_localize.services.mapping_audit_service import (
    MappingIndex, audit_mapping, load_mapping,
)


@pytest.fixture
def data():
    return json.loads((Path(__file__).parent / "fixtures/mapping_v2.json").read_text(encoding="utf-8"))


def entry(id="other", en="Basic ATK", vi="ĐĐT", pt="ATQ Básico", **changes):
    item = {"id": f"dg.{id}.1234567890", "groups": ["combat"],
            "translations": {"en": en, "vi": vi, "pt-BR": pt},
            "aliases": {"en": [], "vi": [], "pt-BR": []}, "keys": [],
            "context_required": False, "variants": [], "rejected": []}
    item.update(changes)
    return item


def run(tmp_path, data, rows, name="DG - Translate_Data.csv"):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        csv.writer(stream).writerows(rows)
    return audit_mapping(mapping, [path])


def test_exact_labels_check_every_language_and_preserve_csv(tmp_path, data):
    report = run(tmp_path, data, [["Tag", "Key", "Custom(modified)", "English", "Vietnamese", "Portuguese (Brazil)"],
                                  ["combat", "cf_damage_title", "new", "Damage", "Sát thương", "DNO"]])
    assert {(i.locale, i.status, i.expected) for i in report.issues} == {("en", "wrong", "DMG"), ("vi", "wrong", "ST")}
    assert report.wrong_keys == {"cf_damage_title"}
    assert report.checked_cells == 3
    assert report.affected_files == report.files
    assert "Sát thương" in report.files[0].read_text(encoding="utf-8-sig")


def test_longest_first_protected_ranges_boundaries_and_aliases(data):
    data["entries"] += [entry(), entry("atk", "ATK", "CÔNG", "ATQ")]
    index = MappingIndex(data)
    text = '<color=DMG>Basic ATK</color> {DMG} cf_damage_title ATKspeed Damage'
    terms = index.find_terms(text, "en")
    assert [term for term, ids in terms] == ["basic atk", "damage"]
    assert index.find_terms("Basic <b>ATK</b>", "en")[0][0] == "atk"
    assert not index.find_terms("Dang", "vi")


def test_alias_does_not_authorize_target_variant(tmp_path, data):
    data["entries"][0]["aliases"]["vi"] = ["Thiệt Hại"]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"], ["cf_damage_title", "DMG", "Thiệt Hại"]])
    assert report.issues[0].status == "wrong"


def test_ambiguous_candidates_require_key_context(tmp_path, data):
    data["entries"] = [entry("frost1", "Frostbite", "Phỏng Lạnh", "Geladura", keys=["cf_skill_frostbite_title"], context_required=True),
                       entry("frost2", "Frostbite", "Nanh Giá Lạnh", "Congelamento", keys=["cf_pet_p10_skill_title"], context_required=True)]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"],
        ["unknown", "Frostbite", "Wrong"], ["cf_skill_frostbite_title", "Frostbite", "Wrong"]])
    assert all(i.status == "review" for i in report.issues if i.key == "unknown")
    assert report.wrong_keys == {"cf_skill_frostbite_title"}


def test_derived_title_and_description_are_different(tmp_path, data):
    data["entries"][0]["keys"] = ["cf_skill_test_title", "cf_skill_test_desc"]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"],
        ["cf_skill_test_plus_title", "DMG +", "ST"],
        ["cf_skill_test_plus_desc", "Deal DMG to enemies", "Gây ST lên kẻ địch"]])
    assert report.wrong_keys == {"cf_skill_test_plus_title"}
    assert {i.expected for i in report.issues} == {"ST +"}


def test_override_does_not_replace_entire_description(tmp_path, data):
    silver = entry("silver-key", "Silver Key", "Chìa Khóa Bạc", "Chave de Prata", keys=["cf_gold_key_title"])
    data["entries"].append(silver)
    data["key_overrides"] = [{"id": "gold", "operator": "contains", "value": "gold_key", "entry_id": silver["id"], "preserve_key": True}]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"],
        ["cf_gold_key_title", "Gold Key", "Chìa Khóa Vàng"],
        ["cf_gold_key_desc", "Gain Silver Key and DMG", "Nhận Chìa Khóa Bạc và ST"]])
    assert report.wrong_keys == {"cf_gold_key_title"}
    assert not any(i.key.endswith("desc") for i in report.issues)


def test_title_key_can_be_context_hint_without_full_cell_replacement(tmp_path, data):
    data["entries"] = [entry("equipment", "Equipment", "Trang Bị", "Equipamento", keys=["equipment_design_title"])]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"],
        ["equipment_design_title", "Equipment Design", "Bản Thiết Kế Trang Bị"]])
    assert not report.issues


def test_derived_title_with_additional_words_is_not_replaced_whole(tmp_path, data):
    data["entries"][0]["keys"] = ["cf_skill_test_title"]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"],
        ["cf_skill_test_plus_title", "DMG Fragment +", "Mảnh ST +"]])
    assert not report.issues


def test_context_key_with_no_source_does_not_infer_whole_label(tmp_path, data):
    report = run(tmp_path, data, [["Key", "Vietnamese"], ["cf_damage_title", "Unknown name"]], name="DG - export_vi.csv")
    assert not report.wrong_keys
    assert report.issues[0].status == "review"


def test_prose_grammar_is_review_and_rejected_forms_are_scoped(tmp_path, data):
    data["entries"][0]["rejected"] = [{"locale": "vi", "forms": ["Lỗi"], "condition": ""},
        {"locale": "pt-BR", "forms": ["Errado"], "condition": "only a specific meaning"}]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese", "Portuguese (Brazil)"],
        ["a", "Deal DMG", "Gây Lỗi", "Errado"], ["b", "Deal DMG", "Gây sát thương", "Causar dano"]])
    assert report.wrong_keys == {"a"}
    assert all(i.status == "review" for i in report.issues if i.key == "b" or i.locale == "pt-BR")


def test_variants_are_review_not_automatic_wrong(tmp_path, data):
    data["entries"][0]["variants"] = [{"locale": "vi", "text": "Sát Thương", "condition": "only prose"}]
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"], ["cf_damage_title", "DMG", "Sát Thương"]])
    assert not report.wrong_keys and report.issues[0].status == "review"


def test_monolingual_pairs_match_family_and_exact_key(tmp_path, data):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(data), encoding="utf-8")
    paths = []
    for name, body in {"DG - export_en.csv": "Key,English\na,DMG\n", "DG - export_vi.csv": "Key,Vietnamese\na,wrong\n",
                       "DG - upload_vi.csv": "Key,Vietnamese\na,wrong\n"}.items():
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    report = audit_mapping(mapping, paths)
    assert any(i.path.name == "DG - export_vi.csv" and i.status == "wrong" for i in report.issues)
    assert all(i.status == "review" for i in report.issues if i.path.name == "DG - upload_vi.csv")
    assert report.wrong_keys == {"a"}


def test_duplicate_sources_are_not_arbitrarily_selected(tmp_path, data):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(data), encoding="utf-8")
    english, target = tmp_path / "DG - export_en.csv", tmp_path / "DG - export_vi.csv"
    english.write_text("Key,English\na,DMG\na,Unrelated text\n", encoding="utf-8")
    target.write_text("Key,Vietnamese\na,wrong\n", encoding="utf-8")
    report = audit_mapping(mapping, [english, target])
    assert not report.wrong_keys
    assert any("nhiều bản nguồn" in i.reason and i.status == "review" for i in report.issues)


def test_multiline_line_numbers_bad_csv_and_cancel(tmp_path, data):
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"], ["x", "Unknown\ntext", "text"], ["cf_damage_title", "DMG", "wrong"]])
    assert report.issues[0].line == 4
    path = tmp_path / "bad.csv"
    path.write_text('Key,English\na,DMG,extra\n', encoding="utf-8")
    report = audit_mapping(tmp_path / "mapping.json", [path, report.files[0]])
    assert str(path) in report.errors and report.wrong_keys == {"cf_damage_title"}
    with pytest.raises(CancelledError):
        audit_mapping(tmp_path / "mapping.json", [path], cancel_callback=lambda: True)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(schema_version="1.0.0"),
    lambda d: d["matching"].update(case_sensitive=True),
    lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])),
    lambda d: d["entries"][0]["translations"].pop("vi"),
    lambda d: d["abbreviations"].append({"entry_id": "dg.missing.1234567890", "expansions": {"vi": "x", "pt-BR": "y"}}),
])
def test_reject_invalid_contract(tmp_path, data, mutation):
    mutation(data)
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_mapping(path)


def test_case_equivalent_source_aliases_are_allowed(tmp_path, data):
    data["entries"][0]["aliases"]["en"].append("dmg")
    report = run(tmp_path, data, [["Key", "English", "Vietnamese"], ["cf_damage_title", "DMG", "ST"]])
    assert not report.issues
