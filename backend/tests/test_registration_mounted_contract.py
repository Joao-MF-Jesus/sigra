"""Real auth routes under the publication mount, disposable local DB only."""
import json
import secrets
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import auth, main, models, deployment
from backend.tests.test_participant_trials import storage


@pytest.fixture
def mounted(storage, monkeypatch):
    # No publication factory/remote identity is fabricated. These local tests
    # exercise the unchanged fictitious-account rule with an explicit test seam.
    monkeypatch.setattr(deployment, "enabled", lambda values=None: True)
    monkeypatch.setattr(deployment, "settings", lambda values=None: SimpleNamespace(real_collection=False))
    monkeypatch.setenv("SIGRA_COOKIE_SECURE", "true")
    def client(prefix="/sigra-api"):
        application = main.app
        if prefix:
            application = FastAPI()
            application.mount(prefix, main.app)
        # No lifespan: no factory startup, migration or existing DB contact.
        return TestClient(application, base_url="https://preview.example.invalid", headers={"X-SIGRA-CSRF": "1"})
    return storage, client


def payload():
    return {"name": "Participante sintético", "email": "local@example.invalid", "password": secrets.token_urlsafe(24)}


def post(client, path, value):
    return client.post(path, content=json.dumps(value, ensure_ascii=True).encode("ascii"),
                       headers={"Content-Type": "application/json"})


@pytest.mark.parametrize("prefix", ["", "/sigra-api", "/gateway/sigra-api"])
@pytest.mark.parametrize("field,value", [
    ("password", "x" * 11), ("password", "x" * 257), ("email", "invalid"),
    ("name", " X "), ("name", "A\nB"), ("role", "admin"),
])
def test_expected_validation_is_422_and_never_echoes_input_or_context(mounted, prefix, field, value):
    engine, clients = mounted
    data = {**payload(), field: value}
    response = post(clients(prefix), prefix + "/auth/register", data)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", field] for error in errors)
    assert all(set(error) == {"type", "loc", "msg"} for error in errors)
    assert data["password"] not in response.text
    with Session(engine) as db:
        assert db.query(models.User).count() == db.query(models.AuthSession).count() == 0


@pytest.mark.parametrize("prefix", ["", "/sigra-api"])
@pytest.mark.parametrize("field", ["email", "password", "name"])
def test_unencodable_json_scalar_is_rejected_before_hash_or_database(mounted, monkeypatch, prefix, field):
    engine, clients = mounted
    def must_not_hash(value):
        pytest.fail("Invalid text reached the password KDF")
    monkeypatch.setattr(auth, "hash_password", must_not_hash)
    data = payload()
    data[field] = data[field] + "\ud800"
    response = post(clients(prefix), prefix + "/auth/register", data)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert all(set(error) == {"type", "loc", "msg"} for error in response.json()["detail"])
    assert data["password"] not in response.text
    with Session(engine) as db:
        assert db.query(models.User).count() == 0


@pytest.mark.parametrize("password_length", [12, 256])
def test_valid_registration_duplicate_login_and_normal_secure_session(mounted, password_length):
    engine, clients = mounted
    client = clients()
    data = {**payload(), "password": "s" * password_length}
    created = post(client, "/sigra-api/auth/register", data)
    assert created.status_code == 201
    assert created.json()["role"] == "participant"
    assert set(created.json()) == {"id", "name", "email", "role"}
    duplicate = post(client, "/sigra-api/auth/register", {**data, "email": " LOCAL@EXAMPLE.INVALID "})
    assert duplicate.status_code == 409
    assert data["password"] not in duplicate.text
    with Session(engine) as db:
        row = db.query(models.User).one()
        assert row.role == "participant"
        original_hash = row.password_hash
        assert auth.verify_password(data["password"], original_hash)
    login = post(client, "/sigra-api/auth/login", {key: data[key] for key in ("email", "password")})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=lax"))
    assert client.get("/sigra-api/auth/session").json()["user"]["id"] == created.json()["id"]
    assert client.get("/sigra-api/api/v1/admin/test-runs.csv").status_code == 403
    with Session(engine) as db:
        assert db.query(models.User).one().password_hash == original_hash
        assert db.query(models.AuthSession).count() == 1


def test_storage_failure_is_sanitized_503_and_rolls_back(mounted, monkeypatch):
    engine, clients = mounted
    def broken_commit(self):
        raise SQLAlchemyError("synthetic storage failure")
    monkeypatch.setattr(Session, "commit", broken_commit)
    response = post(clients(), "/sigra-api/auth/register", payload())
    assert response.status_code == 503
    assert "synthetic storage failure" not in response.text
    with Session(engine) as db:
        assert db.query(models.User).count() == 0


def test_valid_unicode_password_is_not_normalized_or_rejected(mounted):
    engine, clients = mounted
    data = {**payload(), "password": "Áα🙂" * 4}
    assert len(data["password"]) == 12
    client = clients()
    assert post(client, "/sigra-api/auth/register", data).status_code == 201
    with Session(engine) as db:
        encoded = db.query(models.User).one().password_hash
        assert auth.verify_password(data["password"], encoded)
        assert not auth.verify_password(data["password"].casefold(), encoded)
    assert post(client, "/sigra-api/auth/login", {k:data[k] for k in ("email", "password")}).status_code == 200


def test_fictitious_domain_csrf_and_client_privileges_remain_blocked(mounted):
    engine, clients = mounted
    client = clients()
    real_domain = post(client, "/sigra-api/auth/register", {**payload(), "email": "fictional@example.com"})
    assert real_domain.status_code == 403
    csrf = client.post("/sigra-api/auth/register", headers={"X-SIGRA-CSRF": "0"}, json=payload())
    assert csrf.status_code == 403
    assert post(client, "/sigra-api/auth/register", {**payload(), "role": "admin"}).status_code == 422
    with Session(engine) as db:
        assert db.query(models.User).count() == 0
