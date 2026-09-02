# Plataforma de dados — Etapa 8B2

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

A Etapa 7B acrescenta, sem conectar consumidores:

- `bronze.pbev_source_asset` e `bronze.pbev_raw_row`;
- `silver.pbev_vehicle_mapping`, sua view de decisão corrente e
  `silver.vehicle_efficiency_observation`;
- `gold.vehicle_efficiency_dataset`, `gold.vehicle_efficiency_snapshot` e
  `gold.vehicle_efficiency_quality_result`.

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
$env:DATA_PLATFORM_DATABASE_URL = "postgresql+psycopg://localhost/sigra_data_platform"
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

## PBE Veicular interno e shadow

O ramo PBEV é analítico, independente e de uso interno:

```text
PDFs oficiais externos -> Bronze PBEV -> Silver mapping -> Gold shadow
```

Ele não é importado pela FastAPI, frontend, recomendador, financiamento ou BI;
não altera `gold.vehicle_feature_dataset`, ranking nem dados demonstrativos. O
Gold PBEV usa somente `building`, `shadow_published` e `retired`; nunca publica
um dataset `active` para consumidores.

Os seis PDFs de 2017 a 2022 devem permanecer em diretório externo. O modo desta
etapa é obrigatoriamente `metadata_only`: somente metadados, hashes, células
internas e linhagem são persistidos; `document_bytes` permanece nulo. PDFs e
linhas transformadas não podem ser redistribuídos em Git, ZIP ou documentação.
O uso registra atribuição ao Instituto Nacional de Metrologia, Qualidade e
Tecnologia (Inmetro), PBE Veicular, e licença `CC-BY-ND-3.0`. Exposição ou
redistribuição futura exige revisão jurídica específica.

O parser `pbev-pdf-v1` aceita exclusivamente os hashes auditados e quatro
famílias de layout versionadas. Ele valida HTTPS oficial, MIME, assinatura,
tamanho, páginas, SHA-256, layout, licença, atribuição e unidades. Grade vetorial
é o caminho normal; fallback de texto posicionado exige revisão explícita. OCR
não é usado. Drift, hash diferente, página incompleta ou unidade desconhecida
bloqueiam Silver/Gold. Ausência vira `NULL`, nunca zero, e decimais não passam
por `float`. NMHC/CO/NOx em g/km até 2021 permanecem semanticamente separados
de NMOG+NOx/CO/CHO em mg/km em 2022.

O matcher `pbev-match-v1` usa marca 10, modelo 20, ciclo 10, versão 20, motor 15,
transmissão 10, combustível/propulsão 10 e carroceria 5. Um único líder
compatível, sem conflito e com ao menos 95 pontos é `matched`; múltiplos líderes
semanticamente equivalentes também podem ser `matched` quando suas métricas
materiais são idênticas. A faixa de 75–94 é `pending` quando ainda não existe
evidência suficiente para um match seguro. Líderes com identidades semânticas
diferentes ou métricas materiais divergentes permanecem `ambiguous`; conflito
do catálogo é `rejected` e ausência é `not_found`. Somente `matched` pode ser
publicado. Decisões `pending`, `ambiguous`, `rejected` ou `not_found` nunca são
publicadas. Decisões são append-only e revisão manual cria supersessão.
`vehicle_sk` sempre vem da Silver real; IDs 1–34 são somente referências
externas e `sample_data` não participa do matching.

Para os seis hashes, parser, matcher e catálogo auditados, duas materializações
idempotentes no PostgreSQL local descartável revisaram formalmente o baseline
das 34 identidades para 18 `matched`, 6 `ambiguous`, 3 `rejected`, 3
`not_found` e 4 `pending`, com cobertura publicável de 52,94%. As referências
19, 20 e 22 foram rebaixadas de `matched` para `pending` por ausência de
evidência suficiente de transmissão; a referência 33 permaneceu `pending`.
Trata-se de governança de qualidade baseada em evidência reproduzível, não de
relaxamento arbitrário. Regressão abaixo de 18 bloqueia publicação; aumento
requer evidência de revisão. Somente `matched` entra no Gold shadow. Os gates
também exigem origem, hash, MIME, páginas, layout, unidades, linhagem,
reconciliação dos estados, dataset não vazio, unicidade de `vehicle_sk`, licença
e atribuição.

