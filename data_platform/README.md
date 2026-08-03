# Plataforma de dados — Etapa 3

Esta estrutura e independente do startup da FastAPI. A migration Alembic cria
`meta`, `bronze`, `silver` e `gold`, mas nesta etapa somente as tabelas
`meta.pipeline_run`, `meta.data_quality_issue` e `bronze.fipe_raw` existem.

## Configuracao e execucao

- `DATA_PLATFORM_DATABASE_URL`: URL PostgreSQL exclusiva do processo (obrigatoria para escrita).
- `DATA_PLATFORM_FIPE_API_URL`: base da API, por padrao `https://fipe.parallelum.com.br/api/v2`.
- `DATA_PLATFORM_HTTP_TIMEOUT_SECONDS`: timeout, por padrao 10 segundos.

Na raiz do projeto:

```powershell
$env:DATA_PLATFORM_DATABASE_URL = "postgresql+psycopg://usuario:senha@host/banco"
python -m alembic -c backend/alembic.ini upgrade head
python -m data_platform.ingestion.fipe.cli --dry-run --target "car:004517-9:2021-1"
python -m data_platform.ingestion.fipe.cli --source-reference "2026-08" --target "car:004517-9:2021-1"
```

O dry-run faz HTTP e validacao, mas nao abre conexao nem escreve:
`records_validated` informa quantos registros passaram e `records_inserted`
permanece zero. Testes nunca fazem HTTP real. Para consultar uma execucao:

```sql
SELECT * FROM meta.pipeline_run WHERE pipeline_run_id = '<uuid>';
```

Status: `running`, `succeeded`, `failed`, `partial` e `rejected`. Payloads sao
canonizados apenas para calcular SHA-256; o JSON original (valores e estrutura)
e persistido em JSONB nas respostas 2xx validas. A identidade idempotente usa
fonte, endpoint sanitizado, status HTTP, status de ingestao e hash; assim uma
repeticao realmente identica e deduplicada sem confundir erro com dado valido.

Respostas fora de 2xx sao registradas como `http_error`; respostas 2xx cujo
corpo nao pode ser interpretado como JSON sao `invalid_json`. Nesses eventos,
`payload` e `schema_fingerprint` ficam nulos: nenhum JSON ficticio e criado e o
corpo bruto nao e armazenado. A evidencia auditavel e composta por status HTTP,
endpoint sem autenticacao/query, tamanho do corpo e SHA-256 deterministico dos
bytes recebidos. Isso evita persistir credenciais ou conteudo sensivel. Timeout
sem resposta fica somente em `meta.pipeline_run`, pois nenhum corpo foi recebido.

## Ponte transitoria

`targets.py` consulta os perfis legados e o cache somente para descobrir
endpoints cujo `year_code` completo ja esteja disponivel. IDs internos 1–34 nao
sao copiados nem usados como identidade. Alvos tambem podem ser passados pela
CLI, que e o caminho permanente ate existir o mapeamento Silver. O fluxo atual
de cache/refresh nao foi movido nem alterado.

## Testes e rollback

```powershell
python -m pytest data_platform/tests
python -m pytest backend/tests
python -m alembic -c backend/alembic.ini downgrade 20260723_0001
```

Upgrade/downgrade das novas estruturas so produzem DDL em PostgreSQL. Em SQLite
a revision e deliberadamente no-op, preservando a suite e o startup atuais.
Falhas HTTP/JSON com resposta sao contabilizadas e registradas na Bronze sem
armazenar corpo ou credenciais. Silver, Gold, orquestrador e integracao com o
recomendador seguem fora desta etapa.
