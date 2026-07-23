# Migracao SQLite para PostgreSQL

## Contratos

- fonte: somente `backend/sigra.db`;
- destino: PostgreSQL com migration Alembic em `head`;
- formato intermediario: `sqlite-export-v1`;
- schema: `1.0.0`;
- dinheiro: `Decimal`, serializado com tag `$type: decimal`;
- importacao: dry-run por padrao e transacao unica;
- seeds, scores e rankings nao sao recalculados.

## 1. Diagnostico

```powershell
python scripts/check_database_configuration.py
python scripts/clean_workspace.py --dry-run
python scripts/clean_workspace.py --dry-run --include-legacy-databases
```

O banco legado da raiz nunca e removido no modo padrao. A remocao exige
`--confirm --include-legacy-databases`, cria backup com SHA-256 quando o arquivo
nao esta vazio e nunca alcança o banco canonico.

## 2. Exportacao

```powershell
python scripts/export_sqlite_data.py --overwrite
python scripts/validate_database_export.py dist/data-migration/sqlite-export-v1
```

O diretorio contem `manifest.json`, um JSONL por tabela, checksums e relatorios.
Exports reais ficam fora das releases.

## 3. Preparacao do destino

```powershell
$env:DATABASE_ENV="integration"
$env:DATABASE_URL="postgresql+psycopg:///sigra"
$env:PGHOST="127.0.0.1"
$env:PGPORT="5432"
$env:PGUSER="sigra"
$env:PGPASSWORD="<senha-local>"
python -m alembic -c backend/alembic.ini upgrade head
python scripts/check_migration_status.py
```

## 4. Importacao

Primeiro:

```powershell
python scripts/import_postgresql_data.py dist/data-migration/sqlite-export-v1
```

Depois de revisar o relatório:

```powershell
python scripts/import_postgresql_data.py dist/data-migration/sqlite-export-v1 --confirm-import
```

Um alvo nao vazio e recusado. A excecao exige simultaneamente
`--allow-non-empty-target --confirm-non-empty-target`; registros existentes nao
sao sobrescritos e colisao de chave aborta toda a transacao.

## 5. Equivalencia

```powershell
python scripts/compare_database_contents.py
```

O status esperado e `equivalent`, sem diferencas de contagem, valores,
relacoes ou versoes. Em PostgreSQL, as sequences de chaves inteiras sao
ajustadas depois da carga.

## Rollback

Se a importacao falhar, a transacao e revertida integralmente. Se a validacao
posterior falhar, preserve o SQLite original, descarte o banco PostgreSQL de
integracao e repita a partir do export validado. Nao altere o SQLite canonico.
