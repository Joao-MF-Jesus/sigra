from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_platform_engine(database_url: str) -> Engine:
    if not database_url:
        raise ValueError("DATA_PLATFORM_DATABASE_URL e obrigatoria fora do dry-run")
    engine = create_engine(database_url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise ValueError("A plataforma de dados exige PostgreSQL")
    return engine
