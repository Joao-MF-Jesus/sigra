# Plataforma de dados — Etapa 6

A plataforma de dados permanece independente do startup da FastAPI. As
migrations são PostgreSQL-only e mantêm o banco SQLite operacional como no-op.
O pipeline Gold lê exclusivamente Silver e Meta. Backend, recomendador e
frontend continuam sem integração com a plataforma nesta etapa.

## Estruturas implementadas

- `meta.pipeline_run` e `meta.data_quality_issue`;
- `bronze.fipe_raw`;
- `silver.vehicle_identity`;
- `silver.vehicle_source_mapping`;
- `silver.vehicle_price_history`;
- `gold.vehicle_feature_dataset`;
- `gold.vehicle_features_snapshot`;
- `gold.vehicle_feature_dataset_activation`;
- view `gold.vehicle_features_current`.

A Silver lê exclusivamente registros `bronze.fipe_raw` com
`ingestion_status = 'received'`, HTTP 2xx e payload JSONB não nulo. Eventos
`invalid_json`, `http_error` e timeouts não entram na transformação.

## Configuração e execução

- `DATA_PLATFORM_DATABASE_URL`: URL do banco usado pela plataforma.
- `DATA_PLATFORM_FIPE_API_URL`: base da API usada somente pela ingestão Bronze.
- `DATA_PLATFORM_HTTP_TIMEOUT_SECONDS`: timeout da ingestão Bronze.
- `DATA_PLATFORM_TEST_POSTGRESQL_URL`: PostgreSQL descartável para testes reais.

Na raiz do projeto:

```powershell
$env:DATA_PLATFORM_DATABASE_URL = "postgresql+psycopg://usuario:senha@host/banco"
python -m alembic -c backend/alembic.ini upgrade head
python -m data_platform.ingestion.fipe.cli --source-reference "2026-08" --target "car:004517-9:2021-1"
python -m data_platform.transformation.cli --source-reference "2026-08"
python -m data_platform.publication.cli publish --source-reference "2026-08"
```

Rollback manual para um snapshot já publicado:

```powershell
python -m data_platform.publication.cli rollback "gold-fipe-car-v1-..."
```

O dry-run Silver valida a Bronze elegível, mas não cria `pipeline_run`, issues
ou linhas Silver e mantém `records_inserted` igual a zero:

```powershell
python -m data_platform.transformation.cli --dry-run
```

## Identidade e mapping

`brand` e `model` são obrigatórios. A descrição `model` da FIPE permanece
integral em `model_name`; a etapa não tenta separar uma versão sem evidência.
`version_name` e `transmission_type` permanecem nulos.

A chave canônica é um SHA-256 de uma representação JSON determinística. Somente
caixa, acentos e sequências de espaços são neutralizados na chave. Os valores
de exibição preservam caixa, acentos, pontuação e conteúdo, normalizando apenas
Unicode e espaços.

`fuel` é a fonte principal e usa o vocabulário `gasoline`, `ethanol`, `flex`,
`diesel`, `electric`, `hybrid` e `cng`. `fuelAcronym` apenas valida o valor:

- combustível ausente/desconhecido: mapping `pending` e issue `UNMAPPED_FUEL`;
- conflito reconhecido: mapping `ambiguous` e revisão obrigatória;
- nenhum desses estados produz preço.

O `year_code` completo, inclusive o sufixo, é preservado no mapping.
`modelYear` é apenas validação cruzada. O valor `32000` representa zero
quilômetro: `is_zero_km = true` e `model_year = NULL`. Ausência de ano e zero-km
possuem representações diferentes no cálculo da chave.

Somente mappings `matched` possuem `vehicle_sk` e publicam preço. `pending`,
`ambiguous` e `rejected` exigem `vehicle_sk = NULL`; decisões ambíguas, manuais
ou revisadas exigem `review_notes`.

O mapping materializa `vehicle_type` (`car`, `motorcycle` ou `truck`) diretamente
da linhagem Bronze. As identidades externas vigentes são compostas por
`source_name + vehicle_type + source_vehicle_key` e, para FIPE, por
`source_name + vehicle_type + fipe_code + year_code`. A mesma chave pode existir
em tipos diferentes, mas não pode se repetir dentro do mesmo tipo.

## Preço, histórico e qualidade

Preço FIPE é aceito somente como BRL no formato da fonte, convertido diretamente
para `Decimal` e persistido como `NUMERIC(14,2)`. Não há conversão por `float`.
`referenceMonth` é convertido por tabela explícita de meses para o primeiro dia
do mês, sem depender do locale do sistema.

O histórico é append-only e ordenado por competência:

- referência mais recente encerra o atual e torna-se corrente;
- referência antiga entra como não corrente entre predecessor e sucessor;
- mesmo mês e mesmo preço é idempotente;
- mesmo mês com preço diferente cria `PRICE_CONFLICT_SAME_MONTH` e não altera o
  fato existente;