### Execução manual e testes

Instale as dependências já fixadas do projeto no runtime de dados antes do
processamento. `pdfplumber==0.11.9` foi escolhido por ser suficiente para grade
vetorial/texto posicionado, possuir licença MIT e não adicionar OCR.

```powershell
$env:PBEV_ASSET_DIR = "C:\caminho-externo\pbev"
$env:DATA_PLATFORM_DATABASE_URL = "postgresql+psycopg://..."
.\backend\.venv\Scripts\python.exe -m data_platform.pbev.cli run
.\backend\.venv\Scripts\python.exe -m data_platform.pbev.cli run --dry-run
```

O dry-run não resolve o diretório, não importa a biblioteca PDF, não abre banco,
não chama rede e não escreve. O download é uma ação explícita separada; retries
são limitados a timeout/TLS transitório, 408, 429 e 5xx, respeitando
`Retry-After`. Locks são `pbev:<cycle_year>`, e o pipeline expõe checkpoints de
heartbeat, cancelamento e timeout. Uma falha PBEV não altera nem bloqueia FIPE.

Testes oficiais são opt-in e apontam para os ativos externos:

```powershell
$env:PBEV_TEST_ASSET_DIR = "C:\caminho-externo\pbev"
.\backend\.venv\Scripts\python.exe -m pytest data_platform\tests\test_pbev.py -q -p no:cacheprovider
```

O teste PostgreSQL só executa quando `DATA_PLATFORM_TEST_POSTGRESQL_URL` indica
PostgreSQL descartável com nome terminado em `_test`; a URL nunca é impressa.
Sem a variável, o teste fica explicitamente skipped.

Rollback apenas da Etapa 7B:

```powershell
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini downgrade 20260810_0005
```

O downgrade bloqueia se houver shadow PBEV ativo, remove somente objetos PBEV e
preserva FIPE e orquestração. SQLite continua no-op. Antes de qualquer uso fora
do ambiente interno shadow, a área jurídica deve revisar licença, atribuição,
armazenamento, redistribuição e contrato dos consumidores.

## Preços de combustíveis ANP — fundação shadow

A Etapa 8B1 adiciona um pipeline manual e independente para o download oficial
do dataset CSV móvel de preços de gasolina e etanol da ANP. A fonte não é uma
API. O único host permitido inicialmente é `www.gov.br`, com HTTPS obrigatório,
redirects restritos ao mesmo host, streaming, timeout e retry somente para
timeout, 408, 429 e 5xx. O limite operacional inicial é 32 MiB: aproximadamente
quatro vezes o asset de 7.908.850 bytes observado no piloto. O cliente valida
`Content-Length`, quando presente, e também interrompe o próprio stream ao
ultrapassar o limite; esse valor deverá ser revisto após novos pilotos.

```text
CSV oficial ANP -> Bronze ANP -> Silver ANP -> Gold ANP shadow
```

O pipeline continua sem conexão de dados com PBEV, FastAPI, recomendador,
frontend, financiamento ou BI. A Etapa 8B2 apenas permite coordenar sua API
Python pública pelo mesmo runner da plataforma; o resultado permanece Gold
shadow e nunca substitui a Gold FIPE operacional.

O modo Bronze é sempre `metadata_only`: os bytes originais do CSV não são
persistidos no PostgreSQL nem no repositório. O arquivo existe somente no
diretório temporário do sistema durante download e parsing, sendo removido em
sucesso ou falha. Metadados, hashes e período ficam em
`bronze.anp_source_asset`; as linhas parseadas e sua linhagem ficam em
`bronze.anp_fuel_price_raw` como JSONB append-only.

O parser `anp-csv-v1` exige o header ordenado auditado, ponto e vírgula e UTF-8
com ou sem BOM. Coluna ausente, extra, desconhecida ou reordenada é layout drift
e bloqueia a publicação. Dinheiro é convertido diretamente para `Decimal`, sem
passar por `float`. Gasolina C comum, gasolina C aditivada e etanol hidratado
permanecem produtos distintos; diesel, GNV e GLP são reconhecíveis, mas ficam
fora do recurso atual. Gasolina C comum e etanol hidratado são produtos
essenciais do recurso e devem estar presentes. Gasolina C aditivada continua
reconhecida, processada, separada e opcional.

