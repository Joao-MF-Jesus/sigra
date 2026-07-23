# Formulas de financiamento

## Precisao

Todos os calculos do backend usam `Decimal`. A precisao interna e mantida durante potencias, conversao de taxas e totais. Valores monetarios de resposta sao arredondados para duas casas com `ROUND_HALF_UP`. Percentuais exibidos tambem usam duas casas.

## Sistema Price

Para principal `PV`, taxa efetiva mensal decimal `i` e prazo `n`:

```text
parcela = PV * [i * (1 + i)^n] / [(1 + i)^n - 1]
```

Quando a taxa mensal e zero:

```text
parcela = PV / n
```

## Composicao da simulacao direta

```text
principal do preco = preco usado - entrada
custos adicionais financiados = tarifas + seguro + servicos financiados
total financiado = principal do preco + custos adicionais financiados
total preciso das parcelas = arredondar(parcela precisa * prazo)
parcela regular = arredondar(parcela precisa)
quantidade regular = prazo - 1
parcela final = total preciso - (parcela regular * quantidade regular)
maior parcela do cronograma = max(parcela regular, parcela final)
custo inicial = entrada + tarifas pagas a vista
total de aquisicao = custo inicial + total das parcelas
acrescimo total do financiamento = total das parcelas - principal do veiculo
estimativa de juros = total das parcelas - valor total financiado
diferenca para compra a vista = total de aquisicao - preco usado
```

`total_financing_addition` inclui custos adicionais incorporados e o efeito da taxa. `interest_estimate` so e exibido no modo de taxa mensal, no qual a composicao informada permite a separacao. Com CET, o sistema nao chama o residuo de juros puros.

## Reconciliacao monetaria

As primeiras `n - 1` parcelas usam `regular_installment`. `final_installment` absorve o ajuste de centavos para que:

```text
regular_installment * number_of_regular_installments + final_installment
= total_installments
```

`maximum_installment_in_schedule` determina o cumprimento do teto, o status, os avisos e o comprometimento da parcela. Na simulacao reversa, a busca por capacidade usa centavos e retorna o maior principal cujo cronograma completo respeita o teto, inclusive a ultima parcela.

Para principais extremamente pequenos, existe uma protecao que reduz a parcela regular ao piso de centavos quando o arredondamento normal produziria parcela final negativa. A formula Price precisa nao e alterada.

## CET anual

Quando o CET anual efetivo e informado:

```text
i_mensal = (1 + i_anual)^(1/12) - 1
```

A implementacao usa logaritmo e exponencial de `Decimal` com contexto de alta precisao. O CET informado nao e decomposto em componentes que nao foram fornecidos.

Se o CET ja inclui custos adicionais, esses custos nao podem ser financiados novamente. Se nao inclui, tarifas, seguro e servicos informados sao adicionados separadamente ao principal.

## Simulacao reversa

Primeiro e calculado o principal total suportado pela parcela maxima. Para taxa positiva, inverte-se o fator Price. Para taxa zero:

```text
maximo financiavel = parcela maxima * prazo
principal disponivel para o preco = max(0, maximo financiavel - custos financiados)
preco maximo do veiculo = entrada + principal disponivel para o preco
```

Se os custos financiados superarem a capacidade, o preco maximo nunca fica negativo: `available_vehicle_principal` fica em zero, o resultado informa somente a entrada disponivel e usa `insufficient_for_financed_costs`. A capacidade matematica e os custos solicitados permanecem separados; o sistema nao inventa financiamento parcial de custos.

## Desembolso mensal

```text
desembolso mensal total = parcela + custo mensal estimado do veiculo
margem restante = orcamento mensal - desembolso mensal total
comprometimento = desembolso mensal total / orcamento mensal
```

Se o custo mensal do veiculo nao for informado, o sistema nao assume zero e nao calcula desembolso total, margem ou comprometimento.
