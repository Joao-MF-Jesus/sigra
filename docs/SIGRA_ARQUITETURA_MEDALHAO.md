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

## 19. Etapa 7B — PBE Veicular interno e Gold shadow

A integração PBE Veicular é um ramo analítico separado do fluxo FIPE:

```text
ativos oficiais externos
        |
        v
bronze.pbev_source_asset + bronze.pbev_raw_row
        |
        v
silver.pbev_vehicle_mapping -> silver.vehicle_efficiency_observation
        |
        v
gold.vehicle_efficiency_dataset -> gold.vehicle_efficiency_snapshot
                                -> gold.vehicle_efficiency_quality_result
```

Não existe aresta para FastAPI, frontend, recomendador, financiamento, BI,
`gold.vehicle_feature_dataset` ou `gold.vehicle_features_current`. O resultado é
somente `shadow_published`, nunca uma fonte ativa do SIGRA. Falha nesse ramo não
interrompe nem reverte Bronze, Silver ou Gold FIPE.

### 19.1 Fonte, licença e armazenamento

O contrato aceita somente os seis ativos oficiais do Inmetro auditados para os
ciclos 2017–2022. URL oficial HTTPS, MIME, assinatura PDF, tamanho, páginas,
SHA-256, layout, licença e atribuição são gates anteriores à transformação. Um
novo hash é um novo ativo em quarentena, exige validação de layout e não herda o
baseline automaticamente.

Nesta etapa, `storage_mode=metadata_only` e `document_bytes=NULL` são
obrigatórios. Os PDFs ficam fora do repositório e do ZIP; não há redistribuição
de documentos ou linhas transformadas. A proveniência registra Inmetro/PBE
Veicular, `CC-BY-ND-3.0` e URL da licença. Exposição futura depende de revisão
jurídica de finalidade, atribuição, armazenamento e redistribuição.

### 19.2 Parser e semântica

`pbev-pdf-v1` implementa quatro famílias: `pbev-l1-2017-2019-v1`,
`pbev-l2-2020-v1`, `pbev-l3-2021-v1` e `pbev-l4-2022-v1`. A grade vetorial é o
único caminho automaticamente aceito. Texto posicionado é fallback restrito a
layout conhecido e coloca o ativo em revisão; OCR automático é proibido.
Layout/unidade desconhecidos e páginas incompletas bloqueiam Silver e Gold.

