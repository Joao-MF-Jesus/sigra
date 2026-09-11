from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_platform.catalog.contracts import Dossier, FieldEvidence, IdentityReview, EvidenceReference
from data_platform.catalog.intake import REQUIRED_FIELDS, SOURCE_HASH, assess, fipe_target, intake_report, load_selection
from data_platform.contracts.pbev import AUDITED_ASSET_BY_YEAR


ROOT = Path(__file__).resolve().parents[2]


def test_selection_preserves_canonical_ids_groups_and_separate_candidate_status():
    selection = load_selection()
    assert selection.source.sha256 == SOURCE_HASH
    assert len(selection.baseline) == 34
    assert len(selection.candidates) == 66
    assert [r.id for r in (*selection.baseline, *selection.candidates)] == list(range(1, 101))
    assert len({r.candidate_key for r in selection.candidates}) == 66
    assert Counter(r.collection_group for r in selection.candidates) == {group: 11 for group in ("Cidade", "Aplicativo", "Trabalho", "Família", "Estrada", "SUV/Espaço")}
    assert {r.status for r in selection.candidates} == {"selected"}
    assert Counter(r.batch for r in selection.candidates) == {1: 22, 2: 22, 3: 22}


def test_existing_34_match_workbook_without_changing_any_field():
    from app.sample_data import VEHICLES
    before = [asdict(v) for v in VEHICLES]
    selection = load_selection()
    assert [(v.id, v.brand, v.model, v.year) for v in VEHICLES] == [(v.id, v.brand, v.model, v.year) for v in selection.baseline]
    intake_report(selection)
    assert before == [asdict(v) for v in VEHICLES]


@pytest.mark.parametrize("batch", [1, 2, 3])
def test_incomplete_batch_never_emits_ingestion_targets_or_activates(batch):
    selection = load_selection()
    result = intake_report(selection, batch=batch)
    assert (result["selected"], result["blocked"], result["activated"]) == (22, 22, 0)
    assert result["database_accessed"] is False
    for row in result["rows"]:
        assert row["canonical_key"] is None
        assert row["fipe_code"] is None
        assert row["pbev_row_hash"] is None
        assert row["active"] is False
        assert set(row["unavailable_fields"]) == set(REQUIRED_FIELDS)
    candidate = next(r for r in selection.candidates if r.batch == batch)
    with pytest.raises(ValueError, match="blocked"):
        fipe_target(candidate, Dossier(candidate_id=candidate.id))


def test_intake_is_deterministic_idempotent_and_has_no_connection_side_effects(monkeypatch):
    import socket
    import sqlalchemy
    def forbidden(*_args, **_kwargs):
        pytest.fail("candidate intake must not access a network or database")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    selection = load_selection()
    assert intake_report(selection) == intake_report(selection)


def _reference(year=2021):
    asset = AUDITED_ASSET_BY_YEAR[year]
    return EvidenceReference(source_url=asset.download_url, sha256=asset.sha256, locator="TEST-ONLY synthetic row", collected_at="2026-09-06T00:00:00Z")


def _complete_test_dossier():
    """Synthetic contract fixture, never a researched vehicle or persisted seed."""
    candidate = load_selection().candidates[0]
    ref = _reference()
    identity = IdentityReview(
        method="explicit_review", method_version="test-only-v1", reviewed_by="test-only",
        reviewed_at="2026-09-06T00:00:00Z", candidate_key=candidate.candidate_key,
        target_version=candidate.target_version, fipe_code="999999-9", year_code="2021-5",
        fipe_description="TEST ONLY", fipe_brand="TEST ONLY", fipe_price_brl="50000.00",
        fipe_reference_month="2026-09-01", fipe_source=EvidenceReference(
            source_url="https://parallelum.com.br/fipe/api/v1/carros/marcas", sha256="a"*64,
            locator="TEST ONLY", collected_at="2026-09-06T00:00:00Z"),
        pbev_cycle=2021, pbev_row_hash="b"*64, pbev_source=ref,
        motor="TEST ONLY 1.0", transmission="manual", fuel="flex",
        configuration_evidence={field:"TEST ONLY explicit source comparison" for field in ("brand","model","version","model_year","motor","transmission","fuel")},
    )
    fields = {name: FieldEvidence(value="2" if unit == "level/5" else "10", unit=unit, kind="observed", references=(ref,)) for name,unit in REQUIRED_FIELDS.items()}
    return Dossier(candidate_id=candidate.id, identity=identity, fields=fields)


def test_complete_dossier_is_not_misrepresented_as_activated_or_source_validated():
    selection = load_selection()
    dossier = _complete_test_dossier()
    assert assess(selection.candidates[0], dossier) == ()
    target = fipe_target(selection.candidates[0], dossier)
    assert (target.vehicle_type, target.fipe_code, target.year_code) == ("car", "999999-9", "2021-5")
    report = intake_report(selection, (dossier,))
    assert report["activated"] == 0
    assert report["rows"][0]["status"] == "dossier_complete_pending_source_and_integration_validation"


