# PostgreSQL local

## Requisitos

- Python 3.12 e dependencias de `backend/requirements.txt`;
- PostgreSQL 16 ou superior;
- role local com acesso aos bancos usados;
- credencial fornecida por variavel de ambiente ou `pgpass`, nunca versionada.

A baseline local foi validada em PostgreSQL 18 com:

- `sigra_dev`: desenvolvimento e upgrade Alembic;
- `sigra_integration`: importacao e testes de integracao;
- `sigra_migration_test`: ciclo destrutivo de migrations.

## Configuracao segura

Use somente a sessao atual. O exemplo omite a senha porque o cliente pode
resolve-la pelo `pgpass`:

```powershell
$env:DATABASE_ENV="integration"
$env:DATABASE_URL="postgresql+psycopg://sigra@127.0.0.1:5432/sigra_integration"
$env:TEST_POSTGRESQL_URL=$env:DATABASE_URL
$env:SIGRA_RUN_POSTGRES_TESTS="1"
```

Nunca imprima a URL quando ela contiver senha. Os scripts oficiais sanitizam a
URL nos relatorios.

## Schema

O PostgreSQL nao usa `create_all` nem seeds no startup:

```powershell
.\.venv-validation\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv-validation\Scripts\python.exe scripts\check_migration_status.py
```

Execute downgrade somente no banco descartavel:

```powershell
$env:DATABASE_URL="postgresql+psycopg://sigra@127.0.0.1:5432/sigra_migration_test"
.\.venv-validation\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv-validation\Scripts\python.exe -m alembic -c backend/alembic.ini downgrade base
.\.venv-validation\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

## Testes de integracao

Mantenha `DATABASE_URL` e `DATABASE_ENV` fora da suite comum; os testes
PostgreSQL usam `TEST_POSTGRESQL_URL` de forma dedicada:

```powershell
$env:TEST_POSTGRESQL_URL="postgresql+psycopg://sigra@127.0.0.1:5432/sigra_integration"
$env:SIGRA_RUN_POSTGRES_TESTS="1"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_ENV -ErrorAction SilentlyContinue
.\.venv-validation\Scripts\python.exe -m unittest discover -s backend/tests -t backend -v
```

Sem `SIGRA_RUN_POSTGRES_TESTS=1` e `TEST_POSTGRESQL_URL`, os oito casos de
integracao aparecem como `skipped`; isso nao equivale a PostgreSQL aprovado.