Valores brutos e células normalizadas preservam a evidência. `-`, `\` e vazio
viram `NULL`; ausência nunca vira zero. Conversões usam `Decimal`. Até 2021,
NMHC, CO e NOx são grandezas em g/km; em 2022, NMOG+NOx, CO e CHO são grandezas
em mg/km. O modelo não funde NMHC com NMOG+NOx, e toda conversão equivalente
mantém valor/unidade de origem e versão da transformação.

### 19.3 Matching, histórico e baseline

`pbev-match-v1` pontua marca 10, modelo 20, ciclo 10, versão 20, motor 15,
transmissão 10, combustível/propulsão 10 e carroceria 5. Conflitos materiais são
eliminatórios. Um único líder compatível com pontuação >=95 pode ser `matched`;
múltiplos líderes semanticamente equivalentes também podem ser `matched` quando
suas métricas materiais são idênticas. A faixa de 75–94 é `pending` quando ainda
não existe evidência suficiente para um match seguro. Líderes com identidades
semânticas diferentes ou métricas materiais divergentes permanecem
`ambiguous`; conflito de catálogo é `rejected`; e ausência é `not_found`. Só
`matched` possui `vehicle_sk` Silver real, gera observação e pode ser publicado.
Decisões `pending`, `ambiguous`, `rejected` ou `not_found` nunca são publicadas.
Decisões são imutáveis/append-only; revisão cria uma decisão que referencia a
anterior por `supersedes_mapping_id`.

O baseline de 34 identidades é contextual aos seis hashes, parser, matcher e
catálogo auditados. Duas materializações idempotentes no PostgreSQL local
descartável revisaram formalmente o baseline para 18 matched, 6 ambiguous, 3
rejected, 3 not_found e 4 pending (52,94%). As referências 19, 20 e 22 foram
rebaixadas de matched para pending por ausência de evidência suficiente de
transmissão; a referência 33 permaneceu pending. A revisão é governança de
qualidade baseada em evidência reproduzível, não relaxamento arbitrário.
Regressão abaixo de 18 bloqueia o shadow, e aumento acima de 18 exige evidência
de revisão registrada. Comfort/Vision, Attractive/Drive e as demais
ambiguidades auditadas não são corrigidas silenciosamente.

### 19.4 Gold shadow, qualidade e operação

Cada publicação cria dataset físico imutável em `building`; depois dos gates,
ele substitui atomicamente o último `shadow_published`, que passa a `retired`.
Uma impressão digital idempotente cobre hashes, parser, matcher, mappings e
linhagem. O último shadow válido permanece em caso de falha. Nunca se publica
dataset vazio, identidade duplicada ou decisão não matched.

Os gates registram origem, hash, MIME, páginas, layout, parser, unidades,
contagens, estados, linhagem, unicidade, baseline, licença e atribuição. O ramo
executa APIs Python diretamente, sem subprocessos. Locks `pbev:<cycle_year>`,
heartbeat, cancelamento e timeout usam checkpoints seguros. Retry automático é
restrito a timeout/TLS transitório, 408, 429 e 5xx e respeita `Retry-After`;
falhas permanentes de hash/layout/unidade não recebem retry cego. Dry-run não
resolve ativos, não importa o parser PDF, não abre banco, não chama rede e não
escreve.

Os testes padrão usam somente estruturas sintéticas mínimas e não chamam rede.
Validação com documentos oficiais depende de `PBEV_TEST_ASSET_DIR` externo. O
teste PostgreSQL depende de `DATA_PLATFORM_TEST_POSTGRESQL_URL` apontando para
banco descartável terminado em `_test`. A migration `20260810_0006` é
PostgreSQL-only e no-op em SQLite; seu downgrade bloqueia um shadow ativo e,
quando seguro, retorna isoladamente a `20260810_0005`.

## 20. Etapa 8B1 — preços de combustíveis ANP em Gold shadow

A fundação ANP é um ramo analítico independente e manual:

```text
download oficial de dataset CSV em www.gov.br
        |
        v
bronze.anp_source_asset -> bronze.anp_fuel_price_raw
        |
        v
silver.anp_fuel_price_observation_current
        |
        v
gold.anp_fuel_price_dataset -> gold.anp_fuel_price_snapshot
                            -> gold.anp_fuel_price_quality_result