A Silver mantém razão social e endereço normalizados para a finalidade interna,
mas CNPJ bruto existe somente na Bronze restrita. A Silver guarda apenas hash
determinístico do CNPJ; ausência ou invalidade usa identidade alternativa
controlada e issue sanitizada. Gold nunca contém CNPJ, razão social, endereço ou
payload Bronze. Mesma identidade e conteúdo deduplicam; divergência dentro do
mesmo asset é conflito; correção posterior cria supersessão append-only, issue
crítica e exige revisão.

A Gold agrega por produto, semana e geografia municipal/estadual. Mediana é a
métrica preferencial para futura estimativa de custo e média permanece
disponível, junto a mínimo, máximo, quartis e IQR. Todos os cálculos usam
`Decimal`. Amostra, estabelecimentos, cobertura, freshness, extremos, dispersão
e variação semanal começam como `not_calibrated`, sem thresholds inventados.
O hard gate `ANP_REQUIRED_PRODUCTS_PRESENT` bloqueia a publicação se gasolina C
comum ou etanol hidratado estiver ausente; ausência somente de gasolina C
aditivada não bloqueia. Hard gates aprovados ativam atomicamente um único
`shadow_published`; falha preserva o shadow anterior e não deixa publicação
parcial. Fingerprint igual ao shadow ativo é no-op.

Execução manual e dry-run:

```powershell
.\backend\.venv\Scripts\python.exe -m data_platform.anp.cli --source-reference anp-last-four-weeks-gasoline-ethanol --dry-run
.\backend\.venv\Scripts\python.exe -m data_platform.anp.cli --source-reference anp-last-four-weeks-gasoline-ethanol
```

O dry-run não abre banco, não chama rede e não cria arquivo. Os testes comuns
usam CSVs sintéticos mínimos. O teste PostgreSQL executa somente quando
`DATA_PLATFORM_TEST_POSTGRESQL_URL` aponta para PostgreSQL local descartável
com nome terminado em `_test`; a URL nunca é exibida. A migration
`20260811_0007` é PostgreSQL-only, no-op em SQLite e bloqueia downgrade quando
existe shadow ANP ativo.

## Orquestração FIPE, PBEV e ANP — Etapa 8B2

A orquestração existente foi ampliada sem duplicar framework. FIPE preserva as
unidades Bronze → Silver → Gold; PBEV e ANP são registrados como unidades
transacionais próprias porque suas APIs públicas já coordenam internamente as
camadas medalhão. O runner chama diretamente `run_pbev_pipeline` e
`run_anp_pipeline`, sem CLI intermediária ou subprocesso.

Os modos explícitos são:

- `fipe`: comportamento anterior e padrão, com suporte a `--from-step`;
- `pbev`: executa somente o shadow PBEV e exige os seis ativos auditados no
  diretório externo informado;
- `anp`: executa somente o pipeline ANP oficial e mantém a publicação shadow;
- `complete`: executa FIPE, PBEV e ANP, preservando os resultados concluídos de
  cada ramo.

```powershell
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --scope fipe --from-step silver
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --scope pbev --pbev-asset-dir "C:\caminho-externo\pbev"
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --scope anp
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --scope complete --pbev-asset-dir "C:\caminho-externo\pbev"
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli run --scope complete --dry-run
.\backend\.venv\Scripts\python.exe -m data_platform.orchestration.cli prefect --scope anp --trigger-type scheduled --serve-cron "0 3 * * 1" --timezone America/Sao_Paulo --deployment-name sigra-anp-weekly
```

O `dry-run` é um plano puro: não carrega cliente, não abre banco, não resolve
ativos PBEV, não cria arquivo temporário e não adquire lock. Prefect continua
opcional e com import tardio; o mesmo parâmetro `--scope` vale para o comando
`prefect`.
O cron acima é apenas um exemplo semanal configurável; ele só inicia o
deployment local quando o operador executa explicitamente `--serve-cron`.

