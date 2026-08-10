# SIGRA — Arquitetura Medalhão e Contratos de Dados

**Status:** proposta técnica aprovada para implementação incremental
**Baseline preservada:** `Sigra.Beckup2.zip`
**Branch da baseline:** `deploy/homologation`
**Commit da baseline:** `9e82f35c2ccb0033a640a9062e3c9ee5b5d5ef8d`
**Escopo desta etapa:** projetar a plataforma de dados sem alterar o funcionamento atual do SIGRA.

## 1. Decisão arquitetural

O SIGRA continuará sendo uma aplicação transacional com FastAPI, React e PostgreSQL. A arquitetura medalhão será adicionada ao mesmo PostgreSQL por meio de schemas independentes, permitindo evolução gradual e rollback simples.

Schemas definidos:

| Schema | Responsabilidade | Escrita principal |
|---|---|---|
| `public` | Sistema operacional atual | FastAPI e Alembic |
| `bronze` | Dados externos brutos e imutáveis | Processos de ingestão |
| `silver` | Dados normalizados, reconciliados e históricos | Transformações controladas |
| `gold` | Produtos de dados prontos para consumo | Transformações publicadas |
| `meta` | Execuções, versões, rejeições e qualidade | Pipeline e testes |

Decisões:

- A primeira fonte implementada será a FIPE.
- Não haverá reescrita imediata das tabelas atuais.
- O schema `public` continuará funcionando durante toda a migração.
- O recomendador continuará calculando a Nota SIGRA em tempo de requisição.
- A camada Gold fornecerá atributos do veículo, não uma nota universal.
- O financiamento continuará stateless e fora da medalhão.
- Spark, Kafka, Hadoop e Kubernetes estão fora do escopo inicial.
- PostgreSQL é suficiente para o volume e para os objetivos atuais.

## 2. Separação entre dados operacionais e dados analíticos

### Permanecem operacionais em `public`

- `users`
- `user_vehicles`
- `expenses`
- `maintenances`
- configurações da aplicação
- ações administrativas
- simulações de financiamento, enquanto permanecerem stateless

Essas estruturas não serão movidas para Bronze, Silver ou Gold. Quando necessário, seus eventos poderão alimentar modelos analíticos sem deixar de ser operacionais.

### Passam a ser alimentados pela plataforma de dados

- catálogo e identidade de veículos;
- preços FIPE e seu histórico;
- fichas técnicas;
- consumo de referência;
- custos de manutenção estimados;
- peças, fornecedores e preços;
- depreciação e outros indicadores temporais;
- confiança, cobertura e atualidade dos dados.

### Tratamento das tabelas atuais

| Estrutura atual | Destino arquitetural |
|---|---|
| `vehicles` | Mantida durante a transição; futuramente substituída na leitura por uma view Gold compatível |
| `motorcycles` | Mantida; identidade e campos legados serão gradualmente reconciliados na Silver |
| `motorcycle_data_sources` | Referência para o desenho de linhagem e evidência das demais fontes |
| `motorcycle_objective_specifications` | Candidata a fonte Silver para especificações objetivas |
| `motorcycle_derived_metrics` | Candidata a produto Gold após validação do método |
| `motorcycle_economic_estimates` | Candidata a fato histórico Silver e produto Gold atual |
| `fuel_consumption_reports` | Evento operacional que poderá gerar agregações Silver/Gold |
| `vehicle_reports` | Evento operacional que poderá alimentar indicadores de confiabilidade |
| `parts`, `suppliers`, `part_prices` | Futuras dimensões e fatos históricos Silver |
| `sample_data.py` | Mantido somente para testes, demonstração e desenvolvimento local |

## 3. Fluxo inicial da FIPE

```text
API FIPE
   ↓
meta.pipeline_run
   ↓
bronze.fipe_raw
   ↓
silver.vehicle_identity
   ↓
silver.vehicle_source_mapping
   ↓
silver.vehicle_price_history
   ↓
gold.vehicle_features_current
   ↓
FastAPI → Recomendador → React
```

