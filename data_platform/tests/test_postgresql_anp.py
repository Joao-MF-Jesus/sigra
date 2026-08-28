from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import io
from pathlib import Path

import pytest

from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()


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


def _content(price: str = "5,6789", *, include_prior_week: bool = False) -> bytes:
    from data_platform.anp.sources import ANP_EXPECTED_HEADER

    rows = []
    for index, (product, value, city) in enumerate(
        (("GASOLINA", price, "Cidade Alpha"),
         ("GASOLINA ADITIVADA", "6,1234", "Cidade Alpha"),
         ("ETANOL", "4,2345", "Cidade Beta")),
        start=1,
    ):
        rows.append({
            "Regiao - Sigla": "SE", "Estado - Sigla": "SP",
            "Municipio": city, "Revenda": f"Posto Sintético {index}",
            "CNPJ da Revenda": _check_digits(f"{index:012d}"),
            "Nome da Rua": "Rua de Teste", "Numero Rua": str(index),
            "Complemento": "", "Bairro": "Centro", "Cep": "00000-000",
            "Produto": product, "Data da Coleta": "04/08/2026",
            "Valor de Venda": value, "Valor de Compra": "",
            "Unidade de Medida": "R$ / litro", "Bandeira": "SINTÉTICA",
        })
    if include_prior_week:
        prior = dict(rows[0])
        prior.update({
            "Revenda": "Posto Sintético Anterior",
            "CNPJ da Revenda": _check_digits("000000000004"),
            "Data da Coleta": "28/07/2026",
            "Valor de Venda": "5,5000",
        })
        rows.append(prior)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=ANP_EXPECTED_HEADER, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


class _StaticClient:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def download(self, *, source_reference, official_page_url, download_url, filename, destination_directory):
        from data_platform.contracts.anp_fuel_prices import DownloadedAnpAsset

        path = Path(destination_directory) / filename
        path.write_bytes(self.content)
        return DownloadedAnpAsset(
            source_reference=source_reference,
            official_page_url=official_page_url,
            download_url_sanitized=download_url,
            filename=filename,
            path=path,
            collected_at=datetime(2026, 8, 11, tzinfo=UTC),
            http_status=200,
            content_type="text/csv",
            byte_length=len(self.content),
            etag=None,
            last_modified=None,
            sha256=hashlib.sha256(self.content).hexdigest(),
        )


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real local descartavel nao configurado")
def test_postgresql_anp_pipeline_idempotency_supersession_guards_and_downgrade(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import DBAPIError

    from data_platform.anp.loader import AnpFuelPriceLoader
    from data_platform.anp.pipeline import AnpExecutionOptions, run_anp_pipeline
    from data_platform.anp.sources import ANP_LAST_FOUR_WEEKS_REFERENCE

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("""UPDATE gold.anp_fuel_price_dataset
                SET status='retired',is_active_shadow=FALSE,retired_at=CURRENT_TIMESTAMP
                WHERE is_active_shadow"""))
        engine.dispose()
        command.downgrade(config, "20260810_0006")
        command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)
        loader = AnpFuelPriceLoader(engine)
        options = AnpExecutionOptions(source_reference=ANP_LAST_FOUR_WEEKS_REFERENCE)
        first = run_anp_pipeline(loader, options, client=_StaticClient(_content()))
        second = run_anp_pipeline(loader, options, client=_StaticClient(_content()))
        assert first.status == "succeeded"
        assert second.status == "deduplicated"
        assert first.dataset_version == second.dataset_version

        with engine.connect() as connection:
            counts = connection.execute(text("""SELECT
                (SELECT COUNT(*) FROM bronze.anp_source_asset) AS assets,
                (SELECT COUNT(*) FROM bronze.anp_fuel_price_raw) AS raw_rows,
                (SELECT COUNT(*) FROM silver.anp_fuel_price_observation) AS observations,
                (SELECT COUNT(*) FROM silver.anp_fuel_price_observation_current) AS current_observations,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_dataset) AS datasets,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_dataset WHERE is_active_shadow) AS active_datasets,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_snapshot) AS snapshots,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_quality_result WHERE status='not_calibrated') AS not_calibrated
            """)).mappings().one()
        assert counts["assets"] == 1
        assert counts["raw_rows"] == counts["observations"] == counts["current_observations"] == 3
        assert counts["datasets"] == counts["active_datasets"] == 1
        assert counts["snapshots"] > 0
        assert counts["not_calibrated"] == 7

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE bronze.anp_fuel_price_raw SET extraction_status='duplicate'"))

        with pytest.raises(ValueError, match="existing period"):
            run_anp_pipeline(loader, options, client=_StaticClient(_content("5,7000")))
        with engine.connect() as connection:
            asset_correction = connection.execute(text("""SELECT
                (SELECT COUNT(*) FROM bronze.anp_source_asset) AS assets,
                (SELECT COUNT(*) FROM silver.anp_fuel_price_observation) AS observations,
                (SELECT COUNT(*) FROM meta.data_quality_issue
                 WHERE rule_code='ANP_RETROACTIVE_ASSET_CORRECTION_REVIEW'
                   AND severity='critical' AND resolution_status='open') AS review_issues,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_dataset) AS datasets
            """)).mappings().one()
        assert asset_correction["assets"] == 2
        assert asset_correction["observations"] == 3
        assert asset_correction["review_issues"] == 1
        assert asset_correction["datasets"] == 1
        with engine.begin() as connection:
            connection.execute(text("""UPDATE meta.data_quality_issue
                SET resolution_status='accepted',resolved_at=CURRENT_TIMESTAMP
                WHERE rule_code='ANP_RETROACTIVE_ASSET_CORRECTION_REVIEW'
                  AND resolution_status='open'"""))

        with pytest.raises(ValueError, match="hard gates"):
            run_anp_pipeline(
                loader,
                options,
                client=_StaticClient(_content("5,7000", include_prior_week=True)),
            )
        with engine.connect() as connection:
            after_correction = connection.execute(text("""SELECT
                (SELECT COUNT(*) FROM silver.anp_fuel_price_observation) AS observations,
                (SELECT COUNT(*) FROM silver.anp_fuel_price_observation_current) AS current_observations,
                (SELECT COUNT(*) FROM meta.data_quality_issue
                 WHERE rule_code='ANP_RETROACTIVE_CORRECTION_REVIEW'
                   AND severity='critical' AND resolution_status='open') AS review_issues,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_dataset) AS datasets,
                (SELECT COUNT(*) FROM gold.anp_fuel_price_dataset WHERE is_active_shadow) AS active_datasets
            """)).mappings().one()
        assert after_correction["observations"] == 5
        assert after_correction["current_observations"] == 4
        assert after_correction["review_issues"] == 1
        assert after_correction["datasets"] == after_correction["active_datasets"] == 1

        with engine.begin() as connection:
            connection.execute(text("""UPDATE gold.anp_fuel_price_dataset
                SET status='retired',is_active_shadow=FALSE,retired_at=CURRENT_TIMESTAMP
                WHERE is_active_shadow"""))
        engine.dispose()
        command.downgrade(config, "20260810_0006")
        engine = create_engine(POSTGRESQL_URL)
        db = inspect(engine)
        assert "anp_source_asset" not in db.get_table_names(schema="bronze")
        assert "anp_fuel_price_observation" not in db.get_table_names(schema="silver")
        assert "anp_fuel_price_dataset" not in db.get_table_names(schema="gold")
    finally:
        engine.dispose()
        command.upgrade(config, "head")