Cada recurso usa lock independente (`sigra-orchestration:fipe`, `:pbev` e
`:anp`). O modo `complete` adquire os três em ordem determinística. Assim, runs
isolados sem recurso comum podem coexistir, enquanto um fluxo completo não
concorre com outro run que escreva no mesmo ramo. Retomada reutiliza toda
unidade `succeeded`/`partial` e repete somente a incompleta. Retry automático é
restrito às exceções transitórias já classificadas; erro de contrato ou
resultado definitivo não recebe repetição cega.

Em `complete`, falha de um ramo independente depois de outro concluído produz
status global `partial`; as publicações anteriores não são revertidas. Dentro
da FIPE, Bronze e Silver continuam bloqueando apenas seus dependentes. ANP e
PBEV não se bloqueiam mutuamente. Status, tentativa, duração, último
`pipeline_run_id` aplicável, métricas resumidas e erro sanitizado permanecem em
`meta.orchestration_run` e `meta.orchestration_step_run`.

A migration `20260811_0008` apenas amplia o enum de steps existente para
`pbev` e `anp_fuel_prices`; não altera DDL, dados ou constraints dos pipelines.
Ela é no-op em SQLite. O downgrade para `20260811_0007` é bloqueado enquanto existir
histórico de orquestração PBEV/ANP, evitando descarte silencioso de auditoria.

## Gold analítica integrada — Etapa 9, Lote 1

O Lote 1 cria somente a fundação estrutural PostgreSQL da análise integrada de
custo veicular FIPE + PBEV + ANP. Não há loader, pipeline, CLI, unidade de
orquestração nem leitura por FastAPI, recomendador, frontend ou BI neste lote.
A migration `20260811_0009` é no-op em SQLite e referencia exclusivamente os
snapshots Gold canônicos: `gold.vehicle_features_snapshot`,
`gold.vehicle_efficiency_snapshot` e `gold.anp_fuel_price_snapshot`.

O dataset integrado usa versões de até 96 caracteres e fixa versões-fonte de
até 80. Seu snapshot tem grão por dataset, veículo, combustível, geografia
exata solicitada e semana ANP; deliberadamente não contém `scenario_code`. A
projeção acrescenta o cenário único `mixed_1000_v1` (1.000 km/mês e 12.000
km/ano). Assim, veículos e cenários publicados são sempre derivados das
projeções unidas aos snapshots, nunca da mera presença de um snapshot.

Exclusões são evidência Gold append-only e têm grãos separados para veículo e
cenário. Triggers impedem conflito nos dois sentidos entre exclusão e projeção.
A reconciliação compara conjuntos completos com `EXCEPT`/`UNION`, registrando
chaves ausentes e inesperadas; igualdade de contagens não é suficiente.

O catálogo inicial possui 29 hard gates críticos, todos com expectativa
`passed`, e preserva os sete controles estatísticos ANP como
`not_calibrated`. A identidade da evidência inclui dataset, versão da política
e código da regra, de modo que resultado de outra política não autoriza
ativação. Coberturas usam `catalog_coverage_pct` e `pbev_coverage_pct` em
`NUMERIC`; regressão aceita somente `not_applicable`, `passed` ou
`manual_review_required`, e este último bloqueia ativação e rollback.

Publicação permanece exclusivamente shadow e atômica por eventos `publish`,
`replace` e `rollback`. Snapshots, projeções, comparações flex, resultados de
qualidade, ativações, invalidações e baselines são imutáveis. O downgrade da
`20260811_0009` remove apenas seus próprios objetos e bloqueia se houver dataset
ou evidência integrada, evitando descarte silencioso.

## Gold analítica integrada — Etapa 9, Lote 2

O módulo `data_platform.integrated_vehicle_cost` materializa e publica o contrato
estrutural do Lote 1 sem criar migration adicional. Ele seleciona somente os
datasets Gold ativos e aprovados de FIPE, PBEV e ANP, fixa suas versões e
fingerprints e executa todas as leituras e escritas sob `REPEATABLE READ` e um
advisory lock transacional exclusivo. Bronze, Silver, caches e fontes externas
não participam dessa unidade.

A requisição exige semana ANP e geografia municipal ou estadual exatas. Não há
fallback nacional ou imputação. Gasolina C comum e etanol hidratado são
obrigatórios; gasolina aditivada permanece opcional e separada. Veículos sem
PBEV Gold matched ou sem consumo material suficiente entram como exclusões Gold
auditáveis e não recebem projeções inventadas.