O backend não fará coleta externa durante uma requisição de recomendação. A aplicação lerá apenas dados já publicados na Gold.

## 4. Contrato `meta.pipeline_run`

Registra uma execução completa ou parcial do pipeline.

| Campo | Tipo sugerido | Regra |
|---|---|---|
| `pipeline_run_id` | UUID | Chave primária |
| `pipeline_name` | VARCHAR(100) | Ex.: `fipe_vehicle_prices` |
| `pipeline_version` | VARCHAR(40) | Versão do código de ingestão |
| `dataset_version` | VARCHAR(80) | Identifica a publicação resultante |
| `trigger_type` | VARCHAR(20) | `manual`, `scheduled`, `retry` ou `backfill` |
| `status` | VARCHAR(20) | `running`, `succeeded`, `failed`, `partial` ou `rejected` |
| `started_at` | TIMESTAMPTZ | Obrigatório e em UTC |
| `finished_at` | TIMESTAMPTZ | Nulo enquanto estiver executando |
| `source_reference` | VARCHAR(160) | Referência mensal ou versão da fonte |
| `records_received` | INTEGER | Não negativo |
| `records_inserted` | INTEGER | Não negativo |
| `records_deduplicated` | INTEGER | Não negativo |
| `records_rejected` | INTEGER | Não negativo |
| `error_summary` | TEXT | Sem credenciais ou payload sensível |
| `git_commit` | VARCHAR(40) | Commit que executou o pipeline |
| `created_at` | TIMESTAMPTZ | Gerado pelo banco |

Regras:

- Toda linha Bronze deve apontar para um `pipeline_run_id`.
- Uma execução só pode publicar na Gold se os testes críticos forem aprovados.
- `finished_at` deve ser posterior ou igual a `started_at`.
- Uma execução `succeeded` não pode possuir contagens negativas nem permanecer sem `finished_at`.

## 5. Contrato `bronze.fipe_raw`

Armazena a resposta recebida sem alterar seus valores.

| Campo | Tipo sugerido | Regra |
|---|---|---|
| `fipe_raw_id` | BIGINT | Chave primária |
| `pipeline_run_id` | UUID | FK para `meta.pipeline_run` |
| `source_name` | VARCHAR(80) | Nome explícito do provedor |
| `source_endpoint` | TEXT | Endpoint consultado sem credenciais |
| `vehicle_type` | VARCHAR(20) | `car`, `motorcycle` ou `truck` |
| `source_record_key` | VARCHAR(160) | Identidade retornada pela fonte |
| `fipe_code` | VARCHAR(20) | Pode ser nulo se a resposta não o fornecer |
| `year_code` | VARCHAR(30) | Preserva combustível e ano informados pela fonte |
| `reference_month_raw` | VARCHAR(80) | Valor original da fonte |
| `http_status` | INTEGER | Status da coleta |
| `collected_at` | TIMESTAMPTZ | Momento real da coleta em UTC |
| `payload` | JSONB | Payload completo e não transformado |
| `payload_hash` | CHAR(64) | SHA-256 canônico do payload |
| `schema_fingerprint` | CHAR(64) | Assinatura da estrutura recebida |
| `ingestion_status` | VARCHAR(20) | `received`, `duplicate`, `invalid_json` ou `http_error` |
| `created_at` | TIMESTAMPTZ | Gerado pelo banco |

Chaves e índices:

- PK em `fipe_raw_id`.
- Índice em `pipeline_run_id`.
- Índice em `(fipe_code, year_code, collected_at)`.
- Restrição única sugerida em `(source_name, payload_hash)` para impedir duplicação idêntica.

Regras:

