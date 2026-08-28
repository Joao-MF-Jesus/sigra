from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = (
    PROJECT_ROOT / "dist" / "validation" / "homologation-smoke-report.json"
)
SENSITIVE_RESPONSE_MARKERS = (
    "postgresql://",
    "postgresql+psycopg://",
    "database_url",
    '"password":',
    '"token":',
    "service_role",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_public_url(value: str, label: str, *, require_https: bool = True) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{label} nao e uma URL absoluta.")
    if require_https and parsed.scheme != "https":
        raise ValueError(f"{label} deve usar HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} nao pode conter credenciais.")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} nao pode conter query string ou fragmento.")
    return value.rstrip("/")


def contains_sensitive_response_data(raw_body: str) -> list[str]:
    normalized = raw_body.casefold()
    return [
        marker
        for marker in SENSITIVE_RESPONSE_MARKERS
        if marker in normalized
    ]


def http_request(
    method: str,
    url: str,
    *,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 20,
) -> dict:
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "SIGRA-Homologation-Smoke/1.0",
        **(headers or {}),
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            raw_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        status = error.code
        response_headers = dict(error.headers.items())
        raw_body = error.read().decode("utf-8", errors="replace")
    except URLError as error:
        raise ConnectionError(f"Falha ao acessar {url}: {error.reason}") from error
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        data = None
    return {
        "status": status,
        "headers": {
            key.casefold(): value
            for key, value in response_headers.items()
        },
        "body": data,
        "raw_body": raw_body,
        "duration_ms": duration_ms,
        "sensitive_markers": contains_sensitive_response_data(raw_body),
    }


def run_check(
    name: str,
    method: str,
    url: str,
    *,
    expected_status: int,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    validate=None,
) -> dict:
    try:
        response = http_request(
            method,
            url,
            payload=payload,
            headers=headers,
        )
        errors = []
        if response["status"] != expected_status:
            errors.append(
                f"HTTP esperado {expected_status}; recebido {response['status']}."
            )
        if response["sensitive_markers"]:
            errors.append(
                "A resposta contem marcadores de informacao sensivel: "
                + ", ".join(response["sensitive_markers"])
            )
        if validate is not None:
            errors.extend(validate(response) or [])
        return {
            "name": name,
            "method": method,
            "url": url,
            "expected_status": expected_status,
            "actual_status": response["status"],
            "duration_ms": response["duration_ms"],
            "status": "passed" if not errors else "failed",
            "errors": errors,
        }
    except Exception as error:
        return {
            "name": name,
            "method": method,
            "url": url,
            "expected_status": expected_status,
            "actual_status": None,
            "duration_ms": None,
            "status": "failed",
            "errors": [str(error)],
        }


def validate_health(response: dict) -> list[str]:
    body = response["body"] if isinstance(response["body"], dict) else {}
    errors = []
    if body.get("status") != "ok":
        errors.append("Health nao retornou status ok.")
    if body.get("public_demo_mode") is not True:
        errors.append("PUBLIC_DEMO_MODE nao esta ativo.")
    database = body.get("database") or {}
    if database.get("reachable") is not True:
        errors.append("Banco remoto nao esta acessivel.")
    if database.get("migration_up_to_date") is not True:
        errors.append("Banco remoto nao esta no Alembic head.")
    return errors


def validate_database_health(response: dict) -> list[str]:
    body = response["body"] if isinstance(response["body"], dict) else {}
    database = body.get("database") or {}
    return (
        []
        if (
            body.get("status") == "ok"
            and database.get("reachable") is True
            and database.get("migration_up_to_date") is True
        )
        else ["Health do banco nao confirmou conexao e migration."]
    )


def validate_nonempty_collection(response: dict) -> list[str]:
    body = response["body"]
    if isinstance(body, list) and body:
        return []
    if isinstance(body, dict):
        collection = body.get("motorcycles") or body.get("vehicles")
        if isinstance(collection, list) and collection:
            return []
    return ["O catalogo retornou uma colecao vazia ou invalida."]


def validate_nonempty_recommendation(response: dict) -> list[str]:
    body = response["body"]
    if isinstance(body, list) and body:
        return []
    if isinstance(body, dict) and isinstance(body.get("recommendations"), list):
        return [] if body["recommendations"] else ["O ranking retornou vazio."]
    return ["O contrato da recomendacao nao foi reconhecido."]


def validate_financing(response: dict) -> list[str]:
    body = response["body"] if isinstance(response["body"], dict) else {}
    return (
        []
        if body.get("regular_installment") is not None
        else ["A simulacao nao retornou a parcela regular."]
    )


def validate_motorcycle_unavailable(response: dict) -> list[str]:
    body = response["body"] if isinstance(response["body"], dict) else {}
    if body.get("algorithm_version") is not None or body.get("weights_version") is not None:
        return ["O endpoint reservado de motos anunciou algoritmo ou pesos inexistentes."]
    return []


