from __future__ import annotations

import hashlib
import json


ANP_OFFICIAL_PAGE_URL = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "serie-historica-de-precos-de-combustiveis"
)
ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "arquivos/shpc/qus/ultimas-4-semanas-gasolina-etanol.csv"
)
ANP_LAST_FOUR_WEEKS_REFERENCE = "anp-last-four-weeks-gasoline-ethanol"
ANP_LAST_FOUR_WEEKS_FILENAME = "ultimas-4-semanas-gasolina-etanol.csv"
ANP_ALLOWED_HOSTS = frozenset({"www.gov.br"})
ANP_EXPECTED_HEADER = (
    "Regiao - Sigla",
    "Estado - Sigla",
    "Municipio",
    "Revenda",
    "CNPJ da Revenda",
    "Nome da Rua",
    "Numero Rua",
    "Complemento",
    "Bairro",
    "Cep",
    "Produto",
    "Data da Coleta",
    "Valor de Venda",
    "Valor de Compra",
    "Unidade de Medida",
    "Bandeira",
)


def layout_fingerprint(header: tuple[str, ...]) -> str:
    encoded = json.dumps(
        {"delimiter": ";", "header": header},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


ANP_EXPECTED_LAYOUT_FINGERPRINT = layout_fingerprint(ANP_EXPECTED_HEADER)


def resolve_source(source_reference: str) -> tuple[str, str, str]:
    if source_reference != ANP_LAST_FOUR_WEEKS_REFERENCE:
        raise ValueError("unknown ANP source reference")
    return (
        ANP_OFFICIAL_PAGE_URL,
        ANP_LAST_FOUR_WEEKS_DOWNLOAD_URL,
        ANP_LAST_FOUR_WEEKS_FILENAME,
    )