- Bronze é append-only.
- Correções nunca sobrescrevem o payload original.
- Uma nova coleta igual pode ser registrada como duplicada sem publicar outra versão na Silver.
- Erro de parsing permanece registrado e não segue para transformação.
- Ausência de campo não deve ser convertida em zero, texto vazio ou data atual.

## 6. Contrato `silver.vehicle_identity`

Representa a identidade canônica do veículo, independente da fonte.

| Campo | Tipo sugerido | Regra |
|---|---|---|
| `vehicle_sk` | BIGINT | Chave substituta e estável |
| `vehicle_type` | VARCHAR(20) | Inicialmente `car` |
| `brand_name` | VARCHAR(80) | Nome normalizado |
| `model_name` | VARCHAR(120) | Nome normalizado |
| `version_name` | VARCHAR(180) | Versão normalizada |
| `model_year` | SMALLINT | Faixa válida definida por contrato |
| `fuel_type` | VARCHAR(30) | Vocabulário controlado |
| `transmission_type` | VARCHAR(30) | Nulo quando desconhecido |
| `canonical_key` | CHAR(64) | Hash da identidade lógica normalizada |
| `valid_from` | TIMESTAMPTZ | Início da validade da versão |
| `valid_to` | TIMESTAMPTZ | Nulo para a versão vigente |
| `is_current` | BOOLEAN | Apenas uma versão atual por identidade |
| `created_by_run_id` | UUID | Execução que criou a versão |
| `updated_by_run_id` | UUID | Execução que atualizou a versão |

Identidade lógica inicial:

```text
vehicle_type + brand_name + model_name + version_name + model_year + fuel_type
```

Regras:

- Não usar o `vehicle_id` atual como identidade externa.
- Diferenças apenas de caixa, acento ou espaço não criam outro veículo.
- Diferenças reais de versão, motorização, ano ou combustível devem permanecer separadas.
- Alterações de identidade exigem nova versão ou reconciliação auditável.
- Duplicidades ambíguas são enviadas para rejeição, nunca mescladas silenciosamente.

## 7. Contrato `silver.vehicle_source_mapping`

Relaciona a identidade canônica às identidades de cada fonte.

| Campo | Tipo sugerido | Regra |
|---|---|---|
| `mapping_id` | BIGINT | Chave primária |
| `vehicle_sk` | BIGINT | FK para `silver.vehicle_identity` |
| `source_name` | VARCHAR(80) | Ex.: FIPE |
| `vehicle_type` | VARCHAR(20) | `car`, `motorcycle` ou `truck` |
| `source_vehicle_key` | VARCHAR(160) | Identidade original da fonte |
| `fipe_code` | VARCHAR(20) | Código FIPE quando aplicável |
| `year_code` | VARCHAR(30) | Código de ano/combustível |
| `mapping_status` | VARCHAR(20) | `matched`, `pending`, `ambiguous`, `rejected` |
| `match_method` | VARCHAR(30) | `manual`, `exact`, `rule`, `reviewed` |
| `confidence` | NUMERIC(5,2) | Entre 0 e 100 |
| `valid_from` | TIMESTAMPTZ | Início da validade |
| `valid_to` | TIMESTAMPTZ | Nulo quando vigente |
| `pipeline_run_id` | UUID | Execução responsável |
| `review_notes` | TEXT | Obrigatório para decisões manuais ou ambíguas |

Regras:

- A identidade da fonte é `source_name + vehicle_type + source_vehicle_key`.
- A combinação FIPE `source_name + vehicle_type + fipe_code + year_code` deve possuir no máximo um mapeamento vigente.
- O tipo é materializado pela linhagem Bronze e não inferido por código, cache ou ID legado.
- Mapeamento ambíguo não publica preço na Gold.
- Revisão manual deve preservar a justificativa.
- O pareamento dos 34 automóveis atuais será migrado dos perfis fixos para esta tabela.

## 8. Contrato `silver.vehicle_price_history`

Mantém o histórico temporal dos preços por veículo e fonte.

