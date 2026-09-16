"""Tests F3 : tools/bench_translation.classify_result (spec 01 §5).

Fonction pure, sans I/O : couvre les 14 règles ordonnées et les cas de
priorité (la règle la plus sévère l'emporte quand plusieurs s'appliquent).
"""

from __future__ import annotations

from tools.bench_translation import (
    CLES_MANQUANTES,
    CONNEXION_REFUSEE,
    ERREUR_HTTP,
    EXC_CONNECTION_ERROR,
    EXC_CONNECTION_REFUSED,
    EXC_TIMEOUT,
    INJOIGNABLE,
    JSON_INVALIDE,
    JSON_NON_EXTRAIT,
    MODELE_ABSENT,
    NON_TRADUIT,
    OK,
    PAS_DE_JSON,
    TIMEOUT,
    TRONQUE,
    TYPE_INATTENDU,
    VIDE,
    classify_result,
)

BASE_KWARGS = dict(
    exc_type=None,
    http_status=None,
    finish_reason=None,
    raw=None,
    parsed=None,
    blocks=["Hello"],
    sources=["Hello"],
    allow_unchanged=[],
)


def _classify(**overrides):
    kwargs = dict(BASE_KWARGS, **overrides)
    return classify_result(**kwargs)


def test_rule1_connection_refused():
    status, _ = _classify(exc_type=EXC_CONNECTION_REFUSED)
    assert status == CONNEXION_REFUSEE


def test_rule2_other_connection_error():
    status, _ = _classify(exc_type=EXC_CONNECTION_ERROR)
    assert status == INJOIGNABLE


def test_rule3_timeout():
    status, _ = _classify(exc_type=EXC_TIMEOUT)
    assert status == TIMEOUT


def test_rule4_404_is_model_absent():
    status, detail = _classify(http_status=404, raw="not found body")
    assert status == MODELE_ABSENT
    assert detail == "not found body"


def test_rule5_other_http_error():
    status, detail = _classify(http_status=500)
    assert status == ERREUR_HTTP
    assert "500" in detail


def test_rule6_finish_reason_length():
    status, _ = _classify(finish_reason="length", parsed={"block_0": "x"})
    assert status == TRONQUE


def test_rule7_json_invalide_no_extractable_json_elsewhere():
    raw = '{"block_0": }'
    status, _ = _classify(raw=raw, parsed=None)
    assert status == JSON_INVALIDE


def test_rule7_json_non_extrait_when_valid_json_exists_elsewhere():
    raw = '{"foo": "bar"} {"baz": 1}'
    status, _ = _classify(raw=raw, parsed=None)
    assert status == JSON_NON_EXTRAIT


def test_rule8_pas_de_json_when_no_braces():
    status, _ = _classify(raw="rien ici", parsed=None)
    assert status == PAS_DE_JSON


def test_rule9_missing_keys():
    status, detail = _classify(
        blocks=["a", "b"], sources=["a", "b"], parsed={"block_0": "x"}
    )
    assert status == CLES_MANQUANTES
    assert "block_1" in detail


def test_rule9_wins_over_type_inattendu():
    # block_1 est absent (règle 9) ET block_0 a un type invalide : la règle 9
    # (évaluée avant la 10) doit l'emporter.
    status, _ = _classify(
        blocks=["a", "b"], sources=["a", "b"], parsed={"block_0": 123}
    )
    assert status == CLES_MANQUANTES


def test_rule10_type_inattendu():
    status, detail = _classify(blocks=["a"], sources=["a"], parsed={"block_0": 123})
    assert status == TYPE_INATTENDU
    assert "0" in detail


def test_rule10_wins_over_vide_and_non_traduit():
    # block_0 type invalide, block_1 vide : la règle 10 doit l'emporter sur la 11.
    status, _ = _classify(
        blocks=["a", "b"],
        sources=["a", "b"],
        parsed={"block_0": None, "block_1": ""},
    )
    assert status == TYPE_INATTENDU


def test_rule11_vide():
    status, detail = _classify(blocks=["a"], sources=["a"], parsed={"block_0": "   "})
    assert status == VIDE
    assert "0" in detail


def test_rule11_wins_over_non_traduit():
    # block_0 vide, block_1 identique à la source : la règle 11 doit
    # l'emporter sur la règle 12.
    status, _ = _classify(
        blocks=["a", "b"],
        sources=["a", "b"],
        parsed={"block_0": "", "block_1": "b"},
    )
    assert status == VIDE


def test_rule12_non_traduit_normalizes_case_and_whitespace():
    status, detail = _classify(
        blocks=["Hello   World"],
        sources=["hello world"],
        parsed={"block_0": "Hello   World"},
    )
    assert status == NON_TRADUIT
    assert "0" in detail


def test_rule12_allow_unchanged_true_bypasses_all_blocks():
    status, _ = _classify(
        blocks=["KRAKOOM!"],
        sources=["KRAKOOM!"],
        parsed={"block_0": "KRAKOOM!"},
        allow_unchanged=True,
    )
    assert status == OK


def test_rule12_allow_unchanged_list_bypasses_only_listed_indices():
    status, _ = _classify(
        blocks=["a", "b"],
        sources=["a", "b"],
        parsed={"block_0": "a", "block_1": "traduit"},
        allow_unchanged=[0],
    )
    assert status == OK


def test_rule12_allow_unchanged_list_does_not_cover_other_index():
    status, _ = _classify(
        blocks=["a", "b"],
        sources=["a", "b"],
        parsed={"block_0": "a", "block_1": "b"},
        allow_unchanged=[1],
    )
    assert status == NON_TRADUIT


def test_rule13_ok_with_extra_keys_noted():
    status, detail = _classify(
        blocks=["a"], sources=["a"], parsed={"block_0": "traduit", "block_x": "surplus"}
    )
    assert status == OK
    assert "block_x" in detail


def test_rule14_plain_ok():
    status, detail = _classify(
        blocks=["a"], sources=["a"], parsed={"block_0": "traduit"}
    )
    assert status == OK
    assert detail == "OK"
