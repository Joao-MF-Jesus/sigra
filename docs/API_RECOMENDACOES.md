# API de recomendacoes

## Requisicao

`POST /recommendations?envelope=true`

```json
{
  "budget": 200000,
  "monthly_limit": 3500,
  "use_case": "cidade",
  "monthly_mileage": 1000,
  "fuel_price": 6,
  "recommendation_strategy": "cost_benefit"
}
```

Os campos financeiros precisam ser finitos. Orcamento, limite mensal e preco do combustivel devem ser positivos; quilometragem pode ser zero. Uso e estrategia devem pertencer aos conjuntos documentados pelo SIGRA.

## Envelope de resposta

```json
{
  "algorithm_version": "2.1.2",
  "weights_version": "cars-v1",
  "vehicle_type": "car",
  "data_reference": null,
  "generated_at": "2026-07-20T18:00:00+00:00",
  "has_viable_options": true,
  "vehicle_processing": {
    "total_found": 34,
    "evaluated": 34,
    "ignored": 0,
    "ignored_reasons": {},
    "ignored_records": []
  },
  "recommendations": []
}
```

`data_reference` permanece nulo quando a base nao possui uma referencia temporal consolidada e confiavel. `generated_at` identifica o momento da resposta, nao o mes de referencia dos precos.

## Viabilidade

- `has_viable_options`: existe ao menos um veiculo que cabe na compra e no limite mensal.
- `is_best_choice`: verdadeiro apenas para a primeira opcao plenamente viavel.
- `is_best_available_reference`: verdadeiro para o primeiro colocado somente quando nenhuma opcao e viavel.

A posicao no ranking nao concede sozinha o rotulo de melhor escolha.

## Processamento de registros

Cada registro e validado isoladamente. Registros invalidos sao ignorados, os demais continuam sendo avaliados e a resposta informa contagens e motivos seguros. `ignored_records` serve para auditoria tecnica e nao contem stack trace.

## Compatibilidade

Sem `envelope=true`, a rota continua retornando a lista de recomendacoes usada pelos clientes legados. O frontend atual solicita explicitamente o envelope versionado.

## Motocicletas

O CRUD `/motorcycles` pertence a um módulo separado. `POST /motorcycles/recommendations` retorna HTTP 501 com mensagem explícita. Não existe Nota SIGRA, ranking ou fallback de automóveis para motocicletas nesta versão.

`GET /motorcycles` retorna por padrão uma lista canônica com somente registros
auditados e válidos. Com `?envelope=true`, retorna versão `0.3.1`,
`algorithm_version`, `weights_version` e `derived_metrics_method_version` como
`null`, além de contagens, resumo seguro dos inválidos e motocicletas válidas.
`limit` e `offset` controlam a página.

Cada motocicleta inclui `eligibility_status`, cobertura, impedimentos/observações, `data_sources`, `derived_metrics` e `economic_estimates`. Elegibilidade é somente prontidão estrutural; não representa recomendação. Ausência de métrica ou estimativa é lista vazia e não vira zero.

A resposta canônica de `GET`, `POST` e `PATCH` omite scores e fontes gerais
legadas. `include_legacy=true` devolve esses campos somente em
`legacy_data.fields`, com `deprecated=true` e remoção planejada para `1.0.0`.
`legacy_data` fica ausente por padrão e nunca é retornado vazio. Quando fontes
agrupadas existem, elas têm precedência e divergências são sinalizadas por
`source_contract.legacy_divergence`.

`coverage` separa quatro grupos mínimos (`identity`, `market_price`,
`technical_specs`, `consumption`) dos grupos complementares. Manutenção anual
é opcional, permanece `null` quando ausente e não bloqueia a estrutura piloto.
`future_recommendation_readiness` é um estado informativo, não score.

`GET /motorcycles/{id}` retorna `409 motorcycle_record_invalid` quando o registro existe, mas não pode atender ao schema público. `PATCH` permite repará-lo e `DELETE` não depende da serialização. Detalhes completos são registrados sem stack trace ou valores sensíveis.

`POST` rejeita URL, enum ou número inválido com HTTP 422. Fontes oficiais agrupadas exigem nome; estimativas exigem metodologia/referência. `PATCH` permite completar uma moto sem especificações, desde que todas as especificações obrigatórias sejam fornecidas. Registro inexistente retorna 404.

Fontes por grupo:

- `GET/POST /motorcycles/{id}/sources`;
- `PATCH/DELETE /motorcycles/{id}/sources/{source_id}`.
- `POST /motorcycles/{id}/sources/{source_id}/set-primary` troca a principal transacionalmente.

Métricas separadas:

- `GET /motorcycles/{id}/derived-metrics`;
- `POST /motorcycles/{id}/derived-metrics` aceita apenas `demonstration` ou `unvalidated`; não calcula score.

Estimativas econômicas separadas:

- `GET/POST /motorcycles/{id}/economic-estimates`;
- depreciação não é calculada e não participa de TCO;
- `calculated` é reservado a serviço interno futuro e `deprecated` é somente leitura.

O contrato não expõe Nota SIGRA, ranking, melhor escolha, estratégia executada ou pontuação final de motocicletas.

## Validação da recomendação automotiva

`use_case` e `recommendation_strategy` são enums. Campo omitido recebe o padrão documentado; valor explicitamente inválido retorna HTTP 422 com campo, entrada recebida e valores permitidos. Não existe conversão silenciosa para `cost_benefit`.

## Saúde e banco

- `GET /health`: estado geral, contagens, FIPE e resumo seguro do banco;
- `GET /health/database`: engine, conectividade e revision Alembic atual.

As respostas não expõem host, usuário, senha ou `DATABASE_URL`. Em SQLite
local ainda não carimbado pelo Alembic, `migration_revision` pode ser `null`.
