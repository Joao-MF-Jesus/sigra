"""CI record fixture, explicitly distinct from the full documentary bundle audit."""
from functools import lru_cache
import os
from pathlib import Path

from app.academic_cohort import revision6_homologation as h
from app.academic_cohort import safety_revision6 as s
from app.academic_cohort.contracts import json_document
from app.deployment import load_plan
from app.packed_plan import APPROVED_SHA256
from data_platform.catalog import academic_cohort_v6 as v6, profile_pilot_v4 as v4


@lru_cache(maxsize=1)
def fixture_plan():
    bundle = Path(os.environ['SIGRA_REVISION6_BUNDLE']).resolve(strict=True)
    decision_file = Path(os.environ['SIGRA_REVISION6_DECISION']).resolve(strict=True)
    mode = os.environ.get('SIGRA_REVISION6_FIXTURE_MODE', 'documentary-bundle-v1')
    if mode == 'documentary-bundle-v1':
        return h.build_plan(bundle, decision_file)
    if mode != 'pinned-runtime-plan-v1':
        raise ValueError('UNKNOWN_EXPLICIT_FIXTURE_MODE')
    plan = load_plan(str(bundle / 'plan.json'), APPROVED_SHA256)
    if s._read(decision_file) != plan.proposal.coverage_decision:
        raise ValueError('CI_COVERAGE_DECISION_DIFFERS')
    # Full V6/Revision6 payload and transport checks, then every existing engine
    # result. No changed assertion, new reference or untrusted package execution.
    h.validate_plan(plan)
    for row in plan.replay['academic_payload']:
        vehicle = v6.V6ProfileVehicle.model_validate(row['vehicle'])
        for scenario, profiles in row['evaluations'].items():
            for profile, expected in profiles.items():
                engine = v6.evaluate_vehicle if 'price_reference_policy_version' in expected else v4.evaluate_vehicle
                actual = json_document(engine(vehicle, profile, scenario, '2026-09'))
                if v4.fingerprint(actual) != v4.fingerprint(expected):
                    raise ValueError('CI_EXISTING_ENGINE_REPLAY_DIFFERS')
    return plan