- somente `valid_to` e `is_current` são atualizados para fechar intervalos.

Toda linha Silver mantém run de transformação e FK para a Bronze de origem. A
execução de ingestão continua recuperável por
`bronze.fipe_raw.pipeline_run_id`. Issues usam a referência segura
`bronze.fipe_raw:<id>`, não copiam payload ou endpoint e possuem índice único
parcial para deduplicar falhas abertas equivalentes.

## Reconciliação dos 34 automóveis

`data_platform.reconciliation.legacy_cars` gera cobertura read-only dos perfis
atuais usando código FIPE e `year_code` completo. Os IDs 1–34 aparecem apenas
como referências externas do relatório. O relatório classifica cada item como
`matched`, `pending`, `ambiguous` ou `rejected` e nunca escreve nem completa a
Silver.

## Publicação Gold

A Gold v1 publica exclusivamente carros da fonte exata
`Tabela FIPE via API Parallelum`. O denominador inclui todos os mappings
correntes `matched`, `pending`, `ambiguous` e `rejected`; o snapshot inclui
somente identidades e preços elegíveis. A cobertura é calculada com
`Decimal`/`NUMERIC`, exige denominador e numerador maiores que zero e precisa ser
de pelo menos 80%.

Cada dataset possui cabeçalho físico e snapshot imutável. A ativação é atômica,
mantém no máximo um dataset ativo e registra eventos append-only de `initial`,
`replacement` e `rollback`. Repetir uma publicação com o mesmo fingerprint do
dataset ativo não cria snapshot nem evento.

O fingerprint não inclui relógio ou freshness. A view corrente calcula
dinamicamente:

- `current`: até 45 dias;
- `stale`: de 46 a 90 dias;
- `expired`: acima de 90 dias.

Preço expirado continua visível. Somente `base_quality_status = 'passed'` junto
de freshness `current` resulta em `quality_status = 'passed'`; todos os demais
casos resultam em `warning`.

Issues Silver críticas e abertas são bloqueios globais porque suas referências
atuais normalmente apontam para Bronze, que a Gold não consulta. Issues aceitas
e aplicáveis produzem warning. Issues Gold usam somente referências seguras de
mapping, identidade, preço, dataset ou run e nunca armazenam payload, endpoint,
URL autenticada ou credencial.

## Testes e rollback

```powershell
python -m pytest data_platform/tests
python -m pytest backend/tests
python -m compileall data_platform backend
python -m alembic -c backend/alembic.ini heads
git diff --check
```

Com PostgreSQL descartável:

```powershell
$env:DATA_PLATFORM_TEST_POSTGRESQL_URL = "postgresql+psycopg://..."
python -m pytest data_platform/tests/test_postgresql_silver.py data_platform/tests/test_postgresql_gold.py -q
```

Downgrade da Etapa 5:

```powershell
python -m alembic -c backend/alembic.ini downgrade 20260803_0003
```

O downgrade verifica previamente colisões que seriam incompatíveis sem
`vehicle_type`. Se houver colisão entre tipos, aborta antes de remover qualquer
estrutura ou dado. Sem colisões, remove a Gold e restaura exatamente o contrato
Silver `0003`. Em SQLite, upgrade, downgrade, publicação e rollback são
deliberadamente no-op.

## Orquestração Bronze → Silver → Gold

A Etapa 6 adiciona uma camada de coordenação sem alterar regras das camadas. O
núcleo em `data_platform.orchestration` chama diretamente as funções Python
`run_pipeline`, `run_silver_pipeline` e `run_gold_publication`; não executa
CLIs, subprocessos ou FastAPI. Bronze, Silver e Gold continuam utilizáveis de
forma independente.

A migration `20260810_0005` cria exclusivamente em PostgreSQL:

- `meta.orchestration_run`, com fluxo/versão, gatilho, chave idempotente,
  parâmetros sanitizados, status, heartbeat e tempos;
- `meta.orchestration_step_run`, com etapa, tentativa, dependência, FK opcional
  para `meta.pipeline_run`, métricas resumidas e erro sanitizado;
- enums para status (`pending`, `running`, `succeeded`, `partial`, `failed`,
  `skipped`, `cancelled`), etapa e gatilho;
- constraints, índices e atualização automática de `updated_at`.

Em SQLite, a migration permanece no-op deliberado. O downgrade da Etapa 6
remove somente esses metadados e retorna ao head `20260803_0004`.

### Execução local

O banco analítico continua vindo de `DATA_PLATFORM_DATABASE_URL`; a URL nunca é
incluída em parâmetros, métricas ou resultados. Exemplos:

```powershell
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --from-step silver
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --from-step gold
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --dry-run
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli result <orchestration_run_id>
```

