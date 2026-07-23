# Schema de motocicletas 0.3.1

## Escopo

O schema `0.3.1` consolida cadastro, rastreabilidade, cobertura e elegibilidade
estrutural. Ele não implementa Nota SIGRA, pesos, TCO, ranking ou recomendação
de motocicletas. O endpoint reservado continua em HTTP 501 com
`algorithm_version = null` e `weights_version = null`.

## Estruturas

- `motorcycles`: identidade comercial, preço, consumos e marcação demonstrativa. `annual_maintenance_cost` é opcional e ausência permanece `NULL`.
- `motorcycle_objective_specifications`: ficha objetiva com unidades explícitas.
- `motorcycle_data_sources`: fonte canônica por grupo, permitindo fontes complementares e uma principal por grupo.
- `motorcycle_derived_metrics`: indicadores externos demonstrativos ou não validados; ausência de linha significa “não calculado”.
- `motorcycle_economic_estimates`: estimativas temporais versionadas, inicialmente `depreciation_rate_annual_percent`.
- `motorcycle_specifications`: compatibilidade temporária com bancos antigos.

## Fontes canônicas e legado

Para novos registros, `motorcycle_data_sources` é a única fonte de verdade de rastreabilidade. Uma fonte principal de `identity` é obrigatória no cadastro. Os campos gerais `data_source`, `data_confidence`, `source_*`, scores e `depreciation_rate` são legados e não são necessários para novos registros.

Quando fontes agrupadas existem, elas têm precedência. Divergência com o legado é indicada em `source_contract.legacy_divergence`. A resposta canônica omite campos antigos; `include_legacy=true` os devolve em `legacy_data`, marcado como `deprecated`.

Classificação dos grupos:

- cadastro: `identity`;
- cobertura mínima piloto: `identity`, `market_price`, `technical_specs`, `consumption`;
- complementares no estágio atual: `maintenance`, `reliability`,
  `parts_availability`, `safety_equipment`, `ergonomics`, `taxes`,
  `insurance`, `derived_metrics`.

## Dados demonstrativos

`demonstration_only` ocorre quando o registro está explicitamente marcado, quando o legado demonstrativo é a única rastreabilidade ou quando a fonte principal de identidade, ficha técnica ou preço é demonstrativa. Uma fonte secundária demonstrativa gera somente observação no grupo e não bloqueia a motocicleta inteira.

## Métricas e estimativas

Criação pública aceita somente `demonstration` e `unvalidated`. `calculated` é reservado a um serviço interno futuro e `deprecated` é apenas leitura. Demonstrativos exigem método `demonstration-*` e confiança máxima de 50. Não validados exigem notas metodológicas ou fonte vinculada. `uncalculated` não deve ser persistido.

Depreciação é estimativa econômica temporal, não especificação técnica. A ausência não vira zero e nenhuma fórmula automática foi implementada. O campo legado só existe para compatibilidade e não é exposto ao lado da estimativa canônica.

## Cobertura

`coverage` informa percentual de campos objetivos, cobertura dos quatro grupos
mínimos, cobertura complementar, campos/grupos ausentes, impedimentos,
observações e `future_recommendation_readiness`. Cobertura e prontidão não são
scores e não entram em ranking.

## Migração

A migração `0.3.0` relaxou campos legados e manutenção anual para `NULL`,
adicionou `is_demonstration` e criou estimativas econômicas. A etapa `0.3.1`
registra o contrato estabilizado, sem fabricar dados nem reescrever
motocicletas. A execução é idempotente.

Uma futura adoção PostgreSQL deve converter as mesmas alterações em migração formal, preservando a restrição de uma fonte principal por moto e grupo.
