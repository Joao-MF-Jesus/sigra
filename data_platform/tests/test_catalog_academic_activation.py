"""SQLite contract fixtures, not PostgreSQL/Gold publication attestation.

These fixtures model existing tables only in a disposable test database.
Production has no DDL, seed, synthetic-source injection or fixture fallback.
"""
from dataclasses import asdict
from functools import partial
import json

import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, create_engine, insert, select, text, update

from data_platform.catalog.activation import activate_catalog, assert_disposable, build_manifest
from data_platform.catalog.adapter import prepare_batch
from data_platform.catalog.crosswalk import review_batch

# Historical v1 contract reproduction only; public defaults prohibit activation.
review_batch = partial(review_batch, historical_v1=True)
prepare_batch = partial(prepare_batch, historical_v1=True)
build_manifest = partial(build_manifest, historical_v1=True)
activate_catalog = partial(activate_catalog, historical_v1=True)


class FixtureArchive:
    def __init__(self, decisions):
        self.reviews = [row['review'] for row in decisions]

    def validate(self, review):
        assert review in self.reviews

    def bytes(self, reference):
        review = next(row for row in self.reviews if row['source_references'][0] == reference)
        return json.dumps(review['fipe'], ensure_ascii=False).encode()


def fixture_database(path, decisions):
    from app.models import Vehicle
    from app.sample_data import VEHICLES
    engine = create_engine('sqlite:///' + path.as_posix())
    Vehicle.__table__.create(engine)
    metadata = MetaData()
    definitions = {
        'pipeline_run': {'pipeline_run_id': String(32), 'pipeline_name': String, 'pipeline_version': String,
            'dataset_version': String, 'trigger_type': String, 'status': String,
            'started_at': DateTime, 'finished_at': DateTime, 'source_reference': String,
            'records_received': Integer, 'records_inserted': Integer, 'records_deduplicated': Integer, 'records_rejected': Integer},
        'vehicle_feature_dataset': {'dataset_version': String, 'is_active': Boolean, 'base_quality_status': String, 'status': String},
        'vehicle_efficiency_dataset': {'dataset_version': String, 'is_active_shadow': Boolean, 'quality_status': String, 'status': String},
        'vehicle_features_snapshot': {'gold_record_id': Integer, 'dataset_version': String, 'source_mapping_id': Integer,
            'vehicle_sk': Integer, 'fipe_code': String, 'year_code': String, 'vehicle_type': String, 'base_quality_status': String,
            'current_price': Numeric(14, 2), 'price_reference_month': Date, 'currency': String,
            'brand_name': String, 'model_name': String, 'model_year': Integer, 'fuel_type': String},
        'vehicle_efficiency_snapshot': {'gold_record_id': Integer, 'dataset_version': String, 'vehicle_sk': Integer,
            'pbev_raw_row_id': Integer, 'asset_id': Integer, 'quality_status': String, 'fossil_city_km_l': Numeric(10, 4),
            'fossil_highway_km_l': Numeric(10, 4), 'cycle_year': Integer, 'fuel_type': String,
            'motor_description': String, 'transmission_code': String, 'model_name': String},
        'vehicle_source_mapping': {'mapping_id': Integer, 'vehicle_sk': Integer, 'bronze_record_id': Integer,
            'mapping_status': String, 'fipe_code': String, 'year_code': String},
        'fipe_raw': {'fipe_raw_id': Integer, 'fipe_code': String, 'year_code': String, 'ingestion_status': String, 'payload_hash': String},
        'pbev_raw_row': {'pbev_raw_row_id': Integer, 'asset_id': Integer, 'row_hash': String, 'extraction_status': String},
        'pbev_source_asset': {'asset_id': Integer, 'asset_status': String, 'sha256': String},
    }
    tables = {name: Table(name, metadata, *[Column(column, kind, primary_key=(index == 0))
               for index, (column, kind) in enumerate(definition.items())]) for name, definition in definitions.items()}
    metadata.create_all(engine)
    archive = FixtureArchive(decisions)
    plans = prepare_batch(decisions, archive)
    with engine.begin() as connection:
        for vehicle in VEHICLES:
            row = {key: value for key, value in asdict(vehicle).items() if key in Vehicle.__table__.c}
            for key in ('use_cases', 'chronic_issues'):
                row[key] = '|'.join(row[key])
            connection.execute(insert(Vehicle.__table__).values(**row))
        connection.execute(insert(tables['vehicle_feature_dataset']).values(dataset_version='contract-fixture-fipe', is_active=True, base_quality_status='passed', status='published'))
        connection.execute(insert(tables['vehicle_efficiency_dataset']).values(dataset_version='contract-fixture-pbev', is_active_shadow=True, quality_status='passed', status='shadow_published'))
        for decision, plan in zip(decisions, plans):
            identifier = decision['id']; review = decision['review']; identity = plan['silver_candidate'].identity
            connection.execute(insert(tables['fipe_raw']).values(fipe_raw_id=identifier, fipe_code=review['fipe']['CodigoFipe'], year_code=review['year_code'], ingestion_status='received', payload_hash=plan['raw'].payload_hash))
            connection.execute(insert(tables['vehicle_source_mapping']).values(mapping_id=identifier, vehicle_sk=identifier + 1000, bronze_record_id=identifier, mapping_status='matched', fipe_code=review['fipe']['CodigoFipe'], year_code=review['year_code']))
            connection.execute(insert(tables['pbev_source_asset']).values(asset_id=identifier, asset_status='accepted', sha256=review['source_references'][1]['sha256']))
            connection.execute(insert(tables['pbev_raw_row']).values(pbev_raw_row_id=identifier, asset_id=identifier, row_hash=review['pbev']['raw']['row_hash'], extraction_status='parsed'))
            connection.execute(insert(tables['vehicle_features_snapshot']).values(gold_record_id=identifier, dataset_version='contract-fixture-fipe', source_mapping_id=identifier, vehicle_sk=identifier + 1000,
                fipe_code=review['fipe']['CodigoFipe'], year_code=review['year_code'], vehicle_type='car', base_quality_status='passed', current_price=decision['observed']['price_brl'],
                price_reference_month=plan['silver_candidate'].price.reference_month, currency='BRL', brand_name=identity.brand_name, model_name=identity.model_name, model_year=identity.model_year, fuel_type=identity.fuel_type))
            connection.execute(insert(tables['vehicle_efficiency_snapshot']).values(gold_record_id=identifier, dataset_version='contract-fixture-pbev', vehicle_sk=identifier + 1000, pbev_raw_row_id=identifier, asset_id=identifier, quality_status='passed',
                fossil_city_km_l=decision['observed']['city_km_l'], fossil_highway_km_l=decision['observed']['highway_km_l'], cycle_year=review['approved_year'], fuel_type=review['pbev']['fuel_type'],
                motor_description=review['pbev']['motor_description'], transmission_code=review['pbev']['transmission_code'], model_name=review['pbev_family']))
    return engine, archive, tables


