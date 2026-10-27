"""Isolated password-policy regression: synthetic fixtures, no database imports."""
import ast
import hashlib
import hmac
from pathlib import Path
import re
import secrets
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


AUTH_SOURCE = Path(__file__).resolve().parents[1] / "app" / "auth.py"
SYNTHETIC_PASSWORD = "OldPass8"


@pytest.fixture
def isolated_auth():
    """Load actual schema/KDF/login definitions without app.database or startup."""
    parsed = ast.parse(AUTH_SOURCE.read_text(encoding="utf-8"))
    names = {
        "Credentials", "Registration", "normalize_email", "hash_password",
        "verify_password", "require_csrf", "_storage_blocked", "login",
        "user_response", "require_admin",
    }
    selected = []
    for node in parsed.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            if node.name in {"login", "require_admin"}:
                node.decorator_list = []
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PASSWORD_ITERATIONS"
            for target in node.targets
        ):
            selected.append(node)
    assert len(selected) == len(names) + 1
    fake_user_model = type("SyntheticUserModel", (), {"normalized_email": "synthetic"})
    session_calls = []
    namespace = {
        "__name__": "isolated_auth_password_policy",
        "BaseModel": BaseModel, "ConfigDict": ConfigDict, "Field": Field,
        "SecretStr": SecretStr, "field_validator": field_validator,
        "hashlib": hashlib, "hmac": hmac, "re": re, "secrets": secrets,
        "Depends": Depends, "HTTPException": HTTPException,
        "Request": Request, "Response": Response, "Session": Session,
        "SQLAlchemyError": SQLAlchemyError,
        "models": SimpleNamespace(User=fake_user_model),
        "get_db": lambda: None, "current_user": lambda: None,
        "cors_allowed_origins": lambda: ["http://testserver"],
        "require_homologation_account": lambda email: None,
        "_limit_attempts": lambda request: None,
        "_set_session": lambda db, user, response: session_calls.append(user),
    }
    tree = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(tree, str(AUTH_SOURCE), "exec"), namespace)
    return SimpleNamespace(**namespace, session_calls=session_calls)


def test_login_accepts_existing_eight_character_password(isolated_auth):
    credentials = isolated_auth.Credentials(email=" Legacy@EXAMPLE.TEST ", password=SYNTHETIC_PASSWORD)
    assert credentials.email == "legacy@example.test"
    assert credentials.password.get_secret_value() == SYNTHETIC_PASSWORD
    assert SYNTHETIC_PASSWORD not in repr(credentials)


@pytest.mark.parametrize("password", ["", "x" * 257])
def test_login_rejects_empty_or_overlong_password(isolated_auth, password):
    with pytest.raises(ValidationError):
        isolated_auth.Credentials(email="legacy@example.test", password=password)


@pytest.mark.parametrize("password", ["", SYNTHETIC_PASSWORD, "x" * 11, "x" * 257])
def test_registration_keeps_new_password_policy(isolated_auth, password):
    with pytest.raises(ValidationError):
        isolated_auth.Registration(name="Synthetic participant", email="new@example.test", password=password)


def test_registration_accepts_twelve_characters_but_not_client_role(isolated_auth):
    payload = {"name": "Synthetic participant", "email": "new@example.test", "password": "x" * 12}
    assert len(isolated_auth.Registration(**payload).password.get_secret_value()) == 12
    with pytest.raises(ValidationError):
        isolated_auth.Registration(**payload, role="admin")
    with pytest.raises(ValidationError):
        isolated_auth.Credentials(email=payload["email"], password=SYNTHETIC_PASSWORD, role="admin")


def test_real_hash_verification_is_unchanged_for_short_existing_password(isolated_auth):
    encoded = isolated_auth.hash_password(SYNTHETIC_PASSWORD)
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert isolated_auth.verify_password(SYNTHETIC_PASSWORD, encoded)
    assert not isolated_auth.verify_password("WrongPw8", encoded)
    assert not isolated_auth.verify_password(SYNTHETIC_PASSWORD, None)


@pytest.mark.parametrize("password, expected_status", [(SYNTHETIC_PASSWORD, 200), ("WrongPw8", 401)])
def test_actual_login_handler_verifies_password_after_http_validation(isolated_auth, password, expected_status):
    user = SimpleNamespace(
        id=1, name="Synthetic participant", email="legacy@example.test", role="participant",
        password_hash=isolated_auth.hash_password(SYNTHETIC_PASSWORD),
    )
    fake_query = SimpleNamespace(first=lambda: user)
    fake_query.filter = lambda expression: fake_query
    fake_db = SimpleNamespace(query=lambda model: fake_query)
    app = FastAPI()
    app.add_api_route("/auth/login", isolated_auth.login, methods=["POST"])
    app.dependency_overrides[isolated_auth.get_db] = lambda: fake_db
    with TestClient(app) as client:
        response = client.post("/auth/login", headers={"X-SIGRA-CSRF": "1"}, json={
            "email": user.email, "password": password,
        })
    assert response.status_code == expected_status
    assert len(isolated_auth.session_calls) == (1 if expected_status == 200 else 0)
    if expected_status == 200:
        assert response.json()["role"] == "participant"


def test_login_still_requires_csrf_header(isolated_auth):
    app = FastAPI()
    app.add_api_route("/auth/login", isolated_auth.login, methods=["POST"])
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": "legacy@example.test", "password": SYNTHETIC_PASSWORD})
    assert response.status_code == 403
    assert not isolated_auth.session_calls


def test_participant_still_cannot_access_admin_permissions(isolated_auth):
    with pytest.raises(HTTPException) as failure:
        isolated_auth.require_admin(SimpleNamespace(role="participant"))
    assert failure.value.status_code == 403
    admin = SimpleNamespace(role="admin")
    assert isolated_auth.require_admin(admin) is admin


def test_openapi_separates_login_and_registration_minimum(isolated_auth):
    assert isolated_auth.Credentials.model_json_schema()["properties"]["password"]["minLength"] == 1
    assert isolated_auth.Registration.model_json_schema()["properties"]["password"]["minLength"] == 12
