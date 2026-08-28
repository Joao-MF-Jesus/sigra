from __future__ import annotations

import csv
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import io
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from data_platform.anp.loader import AnpFuelPriceLoader
from data_platform.anp.pipeline import AnpExecutionOptions, run_anp_pipeline
from data_platform.anp.sources import (
    ANP_EXPECTED_HEADER,
    ANP_EXPECTED_LAYOUT_FINGERPRINT,
    ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
    ANP_LAST_FOUR_WEEKS_FILENAME,
    ANP_LAST_FOUR_WEEKS_REFERENCE,
    ANP_OFFICIAL_PAGE_URL,
    layout_fingerprint,
)
from data_platform.contracts.anp_fuel_prices import (
    ANP_REQUIRED_PRODUCTS,
    PILOT_PRODUCTS,
    DownloadedAnpAsset,
    ProductCode,
)
from data_platform.ingestion.anp.client import AnpCsvClient, AnpDownloadPolicy
from data_platform.ingestion.anp.parser import AnpCsvParser
from data_platform.quality.anp_checks import build_snapshots, evaluate_quality, percentile, require_hard_gates
from data_platform.transformation.anp import transform_asset


def _check_digits(base: str) -> str:
    digits = base
    for weights in (
        (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
        (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
    ):
        total = sum(int(digits[index]) * weight for index, weight in enumerate(weights))
        remainder = total % 11
        digits += str(0 if remainder < 2 else 11 - remainder)
    return digits


SYNTHETIC_CNPJ = _check_digits("123456780001")


def _row(**changes: str) -> dict[str, str]:
    base = {
        "Regiao - Sigla": "SE",
        "Estado - Sigla": "SP",
        "Municipio": "Cidade Sintética",
        "Revenda": "Posto Sintético, Unidade 1",
        "CNPJ da Revenda": SYNTHETIC_CNPJ,
        "Nome da Rua": "Rua de Teste",
        "Numero Rua": "10",
        "Complemento": "",
        "Bairro": "Centro",
        "Cep": "00000-000",
        "Produto": "GASOLINA",
        "Data da Coleta": "04/08/2026",
        "Valor de Venda": "5,6789",
        "Valor de Compra": "",
        "Unidade de Medida": "R$ / litro",
        "Bandeira": "BANDEIRA SINTÉTICA",
    }
    base.update(changes)
    return base


def _csv_bytes(rows: list[dict[str, str]], *, header=ANP_EXPECTED_HEADER, bom=True) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, delimiter=";", quotechar='"', lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in header})
    encoded = stream.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + encoded) if bom else encoded


