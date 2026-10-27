"""Operator-only bootstrap: interactive password, existing migrated database only."""
import argparse
from getpass import getpass

from sqlalchemy import func, or_

from app import models
from app.auth import Registration, hash_password
from app.database import EXPECTED_ALEMBIC_HEAD, SessionLocal, current_migration_revision, engine


def main():
    parser = argparse.ArgumentParser(description="Provisionar administrador local sem senha em argumentos/arquivos")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--confirm-admin", action="store_true", required=True)
    args = parser.parse_args()
    if current_migration_revision(engine) != EXPECTED_ALEMBIC_HEAD:
        raise SystemExit("ADMIN_PROVISIONING_BLOCKED: migration pendente; nenhuma migration foi executada")
    password = getpass("Senha do administrador (mínimo 12 caracteres): ")
    confirmation = getpass("Confirme a senha: ")
    if password != confirmation:
        raise SystemExit("ADMIN_PROVISIONING_BLOCKED: senhas diferentes")
    try:
        validated = Registration(name=args.name, email=args.email, password=password)
    except ValueError:
        raise SystemExit("ADMIN_PROVISIONING_BLOCKED: nome, e-mail ou senha inválidos") from None
    with SessionLocal() as db:
        if db.query(models.User).filter(or_(models.User.normalized_email == validated.email,
                func.lower(func.trim(models.User.email)) == validated.email)).first():
            raise SystemExit("ADMIN_PROVISIONING_BLOCKED: e-mail já cadastrado; conta preservada")
        db.add(models.User(name=validated.name, email=validated.email, normalized_email=validated.email,
                           password_hash=hash_password(password), role="admin"))
        db.commit()
    print("ADMIN_PROVISIONED")


if __name__ == "__main__":
    main()