| Campo | Tipo sugerido | Regra |
|---|---|---|
| `vehicle_price_id` | BIGINT | Chave primária |
| `vehicle_sk` | BIGINT | FK para identidade canônica |
| `source_name` | VARCHAR(80) | Fonte do preço |
| `source_mapping_id` | BIGINT | FK para o mapeamento utilizado |
| `price_amount` | NUMERIC(14,2) | Maior que zero |
| `currency` | CHAR(3) | Inicialmente `BRL` |
| `reference_month` | DATE | Primeiro dia do mês de referência |
| `collected_at` | TIMESTAMPTZ | Momento da coleta |
| `valid_from` | TIMESTAMPTZ | Início da vigência interna |
| `valid_to` | TIMESTAMPTZ | Nulo para registro vigente |
| `is_current` | BOOLEAN | Somente um atual por veículo/fonte |
| `data_confidence` | NUMERIC(5,2) | Qualidade da evidência, não do veículo |
| `bronze_record_id` | BIGINT | Linhagem até o payload bruto |
| `pipeline_run_id` | UUID | Execução que produziu a linha |

Regras:

- Nunca atualizar destrutivamente preços históricos.
- Mudança de mês ou preço cria nova linha e encerra a anterior.
- Mesma fonte, referência, veículo e preço não cria uma nova versão sem motivo.
- Preço inválido ou sem mapeamento é rejeitado.
- Valores monetários usam `NUMERIC`, nunca `FLOAT`.

## 9. Contrato `meta.data_quality_issue`

Registra falhas ou alertas detectados durante ingestão e transformação.

| Campo | Tipo sugerido | Regra |
|---|---|---|
| `issue_id` | BIGINT | Chave primária |
| `pipeline_run_id` | UUID | Execução relacionada |
| `layer_name` | VARCHAR(20) | `bronze`, `silver` ou `gold` |
| `entity_name` | VARCHAR(100) | Tabela ou modelo afetado |
| `record_reference` | VARCHAR(200) | Referência segura do registro |
| `rule_code` | VARCHAR(80) | Código estável da regra |
| `severity` | VARCHAR(20) | `info`, `warning`, `error`, `critical` |
| `message` | TEXT | Explicação sem dados sensíveis |
| `details` | JSONB | Evidência estruturada |
| `resolution_status` | VARCHAR(20) | `open`, `accepted`, `resolved`, `ignored` |
| `created_at` | TIMESTAMPTZ | Gerado pelo banco |
| `resolved_at` | TIMESTAMPTZ | Nulo enquanto aberto |

Falhas críticas bloqueiam publicação na Gold. Alertas podem permitir publicação, desde que sejam contabilizados no relatório da execução. `resolved_at` é nulo somente para issues `open`; `accepted`, `resolved` e `ignored` exigem timestamp de resolução e preservação da auditoria.

## 10. Contrato Gold Vehicle Features v1

A primeira Gold é um dataset físico versionado, não uma leitura operacional. Ela é formada por:

- `gold.vehicle_feature_dataset`: cabeçalho, fingerprint, contagens, cobertura e estado de ativação;
- `gold.vehicle_features_snapshot`: linhas imutáveis por `dataset_version + vehicle_sk`;
- `gold.vehicle_feature_dataset_activation`: eventos imutáveis de ativação, substituição e rollback;
- `gold.vehicle_features_current`: view do único dataset ativo.

O escopo v1 é exclusivamente `vehicle_type = 'car'` e fonte `Tabela FIPE via API Parallelum`. O pipeline lê somente Silver e Meta.

O cabeçalho registra `expected_vehicle_count`, `published_vehicle_count`, `blocked_vehicle_count`, cobertura `NUMERIC(5,2)`, competência mínima e máxima, fingerprint SHA-256 e o último evento de ativação. O banco garante `blocked = expected - published`, cobertura mínima de 80%, numerador positivo e no máximo um dataset ativo.

