"""Catalog activation from already published sources, in disposable databases.

Uses public.vehicles and meta.pipeline_run only for writes. Gold, Silver and
Bronze are read-only here; their existing publishers own ingestion/publication.
The immutable external manifest preserves the legacy snapshot and methodology.
"""
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import MetaData, Table, func, insert, select, text

from data_platform.catalog.academic import method, project_candidates, derive
from data_platform.catalog.adapter import prepare_batch
from data_platform.catalog.crosswalk import fingerprint
from data_platform.catalog.intake import load_selection
from data_platform.transformation.fipe import parse_reference_month


def assert_disposable(engine):
    url = engine.url
    if url.get_backend_name() == 'sqlite':
        if url.database == ':memory:':
            return
        path = Path(url.database or '')
        root = Path(__file__).resolve().parents[2]
        if not path.is_absolute() or not path.name.endswith('_test.db') or root in path.resolve().parents:
            raise ValueError('SQLite activation requires an external disposable _test.db')
        return
    if (url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1', '::1'}
            or not (url.database or '').endswith('_test') or url.query):
        raise ValueError('Activation requires explicitly local disposable PostgreSQL ending in _test')


def _table(connection, name, schema=None):
    return Table(name, MetaData(), schema=schema if connection.dialect.name == 'postgresql' else None,
                 autoload_with=connection, resolve_fks=False)


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _legacy(connection, vehicles):
    rows = [dict(row) for row in connection.execute(select(vehicles).where(vehicles.c.id <= 34).order_by(vehicles.c.id)).mappings()]
    if [row['id'] for row in rows] != list(range(1, 35)):
        raise ValueError('Legacy catalog must contain exactly IDs 1..34')
    for expected, actual in zip(load_selection().baseline, rows):
        if (expected.id, expected.brand, expected.model, expected.year) != (actual['id'], actual['brand'], actual['model'], actual['year']):
            raise ValueError('Legacy identity differs from canonical selection')
    return _json(rows)


def build_manifest(engine, decisions, archive, *, historical_v1=False):
    """Read-only dry preparation; the returned manifest must be saved externally."""
    if not historical_v1:
        raise ValueError('academic-demo-v1 is historical only; current methodology and UI gates are not ready')
    assert_disposable(engine)
    plans = prepare_batch(decisions, archive, historical_v1=True)
    if not plans:
        raise ValueError('An empty activation batch is not a dataset')
    with engine.connect() as connection:
        table = _table(connection, 'vehicles')
        baseline = _legacy(connection, table)
        columns = set(table.c.keys())
    rows = []
    for vehicle in project_candidates(decisions):
        row = {key: value for key, value in asdict(vehicle).items() if key in columns}
        for key in ('use_cases', 'chronic_issues'):
            row[key] = '|'.join(row[key])  # Existing repository join_text contract.
        rows.append(row)
    return {
        'dataset_version': method()['dataset_version'], 'methodology': method(),
        'baseline_version': 'legacy-demo-v0', 'legacy_rows': baseline,
        'legacy_projection': [{**row, **_json(derive(row['price'])['values']),
                               'use_cases': '|'.join(method()['neutral_use_cases'])} for row in baseline],
        'approved_ids': [row['id'] for row in rows], 'new_rows': _json(rows),
        'decision_fingerprints': [row['decision_fingerprint'] for row in plans],
        'source_payload_hashes': [row['raw'].payload_hash for row in plans],
        'category_provenance': 'user selection taxonomy; not a measured score',
        'legacy_input_provenance': 'legacy-demo-v0; not relabeled as observed',
        'status': 'manifest_not_activation_receipt',
    }


def _active(connection, table, active, quality, status):
    query = select(table).where(table.c[active].is_(True), table.c[quality] == 'passed', table.c.status == status)
    if connection.dialect.name == 'postgresql':
        query = query.with_for_update(read=True)
    rows = connection.execute(query).mappings().all()
    if len(rows) != 1:
        raise ValueError(f'Exactly one eligible published dataset required: {table.name}')
    return rows[0]