def _asset(path: Path, content: bytes) -> DownloadedAnpAsset:
    path.write_bytes(content)
    return DownloadedAnpAsset(
        source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
        official_page_url=ANP_OFFICIAL_PAGE_URL,
        download_url_sanitized=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
        filename=path.name,
        path=path,
        collected_at=datetime(2026, 8, 11, tzinfo=UTC),
        http_status=200,
        content_type="text/csv",
        byte_length=len(content),
        etag=None,
        last_modified=None,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _parse(tmp_path: Path, rows: list[dict[str, str]], *, bom=True):
    content = _csv_bytes(rows, bom=bom)
    return AnpCsvParser().parse(_asset(tmp_path / ANP_LAST_FOUR_WEEKS_FILENAME, content))


def test_audited_layout_fingerprint_is_stable():
    assert layout_fingerprint(ANP_EXPECTED_HEADER) == ANP_EXPECTED_LAYOUT_FINGERPRINT
    assert ANP_EXPECTED_LAYOUT_FINGERPRINT == "7dff6acd7e0a8f0113d18959081da8adac1eec7659bc75aad540dbabb4fc6786"


@pytest.mark.parametrize("bom", [False, True])
def test_parser_accepts_only_audited_utf8_variants_and_semicolon(tmp_path, bom):
    parsed = _parse(tmp_path, [_row()], bom=bom)
    assert parsed.layout_fingerprint == ANP_EXPECTED_LAYOUT_FINGERPRINT
    assert parsed.period_start == parsed.period_end
    assert parsed.rows[0].payload["Revenda"] == "Posto Sintético, Unidade 1"
    assert parsed.technical_metadata["delimiter"] == ";"


def test_parser_rejects_unproven_encoding(tmp_path):
    content = _csv_bytes([_row()], bom=False).decode("utf-8").encode("cp1252")
    with pytest.raises(ValueError, match="encoding"):
        AnpCsvParser().parse(_asset(tmp_path / "unproven.csv", content))


@pytest.mark.parametrize(
    "header",
    [
        ANP_EXPECTED_HEADER[:-1],
        ANP_EXPECTED_HEADER + ("Coluna Nova",),
        (ANP_EXPECTED_HEADER[1], ANP_EXPECTED_HEADER[0], *ANP_EXPECTED_HEADER[2:]),
    ],
)
def test_parser_blocks_missing_extra_and_reordered_columns(tmp_path, header):
    content = _csv_bytes([_row()], header=header)
    with pytest.raises(ValueError, match="layout drift"):
        AnpCsvParser().parse(_asset(tmp_path / "drift.csv", content))


def test_decimal_products_and_privacy_minimization(tmp_path):
    parsed = _parse(
        tmp_path,
        [
            _row(),
            _row(**{"Produto": "GASOLINA ADITIVADA", "Valor de Venda": "6,1111"}),
            _row(**{"Produto": "ETANOL", "Valor de Venda": "4,2500"}),
        ],
    )
    batch = transform_asset(parsed)
    assert {item.product_code for item in batch.observations} == {
        ProductCode.GASOLINE_C_COMMON,
        ProductCode.GASOLINE_C_ADDITIZED,
        ProductCode.ETHANOL_HYDRATED,
    }
    common = next(item for item in batch.observations if item.product_code == ProductCode.GASOLINE_C_COMMON)
    assert common.sale_price == Decimal("5.6789")
    assert isinstance(common.sale_price, Decimal)
    assert common.purchase_price is None
    assert common.cnpj_hash and len(common.cnpj_hash) == 64
    assert not hasattr(common, "cnpj")


def test_required_and_pilot_product_contracts_are_explicit():
    assert ANP_REQUIRED_PRODUCTS == {
        ProductCode.GASOLINE_C_COMMON,
        ProductCode.ETHANOL_HYDRATED,
    }
    assert PILOT_PRODUCTS == {
        ProductCode.GASOLINE_C_COMMON,
        ProductCode.GASOLINE_C_ADDITIZED,
        ProductCode.ETHANOL_HYDRATED,
    }


@pytest.mark.parametrize("cnpj", ["00000000000000", "", "123"])
def test_invalid_or_missing_cnpj_uses_controlled_fallback(tmp_path, cnpj):
    batch = transform_asset(_parse(tmp_path, [_row(**{"CNPJ da Revenda": cnpj})]))
    assert len(batch.observations) == 1
    assert batch.observations[0].identity_method == "fallback_identity"
    assert batch.observations[0].cnpj_hash is None
    assert [issue.rule_code for issue in batch.issues] == ["ANP_ESTABLISHMENT_FALLBACK_IDENTITY"]
    assert cnpj not in repr(batch.issues) if cnpj else True


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({"Produto": "QUEROSENE"}, "ANP_UNKNOWN_PRODUCT"),
        ({"Produto": "DIESEL S10"}, "ANP_PRODUCT_OUTSIDE_RESOURCE"),
        ({"Unidade de Medida": "R$ / kg"}, "ANP_INCOMPATIBLE_UNIT"),
        ({"Valor de Venda": "0,0000"}, "ANP_INVALID_PRICE"),
        ({"Valor de Venda": "-1,0000"}, "ANP_INVALID_PRICE"),
        ({"Valor de Compra": "-1,0000"}, "ANP_INVALID_PRICE"),
        ({"Estado - Sigla": "SP", "Regiao - Sigla": "S"}, "ANP_INVALID_GEOGRAPHY"),
    ],
)
def test_silver_hard_rules_block_invalid_observations(tmp_path, changes, rule):
    batch = transform_asset(_parse(tmp_path, [_row(**changes)]))
    assert batch.observations == ()
    assert batch.rejected_count == 1
    assert batch.issues[0].rule_code == rule