As projeções reutilizam exclusivamente `calculate_projection`, `Decimal` e o
cenário `mixed_1000_v1`: participação urbana/rodoviária de 50%/50%, 1.000 km por
mês e 12.000 km por ano. O snapshot continua sem `scenario_code`; o código está
somente na projeção. Comparações flex usam gasolina comum e etanol do mesmo
veículo, semana e geografia.

Na mesma transação são persistidos dataset, requisição geográfica, snapshots,
projeções, comparações flex, exclusões, 29 hard gates, sete controles ANP em
`not_calibrated` e, quando autorizado, o evento de ativação. A reconciliação do
banco valida conjuntos completos por `UNION`, `EXCEPT` e `INTERSECT`. Uma
regressão de cobertura persiste a tentativa como `manual_review_required`, mas
não ativa nem substitui o shadow corrente.

O fingerprint é determinístico e cobre fontes, políticas, requisição,
projeções, exclusões, comparações e evidência de qualidade, sem relógio ou run
ID. Reexecutar o mesmo conteúdo retorna `deduplicated` sem criar dataset,
snapshot, exclusão, quality result ou ativação. Conteúdo material novo gera
substituição atômica. Rollback explícito aceita somente dataset publicado,
retirado, não invalidado e sem revisão pendente; repetir rollback para o dataset
já ativo é idempotente. Evidências históricas não sofrem update ou delete.

Execução manual:

```powershell
.\backend\.venv\Scripts\python.exe -m data_platform.integrated_vehicle_cost.cli dry-run --geography-level municipality --geography-key sao-paulo-sp --week-start 2026-08-03
.\backend\.venv\Scripts\python.exe -m data_platform.integrated_vehicle_cost.cli publish --geography-level municipality --geography-key sao-paulo-sp --week-start 2026-08-03
.\backend\.venv\Scripts\python.exe -m data_platform.integrated_vehicle_cost.cli rollback integrated-cost-v1-...
```

O dry-run retorna somente plano JSON determinístico e sanitizado: não lê
variável de banco, não cria engine, não adquire lock, não chama pipelines-fonte,
não acessa rede e não cria arquivos. A CLI de publicação/rollback lê
`DATA_PLATFORM_DATABASE_URL` somente fora do dry-run. SQLite permanece no-op.

O produto continua exclusivamente Gold shadow. Este lote não altera
orquestração e não cria integração com FastAPI, recomendador, frontend,
financiamento ou BI.

## Gold integrada — orquestração e consumo somente leitura

A migration `20260811_0010`, filha direta da `20260811_0009`, registra
`integrated_vehicle_cost` como unidade canônica própria do ENUM
`meta.orchestration_step`. O valor `gold` continua significando exclusivamente
a Gold FIPE. Em PostgreSQL, as colunas `orchestration_run.start_step` e
`orchestration_step_run.step_name` aceitam a nova unidade; SQLite permanece
no-op. O downgrade é bloqueado se qualquer uma dessas colunas contiver histórico
integrado e nunca apaga ou converte auditoria automaticamente.

No escopo `complete`, a ordem termina em `gold`, `pbev`, `anp_fuel_prices` e
`integrated_vehicle_cost`; a unidade integrada só inicia depois das três fontes
concluídas. Ela possui lock, heartbeat, tentativas, métricas e retomada próprios.
Geografia e semana são parâmetros explícitos. A execução chama diretamente
`run_integrated_vehicle_cost_pipeline` em Python, sem CLI interna ou subprocesso.
O dry-run continua anterior a engine, lock, rede e qualquer gravação.

A API versionada `/api/v1/integrated-vehicle-cost` é exclusivamente de leitura.
O repositório conhece somente a view contratual versionada
`gold.integrated_vehicle_cost_consumption_v1`, que projeta apenas o dataset
integrado ativo, `shadow_published`,
com hard gates e qualidade aprovados, sem regressão em revisão manual e sem
invalidação. Não há fallback para Bronze, Silver, legado ou fonte externa. Os
endpoints oferecem metadata, listagem paginada/ordenada por allowlist e detalhe
por `vehicle_sk`; valores decimais permanecem decimais.