O `dry-run` produz somente um plano estruturado: não abre banco, não grava
metadados e não chama a FIPE. `--source-reference`, `--git-commit`,
`--trigger-type`, `--idempotency-key` e `--resume` permitem identificar e
retomar uma execução sem incluir credenciais. `--partial-policy` aceita
`continue`, `stop` ou `fail`.

Os mesmos defaults podem vir de
`DATA_PLATFORM_ORCHESTRATION_START_STEP`,
`DATA_PLATFORM_ORCHESTRATION_TRIGGER_TYPE`,
`DATA_PLATFORM_ORCHESTRATION_SOURCE_REFERENCE`,
`DATA_PLATFORM_ORCHESTRATION_GIT_COMMIT`,
`DATA_PLATFORM_ORCHESTRATION_IDEMPOTENCY_KEY`,
`DATA_PLATFORM_ORCHESTRATION_PARTIAL_POLICY`,
`DATA_PLATFORM_ORCHESTRATION_MAX_ATTEMPTS`,
`DATA_PLATFORM_ORCHESTRATION_BACKOFF_SECONDS` e
`DATA_PLATFORM_ORCHESTRATION_STEP_TIMEOUT_SECONDS`. Argumentos explícitos da
CLI têm precedência.

### Políticas operacionais

- Bronze, Silver e Gold sempre respeitam a ordem; falha Bronze bloqueia Silver
  e Gold, e falha Silver bloqueia Gold.
- Resultado `partial` segue uma política explícita. O padrão `continue` executa
  a próxima etapa e mantém o run final como `partial`.
- Falhas transitórias usam tentativas limitadas e backoff exponencial. Resultado
  definitivo (`failed`/`rejected`) não é repetido cegamente.
- Uma etapa `succeeded` ou `partial` persistida não é repetida na retomada; uma
  nova tentativa é criada apenas para a etapa incompleta.
- A chave idempotente é persistida somente como SHA-256 e devolve o resultado
  terminal existente. `--resume` reabre de modo explícito um run terminal
  incompleto.
- Um advisory lock PostgreSQL exclusivo impede fluxos incompatíveis
  concorrentes. Heartbeat antigo permite recuperar um run `running` abandonado.
- O timeout do núcleo é cooperativo por checkpoint seguro. No adaptador
  Prefect, cada task também recebe timeout operacional; retries continuam sendo
  decididos pelo núcleo, sem duas políticas concorrentes.
- `Ctrl+C`/cancelamento é registrado como `cancelled` entre checkpoints, sem
  iniciar a próxima etapa.

### Prefect opcional e agendamento

`data_platform.orchestration.prefect_flow` importa Prefect somente quando o
flow é solicitado. Prefect não foi adicionado a `backend/requirements.txt` e o
backend FastAPI não o importa. Um runtime operacional pode provisioná-lo como
dependência opcional e executar localmente:

```powershell
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli prefect
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli prefect --serve-cron "0 3 * * *" --timezone America/Sao_Paulo
```

Sem Prefect, esse comando retorna erro de configuração claro; o comando `run`
continua funcional. O flow expõe tasks Bronze, Silver e Gold. `--serve-cron`
configura um deployment local somente quando explicitamente solicitado; os
testes substituem essa API por objetos locais e não iniciam servidor. Trocar
Prefect por outro scheduler exige somente outro dispatcher/adaptador para o
runner, sem mudança nos pipelines.

Runs agendados usam o identificador do próprio flow run Prefect como material
da chave idempotente quando o operador não fornece uma chave. Assim, ocorrências
distintas do cron não se deduplicam entre si, enquanto retries da mesma
ocorrência continuam correlacionados.

### Monitoramento, retomada e rollback

Consulte `result <orchestration_run_id>` ou as tabelas Meta para obter etapa,
tentativa, duração, status, `pipeline_run_id`, contagens, cobertura e motivo
seguro de falha/skip. Payload FIPE, endpoint, senha, token e URL autenticada não
são persistidos. O rollback de dados continua sendo responsabilidade da Gold;
o rollback da migration de orquestração não altera Bronze, Silver, Gold nem
`meta.pipeline_run`.

Limitações atuais: o timeout puro do núcleo depende de checkpoints cooperativos,
e a agenda/deployment Prefect deve ser provisionada pelo ambiente operacional.
Esta etapa não integra a orquestração ao startup da API nem ao frontend.

### Testes da Etapa 6

```powershell
.\backend\.venv\Scripts\python.exe -m pytest data_platform\tests\test_orchestration.py -q -p no:cacheprovider
.\backend\.venv\Scripts\python.exe -m pytest data_platform\tests -q -p no:cacheprovider
```

Os testes de `test_postgresql_orchestration.py` só usam
`DATA_PLATFORM_TEST_POSTGRESQL_URL` quando o backend é PostgreSQL e o nome do
banco termina em `_test`. Sem essa configuração, permanecem skipped e nenhuma
URL é inventada ou exibida.