@pytest.mark.parametrize("changed,code", [
    ({"year_code":"2020-5"},"MODEL_YEAR_MISMATCH"),
    ({"target_version":"Version chosen by resemblance"},"TARGET_VERSION_REVIEW_REQUIRED"),
    ({"pbev_cycle":2020},"PBEV_YEAR_REVIEW_REQUIRED"),
    ({"configuration_evidence":{}},"CONFIGURATION_EVIDENCE_MISSING"),
    ({"fuel":"diesel"},"FUEL_ADAPTER_NOT_VALIDATED"),
    ({"fuel":"hybrid"},"FUEL_ADAPTER_NOT_VALIDATED"),
])
def test_identity_or_fuel_divergence_cannot_be_silently_resolved(changed, code):
    dossier = _complete_test_dossier()
    dossier = dossier.model_copy(update={"identity":dossier.identity.model_copy(update=changed)})
    assert code in {r.code for r in assess(load_selection().candidates[0], dossier)}


def test_duplicate_reviews_and_fuzzy_methods_are_rejected():
    dossier = _complete_test_dossier()
    with pytest.raises(ValueError, match="ambiguous"):
        intake_report(load_selection(), (dossier, dossier))
    data = dossier.identity.model_dump()
    data["method"] = "fuzzy"
    with pytest.raises(ValidationError):
        IdentityReview.model_validate(data)


@pytest.mark.parametrize("field,value,unit,code", [
    ("annual_maintenance_cost","3200","BRL/month","UNIT_MISMATCH"),
    ("annual_maintenance_cost","-1","BRL/year","VALUE_OUT_OF_RANGE"),
    ("comfort_score","101","score/100","VALUE_OUT_OF_RANGE"),
    ("segment_level","1.5","level/5","VALUE_OUT_OF_RANGE"),
    ("consumption_city","0","km/l","VALUE_OUT_OF_RANGE"),
])
def test_unit_and_numeric_contracts(field,value,unit,code):
    dossier = _complete_test_dossier()
    fields = dict(dossier.fields)
    fields[field] = FieldEvidence(value=value,unit=unit,kind="observed",references=(_reference(),))
    assert code in {r.code for r in assess(load_selection().candidates[0],dossier.model_copy(update={"fields":fields}))}


def test_absence_is_not_zero_and_demonstrative_numbers_do_not_enable_activation():
    missing = FieldEvidence(kind="unavailable",unit="BRL/year")
    assert missing.value is None
    with pytest.raises(ValidationError):
        FieldEvidence(kind="unavailable",value="0",unit="BRL/year")
    with pytest.raises(ValidationError):
        FieldEvidence(kind="derived",value="1",unit="score/100",references=(_reference(),))
    dossier = _complete_test_dossier()
    fields = dict(dossier.fields)
    fields["comfort_score"] = fields["comfort_score"].model_copy(update={"kind":"demonstrative"})
    assert "DEMONSTRATIVE_NOT_ACTIVATABLE" in {r.code for r in assess(load_selection().candidates[0],dossier.model_copy(update={"fields":fields}))}


def test_collection_group_does_not_enter_evidence_gate_or_existing_scores():
    selection = load_selection()
    candidate = selection.candidates[0]
    swapped = candidate.model_copy(update={"collection_group":"Estrada","collection_order":11})
    assert assess(candidate) == assess(swapped)
    for filename in ("recommender.py","tco.py","multifactor_recommendation.py"):
        source = (ROOT / "backend/app" / filename).read_text(encoding="utf-8")
        assert "collection_group" not in source
        assert "collection_order" not in source


def test_all_six_legacy_rankings_remain_deterministic_and_maintenance_divides_once():
    from app.sample_data import VEHICLES
    from app.recommender import RecommendationProfile, recommend
    from app.tco import calculate_tco
    for use_case in ("cidade","app","trabalho","familia","estrada","suv"):
        profile = RecommendationProfile(budget=100000,monthly_limit=1750,use_case=use_case)
        before = recommend(VEHICLES,profile)
        intake_report(load_selection())
        assert recommend(VEHICLES,profile) == before
        assert len(before) == 34
    tco = calculate_tco(60000,12,1000,6,3200,10)
    assert tco["monthly_maintenance_cost"] == round(3200/12,2)


@pytest.mark.parametrize("url", ["https://" + "test-user:test-only@" + "example.org/source", "https://example.org/source?token=test-only", "http://example.org/source"])
def test_operational_authenticated_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        EvidenceReference(source_url=url,sha256="a"*64,locator="test",collected_at="2026-09-06T00:00:00Z")


def test_cli_report_is_external_and_never_overwrites(tmp_path):
    from data_platform.catalog.cli import main
    target = tmp_path / "intake.json"
    assert main(["--report", str(target), "--batch", "1"]) == 2
    assert json.loads(target.read_text(encoding="utf-8"))["activated"] == 0
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        main(["--report", str(target)])
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


def test_two_candidate_ids_cannot_share_one_canonical_identity():
    dossier = _complete_test_dossier()
    other = dossier.model_copy(update={"candidate_id":36})
    with pytest.raises(ValueError, match="duplicate canonical"):
        intake_report(load_selection(), (dossier, other))


def test_cli_does_not_echo_rejected_secret_input(tmp_path, capsys):
    from data_platform.catalog.cli import main
    payload = _complete_test_dossier().model_dump(mode="json")
    sentinel = "synthetic-confidential-input"
    payload["identity"]["fipe_source"]["source_url"] = "https://test:" + sentinel + "@example.org/"
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps([payload]), encoding="utf-8")
    report = tmp_path / "report.json"
    assert main(["--dossiers", str(input_file), "--report", str(report)]) == 2
    output = capsys.readouterr()
    assert sentinel not in output.out + output.err
    assert "invalid_input" in output.out
    assert not report.exists()