def published_receipts(connection, decisions, plans):
    """Check exact persisted source chain. Dossier approval cannot satisfy this."""
    fd = _table(connection, 'vehicle_feature_dataset', 'gold')
    pd = _table(connection, 'vehicle_efficiency_dataset', 'gold')
    fipe = _active(connection, fd, 'is_active', 'base_quality_status', 'published')
    pbev = _active(connection, pd, 'is_active_shadow', 'quality_status', 'shadow_published')
    fs = _table(connection, 'vehicle_features_snapshot', 'gold')
    ps = _table(connection, 'vehicle_efficiency_snapshot', 'gold')
    mapping = _table(connection, 'vehicle_source_mapping', 'silver')
    raw = _table(connection, 'fipe_raw', 'bronze')
    pr = _table(connection, 'pbev_raw_row', 'bronze')
    asset = _table(connection, 'pbev_source_asset', 'bronze')
    receipts = []
    for decision, plan in zip(decisions, plans):
        review = decision['review']
        query = select(
            fs.c.gold_record_id.label('fipe_record_id'), ps.c.gold_record_id.label('pbev_record_id'),
            fs.c.vehicle_sk, fs.c.current_price, fs.c.price_reference_month, fs.c.currency,
            fs.c.brand_name, fs.c.model_name, fs.c.model_year, fs.c.fuel_type,
            ps.c.fossil_city_km_l, ps.c.fossil_highway_km_l, ps.c.cycle_year,
            ps.c.fuel_type.label('pbev_fuel'), ps.c.motor_description, ps.c.transmission_code,
            ps.c.model_name.label('pbev_family'), raw.c.payload_hash, pr.c.row_hash,
            asset.c.sha256.label('asset_sha256'),
        ).select_from(fs.join(ps, fs.c.vehicle_sk == ps.c.vehicle_sk)
            .join(mapping, fs.c.source_mapping_id == mapping.c.mapping_id)
            .join(raw, mapping.c.bronze_record_id == raw.c.fipe_raw_id)
            .join(pr, ps.c.pbev_raw_row_id == pr.c.pbev_raw_row_id)
            .join(asset, ps.c.asset_id == asset.c.asset_id)).where(
                fs.c.dataset_version == fipe['dataset_version'], ps.c.dataset_version == pbev['dataset_version'],
                fs.c.fipe_code == review['fipe']['CodigoFipe'], fs.c.year_code == review['year_code'],
                fs.c.vehicle_type == 'car', fs.c.base_quality_status == 'passed', ps.c.quality_status == 'passed',
                mapping.c.mapping_status == 'matched', mapping.c.vehicle_sk == fs.c.vehicle_sk,
                mapping.c.fipe_code == fs.c.fipe_code, mapping.c.year_code == fs.c.year_code,
                raw.c.fipe_code == fs.c.fipe_code, raw.c.year_code == fs.c.year_code,
                raw.c.ingestion_status == 'received', asset.c.asset_status == 'accepted',
                pr.c.asset_id == ps.c.asset_id, pr.c.extraction_status == 'parsed',
            )
        rows = connection.execute(query).mappings().all()
        if len(rows) != 1:
            raise ValueError(f'Published source identity missing or ambiguous for candidate {decision["id"]}')
        row = rows[0]
        identity = plan['silver_candidate'].identity
        expected = {
            'brand_name': identity.brand_name, 'model_name': identity.model_name,
            'model_year': review['approved_year'], 'fuel_type': decision['observed']['fuel'],
            'currency': 'BRL', 'cycle_year': review['approved_year'],
            'pbev_fuel': review['pbev']['fuel_type'], 'motor_description': review['pbev']['motor_description'],
            'transmission_code': review['pbev']['transmission_code'], 'pbev_family': review['pbev_family'],
            'payload_hash': plan['raw'].payload_hash, 'row_hash': review['pbev']['raw']['row_hash'],
            'asset_sha256': review['source_references'][1]['sha256'],
        }
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError(f'Published source lineage differs for candidate {decision["id"]}')
        for key, value in (('current_price', decision['observed']['price_brl']),
                           ('fossil_city_km_l', decision['observed']['city_km_l']),
                           ('fossil_highway_km_l', decision['observed']['highway_km_l'])):
            if Decimal(str(row[key])) != Decimal(str(value)):
                raise ValueError(f'Published measure differs for candidate {decision["id"]}')
        if str(row['price_reference_month']) != parse_reference_month(review['fipe']['MesReferencia']).isoformat():
            raise ValueError('Published price reference month differs')
        receipts.append({'id': decision['id'], 'vehicle_sk': row['vehicle_sk'],
                         'fipe_record_id': row['fipe_record_id'], 'pbev_record_id': row['pbev_record_id'],
                         'fipe_dataset': fipe['dataset_version'], 'pbev_dataset': pbev['dataset_version']})
    return receipts


def _equivalent_row(actual, expected):
    for key, value in expected.items():
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            if actual[key] is None or Decimal(str(actual[key])) != Decimal(str(value)):
                return False
        elif actual[key] != value:
            return False
    return True