def validate_write_block(response: dict) -> list[str]:
    body = response["body"] if isinstance(response["body"], dict) else {}
    detail = body.get("detail") if isinstance(body, dict) else {}
    return (
        []
        if isinstance(detail, dict) and detail.get("code") == "demo_read_only"
        else ["A escrita nao retornou o bloqueio demo_read_only."]
    )


def validate_untrusted_cors(response: dict) -> list[str]:
    allowed_origin = response["headers"].get("access-control-allow-origin")
    return (
        []
        if allowed_origin is None
        else ["Uma origem nao autorizada recebeu Access-Control-Allow-Origin."]
    )


def smoke_checks(
    backend_url: str,
    frontend_url: str,
    *,
    require_https: bool = True,
) -> dict:
    backend_url = validate_public_url(
        backend_url,
        "SIGRA_BACKEND_URL",
        require_https=require_https,
    )
    frontend_url = validate_public_url(
        frontend_url,
        "SIGRA_FRONTEND_URL",
        require_https=require_https,
    )
    checks = [
        run_check(
            "frontend",
            "GET",
            frontend_url,
            expected_status=200,
            validate=lambda response: (
                []
                if "SIGRA" in response["raw_body"]
                else ["A pagina inicial nao contem a identificacao SIGRA."]
            ),
        ),
        run_check(
            "health",
            "GET",
            f"{backend_url}/health",
            expected_status=200,
            validate=validate_health,
        ),
        run_check(
            "database",
            "GET",
            f"{backend_url}/health/database",
            expected_status=200,
            validate=validate_database_health,
        ),
        run_check(
            "vehicles",
            "GET",
            f"{backend_url}/vehicles",
            expected_status=200,
            validate=validate_nonempty_collection,
        ),
        run_check(
            "motorcycles",
            "GET",
            f"{backend_url}/motorcycles",
            expected_status=200,
            validate=validate_nonempty_collection,
        ),
        run_check(
            "recommendation",
            "POST",
            f"{backend_url}/recommendations",
            expected_status=200,
            payload={
                "budget": 200000,
                "monthly_limit": 3500,
                "use_case": "cidade",
                "monthly_mileage": 1000,
                "fuel_price": 6,
                "recommendation_strategy": "best_within_budget",
            },
            validate=validate_nonempty_recommendation,
        ),
        run_check(
            "financing",
            "POST",
            f"{backend_url}/financing/simulate",
            expected_status=200,
            payload={
                "vehicle_type": "car",
                "vehicle_price": 30000,
                "down_payment": 10000,
                "term_months": 36,
                "monthly_interest_rate_percent": 1.8,
                "upfront_fees": 300,
                "financed_fees": 500,
                "financed_insurance": 100,
                "financed_services": 50,
                "desired_max_installment": 1000,
                "available_monthly_budget": 1800,
                "estimated_monthly_vehicle_cost": 620,
            },
            validate=validate_financing,
        ),
        run_check(
            "motorcycle_recommendation_reserved",
            "POST",
            f"{backend_url}/motorcycles/recommendations",
            expected_status=501,
            validate=validate_motorcycle_unavailable,
        ),
        run_check(
            "persistent_write_blocked",
            "POST",
            f"{backend_url}/users",
            expected_status=403,
            payload={
                "name": "Teste descartavel",
                "email": "blocked@example.test",
            },
            validate=validate_write_block,
        ),
        run_check(
            "untrusted_cors",
            "GET",
            f"{backend_url}/health",
            expected_status=200,
            headers={"Origin": "https://unauthorized.invalid"},
            validate=validate_untrusted_cors,
        ),
    ]
    durations = [
        check["duration_ms"]
        for check in checks
        if check["duration_ms"] is not None
    ]
    failures = [check for check in checks if check["status"] != "passed"]
    return {
        "status": "passed" if not failures else "failed",
        "generated_at": utc_timestamp(),
        "backend_url": backend_url,
        "frontend_url": frontend_url,
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failures),
        "checks_failed": len(failures),
        "response_time_ms": {
            "maximum": max(durations) if durations else None,
            "average": (
                round(sum(durations) / len(durations), 2)
                if durations
                else None
            ),
        },
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa validacoes seguras na homologacao publicada."
    )
    parser.add_argument(
        "--backend-url",
        default=os.getenv("SIGRA_BACKEND_URL"),
    )
    parser.add_argument(
        "--frontend-url",
        default=os.getenv("SIGRA_FRONTEND_URL"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.backend_url or not args.frontend_url:
        raise SystemExit(
            "Defina SIGRA_BACKEND_URL e SIGRA_FRONTEND_URL ou use os argumentos equivalentes."
        )
    try:
        report = smoke_checks(args.backend_url, args.frontend_url)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