def test_same_asset_deduplicates_equal_content_and_rejects_divergent_identity(tmp_path):
    duplicate = transform_asset(_parse(tmp_path, [_row(), _row()]))
    assert len(duplicate.observations) == 1
    assert duplicate.deduplicated_count == 1
    conflict = transform_asset(_parse(tmp_path, [_row(), _row(**{"Valor de Venda": "5,9999"})]))
    assert conflict.observations == ()
    assert conflict.rejected_count == 2
    assert conflict.issues[0].severity == "critical"


def test_overlapping_windows_have_stable_identity_and_changed_content(tmp_path):
    first = transform_asset(_parse(tmp_path, [_row()])).observations[0]
    (tmp_path / ANP_LAST_FOUR_WEEKS_FILENAME).unlink()
    equal = transform_asset(_parse(tmp_path, [_row()])).observations[0]
    (tmp_path / ANP_LAST_FOUR_WEEKS_FILENAME).unlink()
    corrected = transform_asset(_parse(tmp_path, [_row(**{"Valor de Venda": "5,7000"})])).observations[0]
    assert first.observation_key == equal.observation_key == corrected.observation_key
    assert first.content_hash == equal.content_hash
    assert first.content_hash != corrected.content_hash


def test_decimal_quartiles_and_weekly_shadow_aggregation(tmp_path):
    rows = [
        _row(**{"CNPJ da Revenda": _check_digits(f"{index:012d}"), "Valor de Venda": value})
        for index, value in enumerate(("4,0000", "5,0000", "6,0000", "9,0000"), start=1)
    ]
    observations = transform_asset(_parse(tmp_path, rows)).observations
    assert percentile([item.sale_price for item in observations], Decimal("0.25")) == Decimal("4.7500")
    snapshots = build_snapshots(observations, reference_period_end=max(item.collection_date for item in observations))
    municipality = next(item for item in snapshots if item.geography_level == "municipality")
    assert municipality.mean_price == Decimal("6.0000")
    assert municipality.median_price == Decimal("5.5000")
    assert municipality.percentile_75 == Decimal("6.7500")
    assert municipality.interquartile_range == Decimal("2.0000")
    assert municipality.sampling_status == municipality.dispersion_status == "not_calibrated"
    assert len({item.snapshot_fingerprint for item in snapshots}) == len(snapshots)


def _quality_for_products(tmp_path, products):
    rows = [
        _row(
            **{
                "Produto": product,
                "CNPJ da Revenda": _check_digits(f"{index:012d}"),
            }
        )
        for index, product in enumerate(products, start=1)
    ]
    observations = transform_asset(_parse(tmp_path, rows)).observations
    snapshots = build_snapshots(observations, reference_period_end=observations[0].collection_date)
    results = evaluate_quality(observations, snapshots, ())
    required = next(
        item for item in results
        if item.rule_code == "ANP_REQUIRED_PRODUCTS_PRESENT"
    )
    return results, required


@pytest.mark.parametrize(
    "products",
    [
        ("GASOLINA", "ETANOL"),
        ("GASOLINA", "ETANOL", "GASOLINA ADITIVADA"),
    ],
)
def test_required_products_pass_with_or_without_additized_gasoline(tmp_path, products):
    results, required = _quality_for_products(tmp_path, products)
    require_hard_gates(results)
    assert required.status == "passed"
    assert required.severity == "critical"
    assert required.observed_value == {
        "product_codes": sorted(
            ProductCode(item).value
            for item in (
                ProductCode.GASOLINE_C_COMMON,
                ProductCode.ETHANOL_HYDRATED,
                *(
                    (ProductCode.GASOLINE_C_ADDITIZED,)
                    if "GASOLINA ADITIVADA" in products
                    else ()
                ),
            )
        )
    }
    assert sum(item.status == "not_calibrated" for item in results) == 7