```

Não há aresta de dados para PBEV, FastAPI, recomendador, frontend,
financiamento, BI ou Gold FIPE. A Etapa 8B2 acrescenta somente a coordenação da
API Python pública pelo runner analítico, após o piloto PostgreSQL descartável;
o produto continua shadow e isolado dos consumidores operacionais.

### 20.1 Origem, transporte e Bronze

A fonte é o download oficial do CSV móvel de gasolina e etanol publicado pela
ANP, não uma API. O contrato exige HTTPS, allowlist inicial `www.gov.br`,
redirect no mesmo host, status e MIME CSV válidos, rejeição de HTML, streaming,
SHA-256 e tamanho calculados durante a leitura. Retry é limitado a timeout, 408,
429 e 5xx. O limite operacional inicial é 32 MiB, aproximadamente quatro vezes
o asset de 7.908.850 bytes observado no piloto. `Content-Length` acima desse
limite é rejeitado, mas não é a única defesa: o contador do stream interrompe a
transferência ao ultrapassar o limite e o parcial é removido. O limite fica
sujeito a revisão após novos pilotos. URL autenticada, conteúdo e parâmetros
sensíveis não entram em logs ou erros.

`storage_mode=metadata_only` é invariável. Os bytes originais existem somente
em arquivo no diretório temporário do sistema durante o parsing e são removidos
em sucesso ou falha. Nenhum CSV ou ZIP é persistido no banco ou repositório. A
tabela de asset conserva página oficial, URL sanitizada, período, horário UTC,
metadados HTTP, tamanho, hashes e fingerprint; a tabela de raw conserva as
linhas parseadas em JSONB, com número, parser e linhagem. Ambas são append-only.

O parser aceita ponto e vírgula e UTF-8 com ou sem BOM, únicos encodings
comprovados no piloto. O header completo e ordenado participa do schema
fingerprint. Qualquer coluna ausente, extra, desconhecida ou reordenada é layout
drift, coloca o asset em quarentena e bloqueia Silver e Gold. Valores monetários
são `Decimal` desde o parsing; `float` não participa do fluxo.

### 20.2 Silver, identidade e privacidade

O vocabulário distingue `gasoline_c_common`, `gasoline_c_additized` e
`ethanol_hydrated`; eles nunca são consolidados ou escolhidos automaticamente.
`gasoline_c_common` e `ethanol_hydrated` são essenciais para este recurso.
`gasoline_c_additized` permanece reconhecida, processada, separada e opcional.
Diesel B S500/S10, GNV e GLP P13 são reconhecíveis, mas bloqueados por estarem
fora do recurso atual. UF, região, unidade, data e preços são hard gates. Não se
inventa código IBGE.

CNPJ bruto permanece somente na Bronze restrita. A Silver guarda hash
determinístico e usa fallback de identidade controlado, com issue sanitizada,
quando o CNPJ é ausente ou inválido. Issues e erros nunca contêm CNPJ, razão
social ou endereço. A Gold não contém nenhum desses campos nem payload Bronze.

Observações Silver são imutáveis. Mesma chave e conteúdo deduplicam; conteúdos
divergentes para a mesma chave dentro do asset formam conflito. Uma correção em
asset posterior insere nova observação com `supersedes_observation_id`, preserva
o histórico e abre issue crítica para revisão. A view corrente é derivada por
ausência de sucessor, sem update ou delete do histórico.

### 20.3 Agregação, qualidade e publicação

O snapshot tem grão de dataset, produto, semana e nível geográfico municipal ou
estadual. Média, mediana, mínimo, máximo, percentis 25/75 e IQR usam somente
`Decimal`; mediana é a medida preferencial para futura estimativa de custo. O
fingerprint cobre valores ordenados, estabelecimentos anonimizados e linhagem
do asset.

Origem oficial, resposta válida, CSV/schema/período reconhecidos, produto,
moeda BRL, unidade por litro, preço positivo, geografia, linhagem, unicidade,
fingerprints, ausência de issue crítica e publicação exclusivamente shadow são
hard gates. `ANP_REQUIRED_PRODUCTS_PRESENT` exige simultaneamente gasolina C
comum e etanol hidratado; ausência de gasolina aditivada, isoladamente, não
reprova. Amostra mínima, estabelecimentos, cobertura municipal, freshness,
extremos, dispersão e variação semanal ficam explicitamente
`not_calibrated` até o piloto fornecer evidência; não são marcados como aprovados
nem reprovados.

O dataset nasce `building`; snapshots e quality results entram na mesma
transação. Somente depois dos hard gates ele se torna `shadow_published` e o
shadow anterior passa atomicamente a `retired`. Um índice parcial garante um
único shadow ativo. Falha deixa zero publicação parcial; fingerprint já ativo é
no-op. A migration `20260811_0007` é PostgreSQL-only, no-op em SQLite e retorna
isoladamente a `20260810_0006` somente quando não há shadow ANP ativo.

## 21. Etapa 8B2 — orquestração dos ramos FIPE, PBEV e ANP

A Etapa 8B2 evolui o mesmo núcleo independente da Etapa 6. Não existe um
segundo framework e nenhum pipeline é invocado por subprocesso:

```text
CLI ou scheduler opcional
          |
          v
runner único ------------------> meta.orchestration_run
  |                              meta.orchestration_step_run
  +--> FIPE: Bronze -> Silver -> Gold
  +--> PBEV: unidade pbev ------> Gold shadow PBEV
  +--> ANP: unidade anp_fuel_prices -> Gold shadow ANP