def activate_catalog(engine, decisions, archive, manifest_path, *, dry_run=True, acknowledge_academic_demo=False, historical_v1=False):
    """Single atomic write of new catalog IDs and an existing meta run receipt.

    Only test databases are enabled until end-to-end PostgreSQL/UI approval.
    No source publication, schema creation, fixture insertion or Gold mutation.
    """
    if not historical_v1:
        raise ValueError('Operational activation disabled: methodology, source chain, PostgreSQL and UI gates required')
    assert_disposable(engine)
    if not acknowledge_academic_demo:
        raise ValueError('Explicit academic demonstration acknowledgment required')
    path = Path(manifest_path).resolve(strict=True)
    if Path(__file__).resolve().parents[2] in path.parents or not path.is_file():
        raise ValueError('Immutable activation manifest must be outside the repository')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    expected_manifest = build_manifest(engine, decisions, archive, historical_v1=True)
    if fingerprint(manifest) != fingerprint(expected_manifest):
        raise ValueError('Activation manifest differs from current sources, method or legacy baseline')
    plans = prepare_batch(decisions, archive, historical_v1=True)
    reference = 'catalog-manifest-sha256:' + fingerprint(manifest)
    with engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text('SELECT pg_advisory_xact_lock(hashtext(:name))'), {'name': 'sigra-catalog-academic-v1'})
            connection.execute(text('LOCK TABLE public.vehicles IN SHARE ROW EXCLUSIVE MODE'))
        elif connection.dialect.name == 'sqlite':
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        vehicles = _table(connection, 'vehicles')
        runs = _table(connection, 'pipeline_run', 'meta')
        if _legacy(connection, vehicles) != manifest['legacy_rows']:
            raise ValueError('Legacy baseline changed before transaction')
        receipts = published_receipts(connection, decisions, plans)
        ids = manifest['approved_ids']
        all_before = [dict(row) for row in connection.execute(select(vehicles).order_by(vehicles.c.id)).mappings()]
        existing = {row['id']: row for row in all_before if row['id'] in ids}
        run_uuid = uuid5(NAMESPACE_URL, manifest['dataset_version'])
        run_id = run_uuid if connection.dialect.name == 'postgresql' else run_uuid.hex
        prior = connection.execute(select(runs).where(runs.c.pipeline_run_id == run_id)).mappings().one_or_none()
        if prior:
            if (prior['status'] != 'succeeded' or prior['source_reference'] != reference
                    or prior['pipeline_name'] != 'catalog_academic_activation'
                    or prior['pipeline_version'] != 'academic-demo-v1'
                    or prior['dataset_version'] != manifest['dataset_version']
                    or set(existing) != set(ids) or any(not _equivalent_row(existing[row['id']], row) for row in manifest['new_rows'])):
                raise ValueError('Existing activation differs; a new reviewed dataset version is required')
            return {'status': 'already_applied', 'inserted': 0, 'activated': len(ids), 'count': len(all_before),
                    'dataset_version': manifest['dataset_version'], 'receipts': receipts, 'dry_run': dry_run}
        if existing:
            raise ValueError('Requested IDs already exist without this activation receipt')
        if dry_run:
            return {'status': 'dry_run', 'inserted': 0, 'approved': len(ids), 'count': len(all_before),
                    'receipts': receipts, 'dataset_version': manifest['dataset_version']}
        # The database supplies both timestamps; no mixed Python/transaction clocks.
        now = connection.execute(select(func.current_timestamp())).scalar_one()
        connection.execute(insert(runs).values(
            pipeline_run_id=run_id, pipeline_name='catalog_academic_activation', pipeline_version='academic-demo-v1',
            dataset_version=manifest['dataset_version'], trigger_type='manual', status='succeeded',
            started_at=now, finished_at=now, source_reference=reference, records_received=len(ids),
            records_inserted=len(ids), records_deduplicated=0, records_rejected=0,
        ))
        for row in manifest['new_rows']:
            connection.execute(insert(vehicles).values(**row))
        after = [dict(row) for row in connection.execute(select(vehicles).order_by(vehicles.c.id)).mappings()]
        if [row for row in after if row['id'] not in ids] != all_before or len(after) != len(all_before) + len(ids):
            raise RuntimeError('Catalog preservation/count postcondition failed; rollback required')
        if _legacy(connection, vehicles) != manifest['legacy_rows']:
            raise RuntimeError('Legacy preservation failed; rollback required')
        published_receipts(connection, decisions, plans)
    return {'status': 'applied', 'inserted': len(ids), 'activated': len(ids), 'count': len(after),
            'dataset_version': manifest['dataset_version'], 'manifest_fingerprint': fingerprint(manifest),
            'baseline_preserved': True, 'gold_modified': False, 'receipts': receipts}