@pytest.mark.parametrize(
    "products",
    [
        ("GASOLINA",),
        ("ETANOL",),
        ("GASOLINA ADITIVADA",),
    ],
)
def test_missing_required_product_fails_the_hard_gate(tmp_path, products):
    results, required = _quality_for_products(tmp_path, products)
    assert required.status == "failed"
    assert set(required.observed_value["product_codes"]) == {
        transform_asset(_parse(tmp_path, [_row(**{"Produto": products[0]})]))
        .observations[0]
        .product_code.value
    }
    assert sum(item.status == "not_calibrated" for item in results) == 7
    with pytest.raises(ValueError, match="hard gates"):
        require_hard_gates(results)


def test_client_streams_csv_retries_only_allowed_status_and_removes_failure(tmp_path):
    calls = 0
    content = _csv_bytes([_row()])

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, headers={"content-type": "text/csv"}, content=content, request=request)

    client = AnpCsvClient(
        transport=httpx.MockTransport(handler),
        policy=AnpDownloadPolicy(attempts=2, retry_delay_seconds=0.0),
    )
    downloaded = client.download(
        source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
        official_page_url=ANP_OFFICIAL_PAGE_URL,
        download_url=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
        filename="synthetic.csv",
        destination_directory=tmp_path,
    )
    assert calls == 2
    assert downloaded.byte_length == len(content)
    assert downloaded.sha256 == hashlib.sha256(content).hexdigest()
    downloaded.path.unlink()


def test_download_policy_default_limit_is_32_mib():
    assert AnpDownloadPolicy().max_asset_bytes == 32 * 1024 * 1024


@pytest.mark.parametrize("invalid_limit", [0, -1, 1.5, True])
def test_download_policy_rejects_invalid_or_non_positive_limit(invalid_limit):
    with pytest.raises(ValueError, match="positive integer"):
        AnpDownloadPolicy(max_asset_bytes=invalid_limit)


def test_client_accepts_asset_exactly_at_the_limit(tmp_path):
    content = _csv_bytes([_row()])

    def handler(request):
        return httpx.Response(
            200,
            headers={
                "content-type": "text/csv",
                "content-length": str(len(content)),
            },
            content=content,
            request=request,
        )

    client = AnpCsvClient(
        transport=httpx.MockTransport(handler),
        policy=AnpDownloadPolicy(max_asset_bytes=len(content)),
    )
    downloaded = client.download(
        source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
        official_page_url=ANP_OFFICIAL_PAGE_URL,
        download_url=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
        filename="exact-limit.csv",
        destination_directory=tmp_path,
    )
    assert downloaded.byte_length == len(content)
    assert downloaded.sha256 == hashlib.sha256(content).hexdigest()
    downloaded.path.unlink()


def test_client_rejects_content_length_above_limit_without_partial_file(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/csv", "content-length": "11"},
            content=b"x",
            request=request,
        )

    client = AnpCsvClient(
        transport=httpx.MockTransport(handler),
        policy=AnpDownloadPolicy(max_asset_bytes=10),
    )
    target = tmp_path / "announced-too-large.csv"
    with pytest.raises(
        ValueError,
        match="^ANP download exceeds the configured asset size limit$",
    ):
        client.download(
            source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
            official_page_url=ANP_OFFICIAL_PAGE_URL,
            download_url=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
            filename=target.name,
            destination_directory=tmp_path,
        )
    assert not target.exists()


def test_client_stops_headerless_stream_over_limit_and_removes_partial(tmp_path):
    class HeaderlessStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"12345678"
            yield SYNTHETIC_CNPJ.encode("ascii")

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            stream=HeaderlessStream(),
            request=request,
        )

    client = AnpCsvClient(
        transport=httpx.MockTransport(handler),
        policy=AnpDownloadPolicy(max_asset_bytes=10),
    )
    target = tmp_path / "stream-too-large.csv"
    with pytest.raises(ValueError) as raised:
        client.download(
            source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
            official_page_url=ANP_OFFICIAL_PAGE_URL,
            download_url=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
            filename=target.name,
            destination_directory=tmp_path,
        )
    assert str(raised.value) == "ANP download exceeds the configured asset size limit"
    assert SYNTHETIC_CNPJ not in str(raised.value)
    assert "www.gov.br" not in str(raised.value)
    assert not target.exists()