```

PBEV e ANP aparecem como unidades únicas na orquestração porque suas APIs
públicas já controlam internamente Bronze, Silver e Gold numa transação lógica.
Criar três steps artificiais para cada ramo duplicaria responsabilidade e
produziria retomada enganosa. A migration `20260811_0008` amplia somente o enum
`meta.orchestration_step` com `pbev` e `anp_fuel_prices`; as tabelas, FKs,
constraints e
triggers da Etapa 6 são reutilizados. SQLite permanece no-op. O downgrade
retorna a `20260811_0007` apenas quando não existe histórico que use os novos
valores.

### 21.1 Escopos, compatibilidade e dependências

O escopo padrão continua `fipe`, preservando o comando anterior e
`--from-step bronze|silver|gold`. Os escopos adicionais são `pbev`, `anp` e
`complete`. O completo usa a ordem determinística FIPE → PBEV → ANP, mas as
dependências são locais: Bronze bloqueia Silver, Silver bloqueia Gold, enquanto
PBEV e ANP não dependem do resultado FIPE nem um do outro.

Falha ANP após FIPE/PBEV concluídos produz run global `partial` e não reverte
datasets anteriores. A mesma regra de isolamento vale para falha PBEV seguida
de ANP bem-sucedida. Se nenhuma unidade completar, o run é `failed`.
`succeeded` e `partial` persistidos são reutilizados por `--resume`; somente a
unidade incompleta recebe nova tentativa.

### 21.2 Concorrência, retry e cancelamento

Locks são associados ao recurso (`sigra-orchestration:fipe`, `:pbev` e `:anp`),
não a um bloqueio global. Escopos sem recurso comum podem coexistir. O escopo
`complete` adquire os três locks em ordem fixa e, portanto, não concorre com
nenhum run que escreva nos mesmos ramos. Os locks internos `pbev:<cycle_year>`
e `anp:<source_reference>` continuam preservados nos loaders.

Retry automático permanece limitado a transporte, conexão e timeout
transitórios. Erros de hash, layout, contrato, quality gate e resultados
definitivos não recebem retry cego. Checkpoints atualizam heartbeat e observam
cancelamento/timeout entre estágios seguros. Prefect continua um adaptador
opcional com import tardio; o runner e os pipelines não dependem dele.
Uma periodicidade semanal pode ser fornecida externamente, por exemplo cron
`0 3 * * 1` com timezone `America/Sao_Paulo`; nenhum deployment ou schedule é
criado pelo repositório ou pelos testes.

### 21.3 Idempotência, observabilidade e segurança

Cada escopo possui `flow_name` próprio e chave idempotente SHA-256. O step
registra tentativa, status, duração, métricas whitelisted, erro sanitizado e o
último `pipeline_run_id` aplicável quando o pipeline retorna vários runs
internos. Caminho externo PBEV, URL de banco, URL autenticada, credencial,
payload, CSV e PDF não entram nos metadados de orquestração.

O dry-run retorna apenas o plano do escopo: não abre banco, não adquire lock,
não chama FIPE/ANP, não resolve PDFs PBEV e não cria arquivos. Esta etapa não
agenda execução automaticamente e não conecta PBEV ou ANP a FastAPI,
recomendador, frontend, financiamento, BI ou à Gold FIPE operacional.

## 22. Etapa 9, Lote 1 — contrato da Gold analítica integrada

O primeiro lote da Etapa 9 materializa apenas o contrato estrutural da Gold
analítica integrada FIPE + PBEV + ANP. A migration `20260811_0009`, filha da
`20260811_0008`, é PostgreSQL-only e no-op em SQLite. Loader, pipeline, CLI,
orquestração e integrações operacionais ficam explicitamente fora deste lote.

### 22.1 Objetos e linhagem Gold-only

O agregado usa `gold.integrated_vehicle_cost_dataset` e as evidências
`snapshot`, `projection_snapshot`, `flex_comparison_snapshot`,
`geography_request`, `exclusion`, `quality_rule_catalog`, `quality_result`,
`activation`, `invalidation` e `coverage_baseline`, todos com o prefixo
`integrated_vehicle_cost_`. A versão integrada é `VARCHAR(96)`; versões-fonte
e FKs filhas permanecem compatíveis com `VARCHAR(80)`.

As únicas linhagens veiculares e de preço aceitas são os registros Gold
canônicos `vehicle_features_snapshot(gold_record_id)`,
`vehicle_efficiency_snapshot(gold_record_id)` e
`anp_fuel_price_snapshot(snapshot_id)`. Não há FK de identidade para Silver e
nenhum dado PBEV/ANP passa a integrar a Gold FIPE operacional.

### 22.2 Grãos e reconciliação

O snapshot é único por dataset, veículo, combustível, geografia solicitada e
semana ANP. Ele não contém `scenario_code`. A projeção é única por dataset,
snapshot e `mixed_1000_v1`, com 1.000 km mensais e 12.000 km anuais. Portanto,
os conjuntos publicados de veículos e cenários são obtidos da projeção unida
ao snapshot; snapshot sem projeção não é publicação.

Exclusão de veículo não carrega cenário. Exclusão de cenário exige a chave
completa de veículo, `mixed_1000_v1`, combustível, geografia e semana. A
linhagem da exclusão é Gold-only, e triggers impedem tanto inserir projeção já
excluída quanto excluir uma projeção existente. As funções de reconciliação
usam `EXCEPT` e `UNION` sobre chaves completas e expõem conjuntos ausentes e
inesperados, impedindo que contagens coincidentes ocultem identidades trocadas.

### 22.3 Qualidade, ativação e rollback

A política `integrated-vehicle-cost-quality-v1` cataloga 29 hard gates
críticos com status esperado `passed` e sete controles estatísticos ANP com
status esperado `not_calibrated`. Cada resultado é identificado por dataset,
versão da política e regra; evidência de outra versão não satisfaz ativação.
Somente um dataset reconciliado, com todos os resultados requeridos e sem
regressão pendente de revisão manual, pode gerar um evento de ativação.

As coberturas canônicas são `catalog_coverage_pct` e `pbev_coverage_pct`, ambas
decimais. `coverage_regression_status` aceita `not_applicable`, `passed` e
`manual_review_required`; não existe estado `failed`. Regressão bloqueia
ativação e também rollback até revisão manual.

Eventos `publish`, `replace` e `rollback` atualizam o shadow atomicamente e
preservam a versão anterior. Invalidação ativa aposenta o dataset sem apagar
evidência. Snapshots, projeções, comparações flex, resultados, ativações,
invalidações e baselines são append-only. O downgrade é defensivo: remove
somente a `20260811_0009` quando não há dataset nem evidência integrada.

## 23. Etapa 9, Lote 2 — materialização e publicação integrada

O Lote 2 implementa a unidade operacional que preenche os objetos da migration
`20260811_0009`; nenhuma migration ou contrato paralelo é criado. A fronteira
permanece analítica e shadow:

```text
Gold FIPE ativa -----+
Gold PBEV shadow ----+--> plano integrado determinístico
Gold ANP shadow -----+        |
                              v
                  dataset + snapshots + projeções
                  + exclusões + qualidade + ativação
