# Fundação do módulo de motocicletas 0.3.1

O SIGRA possui um módulo consolidado de automóveis e uma fundação independente para motocicletas. A separação impede reutilização acidental de pesos, TCO ou regras de carros.

## Estado atual

- Automóveis: algoritmo `2.1.2`, pesos `cars-v1`, comportamento preservado por fixture de regressão.
- Motocicletas: módulo `0.3.1`, CRUD, auditoria, ficha objetiva, fontes canônicas por grupo, métricas derivadas, estimativas econômicas e elegibilidade estrutural.
- Motocicletas: `algorithm_version = null`, `weights_version = null` e `derived_metrics_method_version = null`.
- `POST /motorcycles/recommendations`: HTTP 501, sem Nota SIGRA, TCO, ranking ou recomendação.

## Modelo de dados

- `motorcycles`: identidade, preço, consumo, manutenção agregada e metadados legados.
- `motorcycle_objective_specifications`: ficha técnica objetiva um-para-um.
- `motorcycle_data_sources`: múltiplas fontes por grupo, com uma principal opcional por grupo.
- `motorcycle_derived_metrics`: indicadores versionados e independentes da ficha; ausência de linha significa não calculado.
- `motorcycle_economic_estimates`: estimativas econômicas temporais, sem cálculo automático ou uso em TCO.
- `motorcycle_specifications`: estrutura legada preservada para abrir bancos `0.1.x`.

Uma motocicleta pode existir e ser exibida sem métrica derivada. Scores antigos aceitos no payload são compatibilidade de entrada e são armazenados como métricas não validadas ou demonstrativas, nunca como fatos objetivos. A resposta canônica os omite; `include_legacy=true` habilita auditoria técnica.

## Cobertura e elegibilidade estrutural

O serviço verifica somente a estrutura do registro: categoria, faixa de 100 a
500 cm³, ano de 2018 em diante, campos indispensáveis, fontes principais,
confiança e atualidade. A cobertura mínima piloto usa `identity`,
`market_price`, `technical_specs` e `consumption`. `maintenance` e os demais
grupos econômicos/metodológicos são complementares; manutenção anual pode ser
`NULL` e nunca é convertida em zero.

`future_recommendation_readiness` descreve lacunas para uma metodologia futura
sem ser nota: `structurally_ready`, `missing_economic_data`,
`missing_methodological_data`, `insufficient_source_confidence`,
`demonstration_only` ou `not_ready`. `eligible` não significa recomendado ou
seguro. Não existe adequação ao perfil, score ou ranking.

## API

- `GET/POST /motorcycles`
- `GET/PATCH/DELETE /motorcycles/{id}`
- `GET/POST /motorcycles/{id}/sources`
- `PATCH/DELETE /motorcycles/{id}/sources/{source_id}`
- `POST /motorcycles/{id}/sources/{source_id}/set-primary`
- `GET/POST /motorcycles/{id}/derived-metrics`
- `GET/POST /motorcycles/{id}/economic-estimates`
- `GET /motorcycles/module-status`
- `POST /motorcycles/recommendations` (HTTP 501)

Os `POST` de métricas e estimativas aceitam somente `demonstration` ou `unvalidated`; `calculated` é reservado a serviço interno futuro e `deprecated` é somente leitura.

## Dados demonstrativos

O arquivo `backend/data/motorcycles.demo.json` contém exatamente quatro
identidades distintas: Honda CG 160 Fan, Yamaha NMax 160 ABS, Royal Enfield
Himalayan 450 e Honda CB 300F Twister. São registros acadêmicos de
demonstração, não dados oficiais nem uma base de mercado.

```powershell
python scripts/seed_motorcycles.py --rebuild-demo --dry-run
python scripts/seed_motorcycles.py --rebuild-demo --confirm
```

A identidade lógica usa marca, modelo, versão, ano e condição. O dry-run
relata registros, duplicidades, conflitos e quantidades relacionadas sem
escrever. A confirmação cria um backup SQLite, executa remoção e inserção em
transação, preserva motocicletas reais e automóveis e valida o estado final.
`normalize-demo` permanece disponível para a normalização legada, mas não
substitui a reconstrução canônica.

## Contrato futuro

O escopo, perfil, TCO conceitual, rubricas, guardrails e critérios para aprovação estão em `MOTORCYCLE_RECOMMENDER_SPEC_V1.md`. Nenhuma proposta desse documento é algoritmo funcional.