O snapshot preserva identidade, mapping, preço, código FIPE, `year_code` integral e runs Silver e Gold. Consumo, manutenção, seguro, confiabilidade, peças, depreciação, categoria, segmento e scores não pertencem ao contrato v1 e não são fabricados.

Freshness é dinâmica na view:

- `current`: até 45 dias;
- `stale`: de 46 a 90 dias;
- `expired`: acima de 90 dias.

O snapshot armazena `base_quality_status`. A view só retorna `quality_status = 'passed'` quando a base é `passed` e o preço está `current`; qualquer warning original, dado stale ou expirado resulta em `warning`. Dados expirados permanecem visíveis.

Mappings `pending`, `ambiguous` e `rejected` entram no denominador, não no snapshot, e recebem issue primária `GOLD_MAPPING_BLOCKED`. Crítica Silver aberta e não atribuível sem Bronze é bloqueio global. O pipeline Gold nunca consulta Bronze, cache, `public.vehicles` ou IDs 1–34.

Publicação e rollback usam lock consultivo, isolamento `REPEATABLE READ` e transação atômica. Snapshots e eventos são protegidos por triggers contra `UPDATE` e `DELETE`. Repetir o fingerprint do dataset ativo é idempotente e não cria outro snapshot ou evento.

A Nota SIGRA, o TCO personalizado e o ranking continuam fora da Gold e não são alterados nesta etapa.

## 11. Contrato da API após integração

A resposta de recomendação manterá os campos atuais e acrescentará:

```json
{
  "algorithm_version": "2.1.2",
  "weights_version": "cars-v1",
  "dataset_version": "fipe-AAAA-MM-run-<id>",
  "pipeline_run_id": "uuid",
  "data_reference": "AAAA-MM-01",
  "data_freshness": {
    "status": "current",
    "published_at": "ISO-8601",
    "oldest_required_source_at": "ISO-8601"
  }
}
```

Regras de compatibilidade:

- Campos novos serão inicialmente opcionais.
- O contrato anterior continuará válido durante a transição.
- Uma feature flag permitirá alternar entre catálogo legado e Gold.
- O fallback não poderá mascarar falha da Gold como dado atualizado.
- A API declarará explicitamente quando usar dado demonstrativo ou legado.

## 12. Regras mínimas de qualidade para a primeira entrega

### Bronze

- payload deve ser JSON válido;
- `pipeline_run_id` deve existir;
- `collected_at` é obrigatório;
- `payload_hash` deve possuir 64 caracteres hexadecimais;
- status HTTP fora de 2xx não segue para Silver;
- estrutura inesperada gera `schema_fingerprint` novo e alerta.

### Silver

- preço maior que zero;
- moeda igual a `BRL` na primeira versão;
- ano dentro de uma faixa plausível;
- código FIPE e código de ano preservados;
- nenhuma duplicidade vigente de identidade ou mapeamento;
- nenhum `vehicle_sk` órfão;
- nenhuma média silenciosa em caso de fontes conflitantes;
- registros ambíguos são rejeitados ou enviados para revisão.

### Gold

- uma linha por `dataset_version + vehicle_sk` e uma view do dataset ativo;
- `dataset_version`, runs de linhagem e fingerprint obrigatórios;
- linhagem completa;
- cobertura mínima de 80% com `NUMERIC`, nunca `FLOAT`;
- bloqueados reconciliados com issues seguras;
- nenhum preço demonstrativo rotulado como FIPE;
- nenhuma ativação se houver falha crítica global;
- snapshot imutável e freshness calculada dinamicamente.

## 13. Idempotência e reprocessamento

- Reexecutar a mesma coleta não deve duplicar payload idêntico.
- Reexecutar a transformação sobre a mesma Bronze deve produzir o mesmo resultado.
- Correção de regra gera nova `pipeline_version` e novo `dataset_version`.
- Backfill utiliza `trigger_type = backfill` e não substitui registros brutos.
- Publicação Gold é atômica: ou a nova versão fica disponível integralmente ou a anterior permanece ativa.
- A versão anterior da Gold deve continuar identificável para rollback.

