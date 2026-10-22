"""Database-backed opaque sessions; no demo credentials or client-selected roles."""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import models
from app.config import cors_allowed_origins
from app.database import get_db

router = APIRouter(prefix="/auth", tags=["participant-auth"])
COOKIE_NAME = "sigra_session"
PASSWORD_ITERATIONS = 600_000
SESSION_SECONDS = 8 * 60 * 60
_attempts = OrderedDict()
_attempt_lock = Lock()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(32)
    value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${value.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        algorithm, rounds, salt, expected = (encoded or "").split("$")
        if algorithm != "pbkdf2_sha256" or int(rounds) != PASSWORD_ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def normalize_email(value: str) -> str:
    value = value.strip().casefold()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) or len(value) > 160:
        raise ValueError("Informe um e-mail válido")
    return value


def require_homologation_account(email=None):
    """The inactive Revision6 is restricted to fictitious reserved-domain accounts."""
    from app import deployment
    if deployment.enabled():
        return deployment.require_account(email)
    from app.academic_cohort.revision6_homologation import enabled, require_runtime
    if not enabled():
        return
    try:
        require_runtime()
    except ValueError:
        raise HTTPException(503, "Destino exclusivo de homologação Revision6 não confirmado") from None
    if email is not None and not email.casefold().endswith((".test", ".invalid")):
        raise HTTPException(403, "Homologação: use somente uma conta fictícia .test ou .invalid")


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=5, max_length=180)
    password: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def email_normalization(cls, value):
        return normalize_email(value)


class Registration(Credentials):
    password: SecretStr = Field(min_length=12, max_length=256)
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if len(value) < 2 or any(ord(char) < 32 for char in value):
            raise ValueError("Informe seu nome")
        return value


def user_response(user: models.User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def _storage_blocked():
    return HTTPException(503, "Persistência de participantes indisponível. A migration precisa ser aplicada pelo responsável.")


def require_csrf(request: Request):
    # Custom header prevents cross-site simple form requests; CORS allows only explicit origins.
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("X-SIGRA-CSRF") != "1":
        raise HTTPException(403, "Origem da operação não confirmada")
    origin = request.headers.get("origin")
    host_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin not in {*cors_allowed_origins(), host_origin}:
        raise HTTPException(403, "Origem da operação não autorizada")


def _limit_attempts(request: Request):
    # Bounded, per-worker protection. Never store password, email or forwarded headers.
    key = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
    now = monotonic()
    with _attempt_lock:
        window, count = _attempts.get(key, (now, 0))
        if now - window >= 60:
            window, count = now, 0
        _attempts[key] = (window, count + 1)
        _attempts.move_to_end(key)
        while len(_attempts) > 2048:
            _attempts.popitem(last=False)
        if count >= 30:
            raise HTTPException(429, "Muitas tentativas. Aguarde um minuto.")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    require_homologation_account()  # Validate the destination before the first DB read.
    token = request.cookies.get(COOKIE_NAME, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(401, "Entre para acessar seus registros")
    try:
        session = db.get(models.AuthSession, _digest(token))
        now = datetime.now(timezone.utc)
        expires = session.expires_at.replace(tzinfo=timezone.utc) if session and session.expires_at.tzinfo is None else session.expires_at if session else None
        if session is None or session.revoked_at is not None or expires <= now:
            raise HTTPException(401, "Sessão encerrada ou expirada")
        user = db.get(models.User, session.user_id)
    except SQLAlchemyError:
        raise _storage_blocked() from None
    if user is None or not user.password_hash or user.role not in {"participant", "admin"}:
        raise HTTPException(401, "Sessão inválida")
    require_homologation_account(user.email)
    require_csrf(request)
    return user


def require_admin(user: models.User = Depends(current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(403, "Acesso reservado ao administrador")
    return user


def assert_owner(user: models.User, owner_id: int):
    if user.id != owner_id:
        raise HTTPException(403, "Acesso restrito aos seus próprios registros")


def cookie_options():
    secure = os.getenv("SIGRA_COOKIE_SECURE", "true").casefold() == "true"
    same_site = os.getenv("SIGRA_COOKIE_SAMESITE", "lax").casefold()
    if same_site not in {"lax", "strict", "none"} or (same_site == "none" and not secure):
        raise HTTPException(503, "Configuração segura de cookie inválida")
    return {"secure": secure, "samesite": same_site, "httponly": True, "path": "/"}


def _set_session(db: Session, user: models.User, response: Response):
    options = cookie_options()
    token = secrets.token_urlsafe(32)
    session = models.AuthSession(token_digest=_digest(token), user_id=user.id,
                                 expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS))
    db.add(session)
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, **options)
    response.headers["Cache-Control"] = "no-store"


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request, db: Session = Depends(get_db)):
    require_csrf(request)
    _limit_attempts(request)
    require_homologation_account(payload.email)
    try:
        existing = db.query(models.User).filter(or_(models.User.normalized_email == payload.email,
            func.lower(func.trim(models.User.email)) == payload.email)).first()
        if existing:
            raise HTTPException(409, "Este e-mail já está cadastrado")
        user = models.User(name=payload.name, email=payload.email, normalized_email=payload.email,
                           password_hash=hash_password(payload.password.get_secret_value()), role="participant")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user_response(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Este e-mail já está cadastrado") from None
    except SQLAlchemyError:
        db.rollback()
        raise _storage_blocked() from None


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    require_csrf(request)
    _limit_attempts(request)
    require_homologation_account(payload.email)
    try:
        user = db.query(models.User).filter(models.User.normalized_email == payload.email).first()
        encoded = user.password_hash if user else None
        # A missing account takes the same password KDF work as an incorrect password.
        if not encoded:
            hash_password(payload.password.get_secret_value())
        if not user or not verify_password(payload.password.get_secret_value(), encoded):
            raise HTTPException(401, "E-mail ou senha incorretos")
        _set_session(db, user, response)
        return user_response(user)
    except SQLAlchemyError:
        db.rollback()
        raise _storage_blocked() from None


@router.get("/me")
def me(response: Response, user: models.User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user_response(user)


@router.get("/session")
def session_status(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if not request.cookies.get(COOKIE_NAME):
        return {"user": None}
    try:
        return {"user": user_response(current_user(request, db))}
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return {"user": None}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    require_homologation_account()
    require_csrf(request)
    options = cookie_options()
    token = request.cookies.get(COOKIE_NAME, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        try:
            session = db.get(models.AuthSession, _digest(token))
            if session:
                session.revoked_at = datetime.now(timezone.utc)
                db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise _storage_blocked() from None
    response.delete_cookie(COOKIE_NAME, **options)
    response.headers["Cache-Control"] = "no-store"