@pytest.fixture
def activation_case(tmp_path):
    decisions = [row for row in review_batch()['decisions'] if row['status'] == 'approved_for_activation']
    engine, archive, tables = fixture_database(tmp_path / 'catalog_test.db', decisions)
    manifest = build_manifest(engine, decisions, archive)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, default=str), encoding='utf-8')
    try:
        yield engine, decisions, archive, tables, path, manifest
    finally:
        engine.dispose()


def snapshot(engine):
    with engine.connect() as connection:
        return {name: [tuple(row) for row in connection.execute(text('SELECT * FROM ' + name + ' ORDER BY 1'))]
                for name in ('vehicles', 'pipeline_run', 'fipe_raw', 'vehicle_features_snapshot', 'vehicle_efficiency_snapshot')}


def run_case(case, **options):
    engine, decisions, archive, _tables, path, _manifest = case
    return activate_catalog(engine, decisions, archive, path, acknowledge_academic_demo=True, **options)


def test_dry_run_writes_nothing(activation_case):
    before = snapshot(activation_case[0])
    result = run_case(activation_case)
    assert result['status'] == 'dry_run' and result['inserted'] == 0 and result['approved'] == 19
    assert snapshot(activation_case[0]) == before


def test_transactional_activation_and_repeat_preserve_baseline_and_sources(activation_case):
    before = snapshot(activation_case[0])
    first = run_case(activation_case, dry_run=False)
    after = snapshot(activation_case[0])
    second = run_case(activation_case, dry_run=False)
    assert first['count'] == 53 and first['inserted'] == 19
    assert second['status'] == 'already_applied' and second['inserted'] == 0
    assert after == snapshot(activation_case[0])
    assert after['vehicles'][:34] == before['vehicles']
    for source in ('fipe_raw', 'vehicle_features_snapshot', 'vehicle_efficiency_snapshot'):
        assert after[source] == before[source]
    assert len(after['pipeline_run']) == 1


