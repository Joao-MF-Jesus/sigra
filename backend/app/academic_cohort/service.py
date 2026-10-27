"""Uses frozen canonical evaluations and the existing v4 group ranking function."""
from copy import deepcopy
from decimal import Decimal

from app.academic_cohort.contracts import LIMITATIONS, PROFILE_COUNTS, json_document, method_manifest
from app.academic_cohort.repository import AcademicFilters, AcademicRepository
from data_platform.catalog.profile_pilot_v4 import fingerprint, rankings


class AcademicUnavailable(ValueError):
    pass


class AcademicNotFound(ValueError):
    pass


class AcademicService:
    # Defaults remain the approved V6. An explicit, guarded subclass may supply
    # its own coverage; never replace the approved contract's trust anchor.
    profile_counts = PROFILE_COUNTS
    limitations = LIMITATIONS
    recommendation_context = {}

    def __init__(self, repository: AcademicRepository):
        self.repository = repository

    def _snapshot(self, snapshot_id=None):
        row = self.repository.snapshot(snapshot_id)
        if row is None:
            if snapshot_id is not None:
                raise AcademicNotFound("Snapshot acadêmico não encontrado")
            raise AcademicUnavailable("Coorte acadêmica ainda não materializada")
        manifest = method_manifest()
        if (row.selected_count != 60 or row.operationally_active or row.recommended
                or row.profile_counts != self.profile_counts
                or row.source_manifest != manifest
                or row.method_fingerprint != fingerprint(manifest)
                or row.inventory_summary.get("inventory_count") != 81
                or len(set(row.inventory_summary.get("selected_ids", []))) != 60
                or len(row.inventory_summary.get("holdout_ids", [])) != 17
                or len(row.inventory_summary.get("outside_selection", [])) != 21):
            raise AcademicUnavailable("Snapshot incompatível com a metodologia local")
        return row

    @staticmethod
    def _item(row):
        if (row.operationally_active or row.recommended
                or fingerprint(row.payload) != row.payload_fingerprint
                or row.catalog_id != row.payload["id"]
                or row.fipe_code != row.payload["fields"]["fipe_code"]["value"]
                or row.year_code != row.payload["fields"]["year_code"]["value"]
                or row.label != row.payload["label"]
                or row.reference_month != row.payload["fields"]["reference_month"]["value"]
                or row.purchase_price_brl != Decimal(row.payload["fields"]["price_brl"]["value"])):
            raise AcademicUnavailable("Evidência persistida inconsistente")
        return {"catalog_id": row.catalog_id, "label": row.label, "fipe_code": row.fipe_code,
                "year_code": row.year_code, "purchase_price_brl": row.purchase_price_brl,
                "price_reference_month": row.reference_month}

    @staticmethod
    def _evaluation(row):
        payload = row.payload
        if (row.operationally_active or row.recommended
                or payload.get("operationally_active") is not False or payload.get("recommended") is not False
                or fingerprint(payload) != row.payload_fingerprint
                or row.catalog_id != payload["id"] or row.profile != payload["profile"] or row.scenario != payload["scenario"]
                or row.academic_test_ready != payload["academic_test_ready"]
                or row.monthly_tco_brl != Decimal(payload["scenario_monthly_tco_brl"])
                or row.score != (None if payload["preview_score"] is None else Decimal(payload["preview_score"]))):
            raise AcademicUnavailable("Avaliação persistida inconsistente")
        return deepcopy(payload)

    def metadata(self, snapshot_id=None):
        row = self._snapshot(snapshot_id)
        return {"snapshot_id": row.snapshot_id, "cohort_version": row.cohort_version,
                "cohort_fingerprint": row.cohort_fingerprint, "method_fingerprint": row.method_fingerprint,
                "inventory_count": row.inventory_summary["inventory_count"], "selected_count": row.selected_count,
                "holdout_ids": row.inventory_summary["holdout_ids"],
                "outside_selection_ids": [r["id"] for r in row.inventory_summary["outside_selection"]],
                "profile_counts": row.profile_counts, "limitations": self.limitations}

    def vehicles(self, filters, limit=20, offset=0, snapshot_id=None):
        row = self._snapshot(snapshot_id)
        vehicles, total = self.repository.vehicles(row.snapshot_id, filters, limit, offset)
        return {"snapshot_id": row.snapshot_id, "cohort_fingerprint": row.cohort_fingerprint,
                "items": [self._item(v) for v in vehicles], "total": total, "limit": limit, "offset": offset}

    def vehicle(self, catalog_id, snapshot_id=None):
        snapshot = self._snapshot(snapshot_id)
        row = self.repository.vehicle(snapshot.snapshot_id, catalog_id)
        if row is None:
            raise AcademicNotFound("Veículo não selecionado neste snapshot acadêmico")
        evaluations = {s: {} for s in ("low", "base", "high")}
        for evaluation in self.repository.evaluations(snapshot.snapshot_id, catalog_ids=[catalog_id]):
            evaluations[evaluation.scenario][evaluation.profile] = self._evaluation(evaluation)
        return {"snapshot_id": snapshot.snapshot_id, "cohort_version": snapshot.cohort_version,
                "cohort_fingerprint": snapshot.cohort_fingerprint, "vehicle": self._item(row),
                "evidence": deepcopy(row.payload), "evaluations": evaluations, "limitations": self.limitations}

    def evaluate(self, request):
        snapshot = self._snapshot(request.snapshot_id)
        filters = AcademicFilters(profile=request.profile, scenario=request.scenario,
                                  max_purchase_price_brl=request.max_purchase_price_brl,
                                  max_monthly_tco_brl=request.max_monthly_tco_brl)
        vehicles, count = self.repository.vehicles(snapshot.snapshot_id, filters, 60, 0)
        for vehicle in vehicles:
            self._item(vehicle)
        ids = [v.catalog_id for v in vehicles]
        rows = [self._evaluation(r) for r in self.repository.evaluations(
            snapshot.snapshot_id, profile=request.profile, scenario=request.scenario, catalog_ids=ids, ready_only=True)]
        if len(rows) != count:
            raise AcademicUnavailable("Cobertura acadêmica persistida incompleta")
        # Exact Decimal scores; no new scoring formula or cross-protocol ranking.
        ranked_rows = [{**r, "preview_score": Decimal(r["preview_score"])} for r in rows]
        groups = rankings(ranked_rows)
        returned = []
        for group in groups.values():
            group["ranking"] = group["ranking"][:request.limit]
            returned.extend(item["id"] for item in group["ranking"])
        selected_rows = {str(r["id"]): r for r in rows if r["id"] in returned}
        return {"snapshot_id": snapshot.snapshot_id, "cohort_version": snapshot.cohort_version,
                "cohort_fingerprint": snapshot.cohort_fingerprint, "profile": request.profile,
                "scenario": request.scenario, "eligible_ids": ids, "eligible_count": count,
                "returned_ids": returned, "groups": json_document(groups), "evaluations": selected_rows,
                "limitations": self.limitations, "empty_reason": "No academically eligible vehicle satisfies the explicit filters" if not ids else None}