`mixed_1000_v1` é identificado na resposta somente como baseline analítico
publicado. Ele não se torna perfil fixo de cliente. Esta etapa não inventa
quilometragem, participação urbana/rodoviária ou outro parâmetro personalizado;
qualquer evolução desse consumo deverá exigir entradas explícitas do usuário.
Não há integração automática com recomendador, frontend ou BI e a publicação
continua shadow.

## Simulação configurável de custo veicular

`POST /api/v1/integrated-vehicle-cost/simulate` executa uma simulação stateless
e somente leitura. A requisição informa explicitamente quilometragem mensal,
percentuais urbano e rodoviário, horizonte em meses, UF, município opcional,
semana ANP, combustível ou estratégia de menor custo, preço manual opcional,
eficiências urbana e rodoviária opcionais, filtro de veículos e limite de
resultados. Distância e horizonte devem ser positivos, a soma dos percentuais
deve ser exatamente 100 e preço ou eficiência informados devem ser positivos.
Limites defensivos rejeitam distância mensal acima de 100.000 km, horizonte
acima de 120 meses e preço ou eficiência acima de 1.000 nas respectivas
unidades. Valores decimais são strings ou inteiros; booleanos, `float`, NaN e
infinitos são rejeitados sem conversão intermediária para `float`.

No modo ANP, produto, geografia e semana devem coincidir exatamente com a Gold
integrada ativa e elegível. No modo manual, o preço vem exclusivamente da
entrada do cliente e não é combinado silenciosamente com preço ANP; a semana
ANP não é apresentada como origem desse preço. Eficiências omitidas usam apenas
evidência PBEV Gold publicada do veículo. Não existe fallback de localidade,
período, produto, preço ou eficiência. Ausência ou ambiguidade gera exclusão ou
erro com código auditável. Gasolina comum, gasolina aditivada e etanol são
seleções explícitas; `lowest_projected_cost` avalia somente evidências
compatíveis disponíveis, sem inventar combustível.

Com proporções `Decimal`, o consumo mensal é `distância mensal × (percentual
urbano / eficiência urbana + percentual rodoviário / eficiência rodoviária)`;
o custo mensal é `consumo mensal × preço`, e o custo do horizonte é `custo
mensal × meses`. Litros mensais e anuais, custos, diferenças contra o baseline e
arredondamentos usam quantizações centralizadas. O ranking ordena custo mensal,
custo por quilômetro, identidade e combustível; o desempate de combustível é
documentado e determinístico. O fingerprint contém cenário, resultados,
exclusões e linhagem, sem relógio ou identificador aleatório.

A resposta ecoa os parâmetros normalizados, eficiências e preço utilizados,
origens `user_input`, `pbev_gold`, `anp_gold` e `canonical_policy`, versões das
fontes, custos mensal/anual/no horizonte, comparação com `mixed_1000_v1`,
avisos, limitações e timestamp da resposta. O baseline canônico continua sendo
a projeção publicada para comparação, ranking, auditoria e regressão; ele não
fornece defaults nem é alterado pela simulação personalizada. A requisição não
grava banco, executa pipeline, adquire lock ou chama rede. Financiamento,
manutenção, seguro, IPVA, depreciação, recomendador e BI permanecem fora do
motor. No fluxo de detalhes do veículo, o frontend consulta a listagem pública
da Gold para exigir uma identidade `vehicle_sk` inequívoca, valida os parâmetros
antes do envio e apresenta resultados, fontes e limitações devolvidos pela API.
Ele não reproduz fórmulas, não persiste preferências e não escreve na Gold.

## Recomendação multifator orientada pelo perfil

`POST /recommendations` mantém o contrato histórico quando
`multifactor_profile` é omitido: ordem, Nota SIGRA, empates, mensagens e
elegibilidade continuam produzidos pelo recomendador existente. A extensão é
opt-in e stateless. Quando habilitada, ela aplica um único cenário explícito a
todos os veículos comparáveis, consulta somente a Gold integrada ativa e
elegível e reutiliza o motor `Decimal` da simulação. Nenhuma fórmula financeira
é copiada para a rota ou para o frontend.