```

### 23.1 Seleção, corte analítico e cálculo

A seleção exige exatamente um dataset ativo e aprovado por fonte. As versões e
fingerprints são fixadas no cabeçalho integrado e as linhas preservam FKs para
os três snapshots Gold. Todas as leituras pertencem à mesma visão transacional
`REPEATABLE READ`; evidência futura ao corte analítico é rejeitada.

A geografia é municipal ou estadual exata, sem fallback. A semana ANP é única e
deve conter gasolina C comum e etanol hidratado; gasolina aditivada é opcional.
O materializador usa somente as fórmulas `Decimal` do contrato e o cenário
`mixed_1000_v1`. Nenhum campo do snapshot é completado por Bronze, Silver,
cache, legado ou serviço externo. Ausência de PBEV matched ou de consumo
material suficiente gera exclusão de veículo com motivo controlado.

### 23.2 Atomicidade, concorrência e qualidade

Um advisory lock transacional estável serializa a publicação integrada. Dataset,
requisição, snapshots, projeções, comparações flex, exclusões, resultados dos 29
hard gates, sete controles ANP `not_calibrated` e evento de ativação pertencem à
mesma transação. Exceção faz rollback integral; nenhuma publicação parcial fica
visível.

A reconciliação persistida usa as funções de conjunto do Lote 1 e confirma que
todo veículo FIPE aparece como projeção ou exclusão e que todo cenário esperado
aparece exatamente uma vez. Conflitos projeção/exclusão continuam bloqueados
pelos triggers nos dois sentidos. Regressão contra o baseline grava o dataset e
a evidência como `manual_review_required`, sem inserir ativação, aposentar o
shadow corrente ou executar rollback automático.

### 23.3 Idempotência, supersessão e rollback

O fingerprint canônico inclui versões e hashes das fontes, políticas, requisição
geográfica, projeções, exclusões, comparações e estados dos gates. Relógio,
UUID do run e credenciais ficam fora. Fingerprint já ativo retorna
`deduplicated`, sem novos dados ou evento. Conteúdo material novo recebe versão
nova e, se aprovado, substitui atomicamente o shadow anterior.

Rollback exige alvo previamente publicado e retirado, não invalidado, com
qualidade aprovada e sem `manual_review_required`. O evento troca a ativação na
mesma transação e preserva todos os snapshots, exclusões e resultados históricos.
Solicitar rollback para o dataset já ativo é no-op idempotente.

### 23.4 CLI, dry-run e limites

A CLI independente expõe `publish`, `dry-run` e `rollback`. O dry-run é puro e
determinístico: não cria engine, não abre banco, não adquire lock, não executa
FIPE/PBEV/ANP, não chama rede e não cria arquivo. Publicação e rollback produzem
JSON sanitizado e código de saída não zero em falha.

O Lote 2 não é registrado como nova unidade de orquestração e não possui aresta
para FastAPI, recomendador, frontend, financiamento ou BI. SQLite continua no-op
analítico. A validação real permanece opt-in e aceita somente PostgreSQL local
descartável com nome terminado em `_test`.

## 24. Etapa 10 — orquestração e consumo controlado da Gold integrada

A migration `20260811_0010` transforma a publicação integrada em unidade
canônica independente da orquestração. A separação é estrutural: `gold` preserva
o significado de Gold FIPE, enquanto `integrated_vehicle_cost` recebe histórico,
tentativas, lock e retomada próprios. A migration altera o ENUM usado por
`meta.orchestration_run.start_step` e `meta.orchestration_step_run.step_name`, é
no-op em SQLite e bloqueia downgrade quando qualquer uma das colunas registra a
nova unidade. Nenhum histórico é removido, renomeado ou convertido.

No escopo `complete`, a Gold integrada sucede Gold FIPE, PBEV shadow e ANP
shadow. Falha de uma fonte impede somente a unidade integrada; ramos já
concluídos permanecem auditados e o resultado global torna-se `partial`. Retomar
repete apenas a unidade incompleta. A publicação integrada é chamada diretamente
como função Python e conserva a política de retry somente para exceções
transitórias. Parâmetros de geografia e semana são obrigatoriamente explícitos
para uma execução real. O modo dry-run não abre banco, não adquire lock, não
chama rede e não grava arquivos.

### 24.1 Fronteira de consumo

O consumo HTTP fica atrás de uma camada de repositório somente leitura e de uma
API versionada em `/api/v1/integrated-vehicle-cost`. O repositório consulta
somente `gold.integrated_vehicle_cost_consumption_v1`, sem conhecer as tabelas
físicas subjacentes. A seleção aceita somente um
dataset integrado ativo, publicado em shadow, elegível pelos hard gates e pela
qualidade, sem `manual_review_required` e sem evento de invalidação. Dataset
retirado/supersedido, inválido ou em revisão não é retornado. Não existem
consultas de fallback a Bronze, Silver, cache ou legado.

Listagem e detalhe são paginados, filtráveis e ordenados por uma allowlist
determinística. Os valores financeiros e de consumo preservam `Decimal`; nenhuma
recomendação ou cálculo operacional é refeito no endpoint. O cenário persistido
`mixed_1000_v1` é rotulado como baseline analítico, não como perfil implícito de
cliente. Personalização futura deverá receber parâmetros explícitos, sem defaults
inventados. Frontend, recomendador e BI permanecem fora desta aresta e nenhuma
promoção operacional é disparada pela leitura.

## 25. Simulação configurável sobre a Gold integrada

O endpoint `POST /api/v1/integrated-vehicle-cost/simulate` recebe um cenário
completo: quilometragem mensal, distribuição urbana/rodoviária totalizando
exatamente 100%, horizonte positivo, UF, município opcional, semana de
referência, combustível ou estratégia de menor custo, preço manual opcional,
eficiências urbana e rodoviária opcionais e filtros. Contratos HTTP estritos
rejeitam booleanos, `float`, NaN, infinitos, omissões e valores fora dos limites
defensivos. O motor puro usa somente `Decimal` e quantização explícita.

O consumo mensal é `distância × (proporção urbana / eficiência urbana +
proporção rodoviária / eficiência rodoviária)`. O custo mensal multiplica os
litros pelo preço, e o custo do horizonte multiplica o custo mensal pela
quantidade de meses. Litros e custos anuais são derivados do resultado mensal;
nenhuma etapa usa conversão intermediária para `float`.

O repositório é somente leitura e consulta exclusivamente a view contratual da
Gold integrada ativa, publicada, aprovada, não invalidada e sem revisão manual,
além das exclusões do mesmo dataset. Não consulta Bronze ou Silver. No modo ANP,
produto, geografia e semana devem coincidir exatamente. No modo manual, o preço
vem apenas do cliente e não recebe fallback ANP. Eficiências omitidas exigem
evidência PBEV Gold publicada; eficiências informadas são marcadas como entrada
do usuário. Nenhuma localidade, período, produto, preço ou eficiência alternativos
são selecionados implicitamente.

Gasolina comum, gasolina aditivada e etanol são seleções explícitas.
`lowest_projected_cost` avalia somente combustíveis compatíveis presentes na
evidência. Ausência e ambiguidade produzem motivos auditáveis. O ranking usa
custo mensal, custo por quilômetro, identidade e combustível; o desempate é
determinístico. O fingerprint serializa cenário, resultados, exclusões e
versões FIPE/PBEV/ANP/Gold integrada, sem relógio ou UUID.

A resposta separa o resultado personalizado da comparação canônica: informa
origens `user_input`, `pbev_gold`, `anp_gold` e `canonical_policy`, parâmetros,
eficiências, preço, geografia, semana quando aplicável, custos mensal/anual/no
horizonte, diferença para `mixed_1000_v1`, fórmula, avisos, limitações e timestamp
da resposta. O baseline permanece evidência publicada para comparação, ranking,
auditoria e regressão; não atua como default do cliente e não é alterado. Não há
persistência de preferência, escrita Gold, lock, pipeline, rede ou chamada
externa. Financiamento, manutenção, seguro, IPVA, depreciação, frontend,
recomendador e BI permanecem fora do motor de cálculo. O frontend disponibiliza
o cenário no detalhe do veículo: resolve explicitamente a identidade publicada
na Gold, mantém percentuais urbano/rodoviário sincronizados, valida os campos e
envia o cenário ao endpoint. Somente a resposta do backend fornece os custos,
fontes e avisos; nenhuma fórmula financeira ou preferência é mantida no cliente.
O head Alembic permanece `20260811_0010`.

## 26. Composição multifator do recomendador

A recomendação multifator é uma composição stateless e opcional sobre o
ranking existente. Sem `multifactor_profile`, o caminho legado não recebe campo
novo e preserva integralmente ordem, score, empates, elegibilidade e mensagens.
Com o perfil habilitado, o backend executa uma única simulação configurável para
o conjunto Gold elegível e aplica exatamente o mesmo cenário a todos os
veículos comparáveis.

O conjunto de critérios é `total_cost`, `usage_fit`, `comfort`, `safety`,
`performance`, `efficiency` e `legacy_quality`. Custo de combustível e
eficiência vêm da Gold e do cenário; `legacy_quality` contém apenas manutenção,
confiabilidade, peças e revenda. Critérios financeiros, TCO e adequação já
presentes no recomendador não são reutilizados nesse agrupamento, evitando
dupla contagem. Pesos devem ser `Decimal` finitos entre zero e cem, com ao menos
um valor positivo, e são normalizados deterministicamente.

Associação entre catálogo legado e Gold exige marca, modelo e ano exatos após
normalização controlada. Zero ou múltiplas identidades tornam a evidência
indisponível; não há aproximação ou fallback silencioso. O mesmo vale para
conforto ausente quando seu peso é positivo. O resultado explica score bruto,
peso de entrada, peso normalizado, contribuição, score final, posição, baseline
histórico, desempates, custos e versões FIPE/PBEV/ANP/Gold integrada. Empates
usam score multifator, posição histórica e identificador do veículo nessa
ordem.

O frontend coleta cenário, autorização para orçamento acima de R$ 200 mil e
pesos editáveis, mas não calcula custos financeiros. Preferências não são
persistidas, a Gold ativa não é mutada e `mixed_1000_v1` permanece referência
analítica. A resposta separa dado publicado, entrada do usuário, cálculo
derivado e evidência indisponível. Não há nova migration, pipeline ou integração
com financiamento ou BI; o head continua `20260811_0010`.
