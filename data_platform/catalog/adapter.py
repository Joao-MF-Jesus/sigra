"""Offline adapter to existing Bronze/Silver contracts; publication is fail-closed.

No parallel tables, startup hook, network access or implicit seed. Approval of
a dossier is NOT a Gold publication receipt and cannot enable catalog writes.
"""
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
from uuid import UUID

from data_platform.catalog.crosswalk import BATCH2_REVIEW_PATH, REVIEW_PATH, decide, fingerprint, mechanical_key
from data_platform.catalog.intake import load_selection
from data_platform.contracts.fipe import FipeTarget
from data_platform.contracts.silver_fipe import BronzeFipeInput
from data_platform.ingestion.fipe.client import FipeResponse
from data_platform.ingestion.fipe.extractor import extract_record
from data_platform.quality.bronze_checks import validate_record
from data_platform.transformation.fipe import transform_bronze_record


class SourceArchive:
    def __init__(self, directories):
        self.directories = tuple(Path(path).resolve(strict=True) for path in directories)

    def bytes(self, reference):
        name = reference['cache_file']
        if Path(name).name != name:
            raise ValueError('Source path must be a filename')
        for directory in self.directories:
            file = directory / name
            if file.is_file():
                content = file.read_bytes()
                if hashlib.sha256(content).hexdigest() == reference['sha256']:
                    return content
        raise ValueError('Immutable source snapshot not found or hash mismatch')

    def validate(self, review):
        for reference in review['source_references']:
            self.bytes(reference)
        if json.loads(self.bytes(review['source_references'][0])) != review['fipe']:
            raise ValueError('FIPE observation differs from immutable snapshot')
        reference = {
            'cache_file': f"pbev-{review['approved_year']}-parsed.json",
            'sha256': review['pbev_parse_snapshot_sha256'],
        }
        parsed = json.loads(self.bytes(reference))['rows']
        for observation in [review['pbev'], *review['applicable_pbev_rows']]:
            matches = [row for row in parsed if row['raw']['row_hash'] == observation['raw']['row_hash']]
            if len(matches) != 1:
                raise ValueError('PBEV row evidence is ambiguous')
            for key, value in observation.items():
                actual = matches[0][key]
                if key == 'raw':
                    actual = {field: actual[field] for field in value}
                if actual != value:
                    raise ValueError('PBEV observed fields changed')
        expected = set()
        chosen = review['pbev']
        for row in parsed:
            if row['brand_name'] != chosen['brand_name'] or row['model_name'] != chosen['model_name']:
                continue
            try:
                if mechanical_key(row) != mechanical_key(chosen):
                    continue
            except ValueError:
                continue
            if review['link_type'] != 'shared_powertrain_group' and row['version_name'] != chosen['version_name']:
                continue
            expected.add(row['raw']['row_hash'])
        if expected != {row['raw']['row_hash'] for row in review['applicable_pbev_rows']}:
            raise ValueError('Applicable source rows were omitted from review')


# Field-name adaptation is explicit and versioned. The original raw payload,
# hash and endpoint are kept in Bronze. This view is NEVER an HTTP response.
V1_TO_SILVER_FIELDS = {
    'TipoVeiculo': 'vehicleType', 'Valor': 'price', 'Marca': 'brand',
    'Modelo': 'model', 'AnoModelo': 'modelYear', 'Combustivel': 'fuel',
    'CodigoFipe': 'codeFipe', 'MesReferencia': 'referenceMonth',
    'SiglaCombustivel': 'fuelAcronym',
}


def prepare_source(submitted, archive, *, historical_v1=False):
    """Revalidate sources and prepare existing pipeline inputs without writing."""
    expected_status = 'approved_for_activation' if historical_v1 else 'identity_approved'
    if submitted.get('status') != expected_status:
        raise ValueError('Blocked record cannot enter the adapter')
    candidate = next(row for row in load_selection().candidates if row.id == submitted['id'])
    checked = decide(candidate, submitted['review'], historical_v1=historical_v1)
    if checked['status'] != expected_status or fingerprint(checked) != fingerprint(submitted):
        raise ValueError('Activation decision changed or failed revalidation')
    review = checked['review']
    registered = [
        row
        for path in (REVIEW_PATH, BATCH2_REVIEW_PATH)
        for row in json.loads(path.read_text(encoding='utf-8'))['reviews']
        if row['id'] == candidate.id
    ]
    if len(registered) != 1 or fingerprint(registered[0]) != fingerprint(review):
        raise ValueError('Review differs from the versioned approval inventory')
    archive.validate(review)
    reference = review['source_references'][0]
    target = FipeTarget('car', review['fipe']['CodigoFipe'], review['year_code'])
    response = FipeResponse(reference['url'], 200, archive.bytes(reference), datetime.fromisoformat(reference['collected_at']))
    raw = extract_record(response, target)
    if validate_record(raw):
        raise ValueError('Existing Bronze gates rejected source')
    # IDs are deliberately absent at preparation time. Zero is an explicit
    # nonpersistable placeholder in this in-memory contract, never a DB key.
    original = BronzeFipeInput(
        fipe_raw_id=0, bronze_pipeline_run_id=UUID(int=0),
        **{key: value for key, value in asdict(raw).items() if key in BronzeFipeInput.__dataclass_fields__},
    )
    normalized = {target: review['fipe'][source] for source, target in V1_TO_SILVER_FIELDS.items()}
    transformed = transform_bronze_record(replace(original, payload=normalized))
    if transformed.mapping_status != 'matched' or transformed.price is None or transformed.has_blocking_issue:
        raise ValueError('Existing Silver gates rejected adapted observation')
    transformed = replace(transformed, bronze=original)
    return {
        'id': candidate.id, 'status': 'prepared_not_published',
        'adapter_version': 'fipe-v1-to-silver-v1', 'target': asdict(target),
        'raw': raw, 'silver_candidate': transformed,
        'normalization': {'field_map': V1_TO_SILVER_FIELDS, 'original_payload_preserved': True},
        'pbev_crosswalk': review, 'decision_fingerprint': checked['decision_fingerprint'],
    }


def prepare_batch(decisions, archive, *, historical_v1=False):
    """Only explicitly approved records are accepted, with no implicit filtering."""
    plans = [prepare_source(row, archive, historical_v1=historical_v1) for row in decisions]
    identities = [(row['target']['fipe_code'], row['target']['year_code'][:4]) for row in plans]
    if len(set(identities)) != len(identities) or len({row['id'] for row in plans}) != len(plans):
        raise ValueError('Duplicate FIPE/year or catalog ID')
    from app.fipe import FIPE_REFERENCE_PROFILES
    legacy = {(row.code, row.year_code[:4]) for row in FIPE_REFERENCE_PROFILES.values()}
    if set(identities) & legacy:
        raise ValueError('Identity overlaps legacy catalog')
    return plans


def activate_prepared(*args, **kwargs):
    """Explicit activation entry point; never a startup hook."""
    from data_platform.catalog.activation import activate_catalog
    return activate_catalog(*args, **kwargs)