Os pesos de custo de combustível, adequação ao uso, conforto, segurança,
desempenho rodoviário, eficiência e qualidade histórica são decimais finitos,
não negativos e normalizados de forma determinística. Custo e eficiência Gold
ficam isolados dos componentes históricos para impedir dupla contagem. Conforto
sem evidência não vira zero inventado: o veículo fica indisponível no ranking
multifator. Identidade Gold ausente ou ambígua também não recebe fallback.

A resposta mostra posição e nota históricas, valores brutos, peso informado,
peso normalizado, contribuição, nota final, desempate, custos, versões das
fontes, avisos e limitações. Dado Gold publicado, parâmetro do usuário e
resultado derivado possuem origens distintas. `mixed_1000_v1` permanece apenas
como baseline analítico. Orçamento acima de R$ 200 mil exige autorização
explícita; não existe teto oculto. Preferências e resultados não são persistidos
e os datasets publicados não são alterados.

## Experiência de recomendação ponta a ponta

A jornada demonstrável começa no objetivo do cliente, passa pelo uso e pelas
preferências e termina no cenário financeiro opcional. O caminho histórico
continua sendo o padrão quando a composição multifator não é solicitada. Quando
ativada, a experiência aplica um único cenário a todas as alternativas
comparáveis e apresenta ranking, posição histórica, contribuições por critério,
origens e limitações antes de abrir o detalhe e a simulação do veículo.

Os estados da interface são explícitos: pronto para preencher, carregando,
resultado vazio, conflito de identidade, Gold indisponível e sucesso. Conflito
ou indisponibilidade nunca promove associação automática, não inventa nota zero
e não oculta o veículo do baseline. Mensagens apresentadas ao usuário são
sanitizadas; códigos técnicos permanecem no contrato auditável do backend. A
interface não calcula custo financeiro e não persiste formulário, pesos ou
resultado derivado.

As fontes continuam separadas por responsabilidade:

- o catálogo histórico fornece o baseline de recomendação;
- a Gold integrada elegível fornece a evidência publicada de FIPE, PBEV e ANP;
- o formulário fornece somente parâmetros do cliente;
- o backend produz a simulação e a composição multifator com `Decimal`;
- `mixed_1000_v1` aparece apenas como referência analítica publicada.

Limites visíveis incluem ausência ou ambiguidade de identidade Gold, falta de
evidência para um critério ponderado e indisponibilidade do dataset elegível.
Não há fallback para outra identidade, período, geografia, combustível ou
fonte, nem integração implícita com financiamento, BI ou escrita na Gold.

### Roteiro de demonstração (5–8 minutos)

1. **Contexto (30 s):** abrir a recomendação e explicar que o ranking histórico
   permanece disponível e que nenhuma preferência é salva.
2. **Necessidade (1 min):** preencher categoria, orçamento, limite mensal, forma
   de uso, prioridade, distância e preço de combustível.
3. **Cenário multifator (2 min):** ativar a comparação, informar divisão
   urbano/rodoviário, estratégia, geografia e semana ANP; explicar em linguagem
   simples o efeito de dois ou três pesos.
4. **Resultado (1–2 min):** calcular, mostrar quantidade comparada, posição
   histórica, nota multifator e reconciliação das contribuições.
5. **Evidência (1 min):** abrir os detalhes, identificar fonte publicada,
   limitações e um caso não disponível sem nota inventada.
6. **Simulação (1 min):** reutilizar o veículo no simulador do detalhe e mostrar
   que o backend calcula o custo sem alterar ranking ou dataset.
7. **Estado controlado (30 s):** apresentar um estado vazio, conflito ou
   indisponibilidade e destacar a ausência de fallback silencioso.

## Carpedia — especificações veiculares em shadow