@pytest.mark.parametrize(
    ("content_type", "body", "message"),
    [
        ("text/html", b"<html></html>", "content type"),
        ("text/csv", b"<!doctype html><html></html>", "HTML"),
    ],
)
def test_client_rejects_disguised_html_without_leaving_partial(tmp_path, content_type, body, message):
    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=body, request=request)

    client = AnpCsvClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match=message):
        client.download(
            source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
            official_page_url=ANP_OFFICIAL_PAGE_URL,
            download_url=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
            filename="rejected.csv",
            destination_directory=tmp_path,
        )
    assert not (tmp_path / "rejected.csv").exists()


def test_client_rejects_redirect_outside_official_host(tmp_path):
    def handler(request):
        return httpx.Response(302, headers={"location": "https://example.invalid/data.csv"}, request=request)

    client = AnpCsvClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="allowlist"):
        client.download(
            source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE,
            official_page_url=ANP_OFFICIAL_PAGE_URL,
            download_url=ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
            filename="redirect.csv",
            destination_directory=tmp_path,
        )


def test_dry_run_does_not_resolve_network_database_or_file():
    class Explosive:
        def __getattribute__(self, _name):
            raise AssertionError("dry-run touched an external collaborator")

    result = run_anp_pipeline(
        None,
        AnpExecutionOptions(source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE, dry_run=True),
        client=Explosive(),
        parser=Explosive(),
    )
    assert result.status == "succeeded"
    assert result.pipeline_run_ids == ()


def test_missing_essential_product_blocks_pipeline_before_any_publication(tmp_path):
    class StaticClient:
        def download(self, *, filename, destination_directory, **_kwargs):
            content = _csv_bytes([_row(**{"Produto": "GASOLINA"})])
            return _asset(Path(destination_directory) / filename, content)

    class RecordingLoader:
        published = 0
        finished = []

        @contextmanager
        def source_lock(self, _source):
            yield

        def start_run(self, *_args):
            return uuid4()

        def persist_bronze(self, _run, parsed):
            return parsed, len(parsed.rows), 0

        def persist_silver(self, _run, observations, issues):
            return tuple(observations), len(observations), 0, tuple(issues)

        def publish_shadow(self, *_args, **_kwargs):
            self.published += 1
            return "must-not-exist", False

        def finish_run(self, _run, status, **_counts):
            self.finished.append(status)

    loader = RecordingLoader()
    with pytest.raises(ValueError, match="hard gates"):
        run_anp_pipeline(loader, AnpExecutionOptions(), client=StaticClient())
    assert loader.published == 0
    assert loader.finished == ["succeeded", "succeeded", "failed"]


def test_layout_drift_is_quarantined_without_silver_or_gold(tmp_path):
    class StaticClient:
        downloaded_path = None

        def download(self, *, filename, destination_directory, **_kwargs):
            content = _csv_bytes([_row()], header=ANP_EXPECTED_HEADER[:-1])
            path = Path(destination_directory) / filename
            path.write_bytes(content)
            self.downloaded_path = path
            return _asset(path, content)

    class FakeLoader:
        persisted = []
        finished = []

        @contextmanager
        def source_lock(self, _source):
            yield

        def start_run(self, *_args):
            return uuid4()

        def persist_bronze(self, _run, parsed):
            self.persisted.append(parsed)
            return parsed, 0, 0

        def finish_run(self, _run, status, **_counts):
            self.finished.append(status)

    client = StaticClient()
    loader = FakeLoader()
    with pytest.raises(ValueError, match="layout drift"):
        run_anp_pipeline(loader, AnpExecutionOptions(), client=client)
    assert len(loader.persisted) == 1
    assert loader.persisted[0].ingestion_status == "quarantined"
    assert loader.persisted[0].rows == ()
    assert loader.finished == ["failed"]
    assert client.downloaded_path is not None
    assert not client.downloaded_path.exists()


def test_loader_rejects_non_postgresql_engine():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(ValueError, match="PostgreSQL"):
            AnpFuelPriceLoader(engine)
    finally:
        engine.dispose()