## 14. Versionamento

O SIGRA passará a separar quatro tipos de versão:

| Versão | Exemplo | Responsabilidade |
|---|---|---|
| Algoritmo | `2.1.2` | Regras de recomendação |
| Pesos | `cars-v1` | Pesos do algoritmo |
| Pipeline | `fipe-ingestion-v1` | Extração e transformação |
| Dataset | `fipe-AAAA-MM-run-<id>` | Dados efetivamente usados |

Essa separação permite explicar se uma mudança de ranking foi causada pelo algoritmo, pelos pesos ou pela atualização dos dados.

## 15. Estratégia de integração sem quebra

1. Criar schemas e tabelas novas por Alembic.
2. Manter o `public.vehicles` inalterado.
3. Executar o pipeline FIPE manualmente.
4. Validar Bronze, Silver e Gold.
5. Criar `legacy_vehicle_id` apenas como ponte transitória.
6. Adaptar o repositório para aceitar uma fonte de catálogo configurável.
7. Habilitar a Gold em ambiente de teste.
8. Comparar quantidade, preço, ranking e contratos com a baseline.
9. Habilitar em homologação.
10. Remover o refresh FIPE do ciclo da FastAPI somente após estabilização.

## 16. Estrutura de pastas planejada

```text
data_platform/
├── common/
│   ├── config.py
│   ├── database.py
│   └── logging.py
├── contracts/
│   └── fipe.py
├── ingestion/
│   └── fipe/
│       ├── client.py
│       ├── extractor.py
│       └── loader.py
├── orchestration/
│   └── flows/
│       └── fipe_flow.py
├── quality/
│   ├── bronze_checks.py
│   ├── silver_checks.py
│   └── gold_checks.py
└── tests/

dbt/
├── models/
│   ├── silver/
│   └── gold/
├── tests/
├── macros/
└── dbt_project.yml
```

O orquestrador será introduzido somente depois de o fluxo manual estar validado. A primeira implementação pode usar funções Python e SQL/dbt executadas por comando único.

## 17. Critérios de conclusão da Etapa 2

- schemas e responsabilidades definidos;
- fronteira operacional versus analítica definida;
- contratos Bronze, Silver, Gold e Meta definidos;
- chaves e identidade externa definidas;
- política de histórico e idempotência definida;
- regras mínimas de qualidade definidas;
- estratégia de compatibilidade e rollback definida;
- primeiro recorte limitado à FIPE.

Com este documento, a Etapa 2 está projetada. A próxima etapa é criar as migrations dos schemas `meta`, `bronze`, `silver` e `gold` e implementar a ingestão Bronze da FIPE, mantendo a aplicação atual desligada desse novo fluxo até a validação.

## 18. Etapa 6 — Orquestração da plataforma

A orquestração coordena o fluxo já validado sem incorporar suas regras:

```text
CLI ou scheduler
      |
      v
runner independente -----> meta.orchestration_run
      |                    meta.orchestration_step_run
      +--> Bronze FIPE ---> meta.pipeline_run
      +--> Silver FIPE ---> meta.pipeline_run
      +--> Gold features -> meta.pipeline_run
```

O runner chama as APIs Python públicas das camadas na ordem Bronze → Silver →
Gold. Ele não executa subprocessos e não é importado por FastAPI, recomendador,
frontend ou BI. O adaptador Prefect depende do runner; o runner nunca depende de
Prefect. Assim, outro scheduler pode substituir Prefect implementando somente a
fronteira de dispatch, sem alterar ingestão, transformação ou publicação.

### 18.1 Metadados e estados