A decisão de fonte é `SOURCE_APPROVED_WITH_RESTRICTIONS`. A integração usa
somente a [API oficial Carpedia v1](https://www.carpedia.com.br/desenvolvedores/docs),
em HTTPS e com chave recebida exclusivamente por `CARPEDIA_API_KEY`. A
autorização cobre consumo interno do produto; os
[Termos de Uso](https://www.carpedia.com.br/termos) exigem atribuição em
exibição pública e vedam redistribuição massiva que replique ou concorra com o
catálogo. Dados de terceiros preservam os respectivos direitos, e ausência de
campo não é interpretada como negativa. Por isso, esta etapa não expõe API,
frontend, recomendador, simulador, BI, financiamento ou orquestração.

O fluxo `carpedia_vehicle_specs_shadow` recebe alvos oficiais explícitos
`id:ano`, baixa apenas JSON de `/api/v1/ficha/{id}/{ano}`, preserva o payload
sanitizado e os hashes em Bronze, normaliza valores e unidades com `Decimal` em
Silver e publica em Gold somente identidades exatas e inequívocas. Ambíguos,
conflitantes, ausentes e pendentes permanecem auditáveis em Silver e nunca são
promovidos. Não há fuzzy matching, identificador fictício, baseline inventado
ou fallback silencioso.

O cliente aplica allowlist `www.carpedia.com.br`, autenticação Bearer fora de
parâmetros e logs, timeouts, retry limitado para falhas transitórias e `429`,
limite de 8 MiB conferido no `Content-Length` e durante streaming, JSON
obrigatório, SHA-256 e limpeza de parcial. O armazenamento é `database_json`;
arquivos temporários vivem somente no diretório temporário do sistema. O
dry-run é puro: não lê segredo, não abre banco, não adquire lock, não chama rede
e não grava arquivo.

A revision PostgreSQL-only `20260811_0011` sucede `20260811_0010`; SQLite é
no-op. Datasets, snapshots, resultados de qualidade e eventos são imutáveis,
a ativação shadow é atômica e o downgrade é bloqueado enquanto houver qualquer
histórico Carpedia. O head passa a ser `20260811_0011`.

## Bootstrap PostgreSQL local de demonstração da Gold integrada

`scripts/bootstrap_postgresql_demo_gold.py` prepara exclusivamente o banco
local `sigra_postgresql_demo`, já migrado até `20260811_0012`. O catálogo deve
ser materializado primeiro pelo modo dedicado, que vincula a sessão ao engine
PostgreSQL já validado, persiste os IDs explícitos de `SAMPLE_VEHICLES` em uma
única transação e só informa sucesso depois de reler os 34 IDs no próprio alvo:

```powershell
.\backend\.venv\Scripts\python.exe scripts\bootstrap_postgresql_demo_gold.py --bootstrap-catalog --acknowledge-synthetic-demo
```

O comando recusa SQLite, host diferente de `127.0.0.1`, outra porta ou banco,
catálogo parcial, IDs extras ou identidades divergentes. Ele não usa o engine
global de `app.database`, não depende do fallback SQLite e não altera
motocicletas ou outros registros. Após essa pós-condição, a materialização das
fontes exige confirmação explícita:

```powershell
.\backend\.venv\Scripts\python.exe scripts\bootstrap_postgresql_demo_gold.py --acknowledge-synthetic-demo
```

A FIPE é reproduzida somente do cache versionado com 34 registros `live`, sem
reescrever o cache. Como os seis PDFs PBEV e o CSV ANP oficiais não fazem parte
do repositório, as duas fontes usam fixtures mínimas com proveniência
`demo_fixture`, URLs no domínio reservado `demo.invalid` e indicação
`official_evidence=false`. PBEV mantém `metadata_only`, não persiste PDF e usa
uma referência metodológica que declara expressamente a natureza sintética. A
ANP não inventa CNPJ e mantém gasolina comum, aditivada e etanol separados.
Esses dados servem somente à demonstração local e não podem ser citados como
evidência oficial.

O bootstrap executa duas vezes FIPE Bronze/Silver/Gold, PBEV shadow, ANP shadow
e Gold integrada para provar deduplicação. A matriz PBEV continua sujeita ao
gate 18/6/3/3/4; a ANP continua sujeita aos hard gates de produtos essenciais;
a Gold integrada continua sujeita aos 29 hard gates e sete controles
`not_calibrated`. A requisição demonstrativa usa a semana `2026-08-03` e o grão
municipal exato `SP:SAO PAULO`. Carpedia não é executada porque não é uma fonte
do contrato integrado FIPE + PBEV + ANP.

Backend e frontend só podem ser iniciados depois que a própria validação do
script confirmar um único dataset integrado ativo e elegível e registros em
`gold.integrated_vehicle_cost_consumption_v1`. A conferência posterior, sem
novas escritas, é:

```powershell
.\backend\.venv\Scripts\python.exe scripts\bootstrap_postgresql_demo_gold.py --validate-only
```