def test_database_failure_rolls_back_all_new_ids_and_receipt(activation_case):
    engine = activation_case[0]
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TRIGGER fail_test_insert BEFORE INSERT ON vehicles WHEN NEW.id=36 BEGIN SELECT RAISE(ABORT, 'injected contract failure'); END")
    before = snapshot(engine)
    with pytest.raises(Exception, match='injected contract failure'):
        run_case(activation_case, dry_run=False)
    assert snapshot(engine) == before


@pytest.mark.parametrize('fault', ['inactive', 'ambiguous_dataset', 'missing_pbev', 'wrong_row_hash', 'changed_price'])
def test_missing_or_conflicting_publication_blocks_every_write(activation_case, fault):
    engine, _, _, tables, _, _ = activation_case
    with engine.begin() as connection:
        if fault == 'inactive':
            connection.execute(update(tables['vehicle_feature_dataset']).values(is_active=False))
        elif fault == 'ambiguous_dataset':
            connection.execute(insert(tables['vehicle_feature_dataset']).values(dataset_version='second-contract-fixture', is_active=True, base_quality_status='passed', status='published'))
        elif fault == 'missing_pbev':
            connection.execute(update(tables['vehicle_efficiency_snapshot']).values(vehicle_sk=999))
        elif fault == 'wrong_row_hash':
            connection.execute(update(tables['pbev_raw_row']).values(row_hash='0' * 64))
        else:
            connection.execute(update(tables['vehicle_features_snapshot']).values(current_price=1))
    before = snapshot(engine)
    with pytest.raises(ValueError):
        run_case(activation_case, dry_run=False)
    assert snapshot(engine) == before


def test_baseline_manifest_is_mandatory_and_immutable(activation_case):
    path = activation_case[4]
    content = json.loads(path.read_text(encoding='utf-8'))
    content['legacy_rows'][0]['price'] = '1'
    path.write_text(json.dumps(content), encoding='utf-8')
    with pytest.raises(ValueError, match='manifest differs'):
        run_case(activation_case, dry_run=False)
    assert len(snapshot(activation_case[0])['vehicles']) == 34


def test_preoccupied_id_never_overwritten(activation_case):
    engine = activation_case[0]
    with engine.begin() as connection:
        vehicles = Table('vehicles', MetaData(), autoload_with=connection)
        row = dict(connection.execute(select(vehicles).where(vehicles.c.id == 1)).mappings().one())
        row['id'] = 35
        connection.execute(insert(vehicles).values(**row))
    before = snapshot(engine)
    with pytest.raises(ValueError, match='already exist'):
        run_case(activation_case, dry_run=False)
    assert snapshot(engine) == before


@pytest.mark.parametrize('url', ['sqlite:///local.db', 'postgresql://localhost/sigra_postgresql_demo', 'postgresql://example.invalid/catalog_test'])
def test_no_operational_database_or_implicit_sqlite_fallback(url):
    from sqlalchemy.engine import make_url
    class Target:
        pass
    target = Target(); target.url = make_url(url)
    with pytest.raises(ValueError):
        assert_disposable(target)
