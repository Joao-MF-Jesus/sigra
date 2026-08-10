# Plataforma de dados — Etapa 5

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