`meta.orchestration_run` representa a intenção idempotente do fluxo e registra
nome/versão, gatilho manual/agendado, etapa inicial, parâmetros sanitizados,
heartbeat, resultado e tempos. A unicidade de `flow_name + idempotency_key`
impede duas materializações da mesma intenção.

`meta.orchestration_step_run` é o histórico append-only das tentativas. Cada
linha identifica Bronze, Silver ou Gold, sua dependência, tentativa, status,
tempos, métricas resumidas e a FK para o `meta.pipeline_run` criado pela camada.
Falha antes da criação do pipeline permite FK nula sem perder a evidência da
tentativa.

Os dois contratos usam o mesmo conjunto de estados:

```text
pending -> running -> succeeded
                   -> partial
                   -> failed
                   -> skipped
                   -> cancelled
```

Constraints asseguram tempos coerentes, tentativas positivas e estado terminal
com `finished_at`. Triggers atualizam `updated_at`. A migration
`20260810_0005` é PostgreSQL-only, no-op em SQLite e regride isoladamente para
`20260803_0004`.

### 18.2 Dependências, partial e retomada

- Bronze com falha definitiva causa skip de Silver; esse skip bloqueia Gold.
- Silver com falha definitiva causa skip de Gold.
- `partial=continue` permite seguir, mas o resultado do fluxo permanece
  `partial`; `stop` interrompe dependentes; `fail` também classifica o fluxo
  como falha.
- Execução iniciada explicitamente em Silver ou Gold registra as etapas
  anteriores como skipped por escolha, não como falha de dependência.
- Retomada reutiliza etapas `succeeded`/`partial` e cria nova tentativa somente
  para a primeira etapa incompleta. Isso preserva a idempotência interna das
  camadas e evita repetir transformações concluídas.
- Um run `running` com heartbeat recente é considerado ativo; após o limite de
  staleness, pode ser recuperado sob o mesmo lock e a mesma chave.

### 18.3 Retry, timeout, concorrência e cancelamento

Falhas de transporte, timeout e conexão são transitórias; violação de contrato
e resultados definitivos não recebem retry automático. A política limita
tentativas e aplica backoff exponencial. O timeout no core é cooperativo para
não abandonar uma thread que ainda possa escrever; tasks Prefect adicionam um
limite operacional externo e devolvem timeout ao mesmo classificador do runner.

Um advisory lock PostgreSQL por fluxo impede execuções Bronze/Silver/Gold
incompatíveis em paralelo. Cancelamento é observado antes de cada etapa e
tentativa; o estado é persistido antes de liberar o lock.

### 18.4 Observabilidade e segurança

Os metadados permitem correlacionar `orchestration_run_id`, etapa, tentativa,
duração, status e `pipeline_run_id`. Métricas whitelisted incluem recebidos,
inseridos, deduplicados, rejeitados, publicados, bloqueados, cobertura e
freshness quando o pipeline a fornecer.

Parâmetros, erros e métricas passam por sanitização e limite de tamanho. Campos
como payload, body, URL, senha, token e secret são redigidos. Não há cópia de
payload FIPE nem armazenamento da URL de banco.

### 18.5 Prefect e agenda

O adaptador constrói um flow local e tasks Bronze, Silver e Gold com import
tardio. Prefect permanece dependência opcional do runtime de dados e não entra
nas dependências do backend. Os testes usam executores falsos e decorators
locais, sem API, servidor ou chamadas externas. Em operação, schedule,
deployment e infraestrutura Prefect ficam fora do repositório e apenas invocam
o flow parametrizado.

### 18.6 Rollback e limites de integração

Rollback de dataset continua sendo executado pelo contrato Gold existente. O
downgrade da Etapa 6 remove somente tabelas, enums, índices e triggers de
orquestração; não altera dados Bronze/Silver/Gold nem runs de pipeline. A etapa
não muda a fonte atual do backend, não agenda automaticamente um deployment e
não liga a plataforma ao ciclo de vida da aplicação.
