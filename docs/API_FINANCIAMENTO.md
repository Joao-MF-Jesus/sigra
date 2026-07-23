# API de financiamento

## Simulacao direta

`POST /financing/simulate`

```json
{
  "vehicle_type": "car",
  "vehicle_price": 30000,
  "down_payment": 10000,
  "term_months": 36,
  "monthly_interest_rate_percent": 1.8,
  "upfront_fees": 0,
  "financed_fees": 500,
  "financed_insurance": 0,
  "financed_services": 0,
  "desired_max_installment": 900,
  "available_monthly_budget": 1600,
  "estimated_monthly_vehicle_cost": 620,
  "amortization_method": "price"
}
```

Para preco do catalogo, substitua `vehicle_price` por `vehicle_id`. `negotiated_price` pode substituir o valor do catalogo sem persistir mudancas.

As fontes sao exclusivas:

- manual: `vehicle_price`, sem ID e sem negociado;
- catalogo: `vehicle_id`, sem `vehicle_price`;
- negociado: `vehicle_id` mais `negotiated_price`.

A resposta canonica usa `catalog_price`, `manual_price`, `negotiated_price`, `price_used` e `price_source` (`catalog`, `negotiated` ou `manual`).

## Simulacao reversa

`POST /financing/reverse-simulate`

```json
{
  "vehicle_type": "car",
  "down_payment": 8000,
  "maximum_installment": 900,
  "term_months": 36,
  "monthly_interest_rate_percent": 1.8,
  "upfront_fees": 0,
  "financed_fees": 500,
  "financed_insurance": 0,
  "financed_services": 0,
  "available_monthly_budget": 1600,
  "estimated_monthly_vehicle_cost": 600,
  "amortization_method": "price"
}
```

## CET informado

Remova `monthly_interest_rate_percent` e envie `effective_cost_rate_percent`, `effective_cost_rate_period` e `effective_rate_includes_additional_costs`.

Com `effective_rate_includes_additional_costs=true`, `financed_fees`, `financed_insurance` e `financed_services` devem ser zero. Com `false`, os custos podem ser incorporados separadamente. `upfront_fees` permanece independente nos dois modos.

## Resposta 1.0.3

- `regular_installment`: parcela regular arredondada;
- `number_of_regular_installments`: quantidade antes da ultima;
- `final_installment`: ultima parcela reconciliada;
- `maximum_installment_in_schedule`: maior valor entre parcela regular e final, usado nos limites;
- `total_installments`: soma monetaria exata das parcelas exibidas;
- `financed_vehicle_principal`: principal referente ao preco;
- `financed_additional_costs`: custos adicionais incorporados;
- `total_financing_addition`: acrescimo total sobre o principal do veiculo;
- `interest_estimate`: disponivel apenas quando a taxa mensal informada permite separacao;
- `financing_status`: situacao do financiamento/parcela;
- `monthly_budget_status`: situacao do desembolso mensal;
- `overall_status`: prioridade consolidada.

Na simulacao reversa, `maximum_financed_amount` e a capacidade matematica total, `required_financed_additional_costs` registra os custos solicitados e `available_vehicle_principal` registra o saldo para o veiculo. Quando os custos superam a capacidade, `financing_status` e `overall_status` recebem `insufficient_for_financed_costs`; nenhum custo parcial e apresentado como financiado.

Aliases antigos permanecem temporariamente e sao relacionados em `deprecated_fields`.

## Comparacao

`POST /financing/compare` recebe `{"scenarios": [...]}` com 2 a 10 contratos de simulacao direta. Um ou onze cenarios retornam HTTP 422; a API nunca trunca a lista. `offer_name` identifica cada proposta. O resultado retorna destaques por criterio e diferencas em relacao ao primeiro cenario, sem declarar vencedor geral.

O envelope inclui `same_vehicle`, `same_price_basis` e `comparison_scope`. `highlight_details` associa cada criterio a `scenario_names`, `value`, `difference_to_next`, `unit` e `is_tie`. `highlights` permanece como lista canonica de nomes. O alias antigo duplicado foi preservado somente em `legacy_highlights` e esta marcado em `deprecated_fields` para remocao planejada em `2.0.0`.

`comparison_context` tambem informa:

- `same_monthly_budget_basis`: `true`, `false` ou `null` quando ha ausencia;
- `same_vehicle_cost_basis`: `true`, `false` ou `null` quando ha ausencia;
- `financial_context_comparable`: permite ou impede vencedor de comprometimento;
- `monthly_commitment_comparison_status`: motivo deterministico da decisao.

Quando o contexto mensal nao e comparavel, `suppressed_highlights` recebe `lowest_budget_commitment` e o motivo. Os percentuais individuais permanecem em cada cenario, mas nao existe vencedor desse criterio nem linguagem de economia. Os demais destaques continuam presentes.

Quando veiculo ou base de preco diferem, a resposta inclui aviso de que os destaques refletem a aquisicao completa. O frontend mostra uma diferenca neutra em vez de chamar o valor de economia.

## Erros

Entradas ausentes, ambiguas, negativas, nao finitas, datas invalidas, prazo acima de 120, tipo invalido ou metodo diferente de `price` retornam HTTP 422. Registro inexistente retorna 404; ID de categoria incompativel retorna 422. Respostas nao incluem stack trace.
