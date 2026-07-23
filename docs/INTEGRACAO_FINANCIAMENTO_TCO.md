# Integracao entre financiamento e TCO

## Separacao atual

O financiamento representa o fluxo da **aquisicao**: entrada, saldo financiado, parcela, tarifas, juros e total pago.

O TCO representa **uso e propriedade**: combustivel, manutencao, impostos, seguro e depreciacao. O TCO automotivo existente nao foi alterado. Motocicletas ainda nao possuem TCO funcional.

Na versao `1.0.1`, o modulo aceita `estimated_monthly_vehicle_cost` calculado externamente ou informado pelo usuario. Esse campo nao e recalculado nem incorporado ao saldo financiado. Para compor `total_monthly_outflow`, ele deve conter somente saidas recorrentes de caixa. Se a origem for o TCO automotivo completo, a depreciacao mensal deve ser removida antes do envio e continuar exibida apenas na visao economica.

## Duas visoes

### Desembolso mensal

Parcela mais custos que saem do caixa no mes. Pode apoiar a verificacao do orcamento disponivel.

### Custo economico

Custos de uso, juros, encargos e depreciacao analisados por sua natureza. Essa visao exige periodo e premissas consistentes.

## Prevencao de dupla contagem

O sistema nao soma, como custos independentes do mesmo periodo:

- preco integral do veiculo;
- amortizacao contida na parcela;
- depreciacao do ativo.

O preco e o total de aquisicao pertencem a visao de compra. A parcela pertence ao fluxo de caixa. A depreciacao pertence ao custo economico. Uma futura tela consolidada deve manter secoes diferentes e declarar o horizonte de analise.

## Campos ausentes

Sem custo mensal do veiculo, o resultado retorna `null` para `total_monthly_outflow`, `monthly_budget_remaining` e `budget_commitment_percentage`. O sistema nao inventa TCO nem trata ausencia como custo zero.
