# Modulo de financiamento

**Versao do modulo:** `1.0.3`  
**Metodo de calculo:** `price-v1.2`  
**Moeda:** `BRL`

## Objetivo

O modulo compara cenarios informados pelo usuario. Ele nao oferece credito, nao consulta CPF, bancos ou financeiras e nao estima chance de aprovacao. A operacao e stateless: nenhuma simulacao e persistida e nenhum login e exigido.

## Arquitetura

O pacote `backend/app/financing` possui responsabilidades separadas:

- `schemas.py`: contrato e validacao das entradas;
- `calculator.py`: funcoes matematicas puras em `Decimal`;
- `service.py`: composicao da simulacao direta e reversa;
- `comparison.py`: destaques objetivos entre propostas;
- `routes.py`: HTTP e resolucao opcional de precos do catalogo;
- `domain.py`: versoes, limites, enums e disclaimer.

O modulo nao importa nem chama o recomendador, os pesos ou o TCO de automoveis. O endpoint reservado de recomendacao de motocicletas continua retornando HTTP 501.

## Endpoints

- `GET /financing/metadata`
- `POST /financing/simulate`
- `POST /financing/reverse-simulate`
- `POST /financing/compare`

A documentacao interativa permanece em `/docs`.

## Taxas aceitas

Cada simulacao aceita exatamente um modo:

1. `monthly_interest_rate_percent`: taxa efetiva mensal em percentual. Exemplo: `1.8` significa `1,8% a.m.`.
2. `effective_cost_rate_percent`: CET informado, acompanhado de `effective_cost_rate_period` (`monthly` ou `annual`) e de `effective_rate_includes_additional_costs`.

Taxa zero e valida somente quando enviada explicitamente. Ausencia de taxa ou envio simultaneo dos dois modos retorna HTTP 422. O SIGRA nao fornece taxa padrao.

Quando um CET e informado, o sistema o utiliza como taxa efetiva para a estimativa e nao tenta decompor o valor em juros, tarifas e seguros.

Se `effective_rate_includes_additional_costs=true`, tarifas, seguro e servicos financiados devem ser zero. Valores positivos retornam HTTP 422 para impedir dupla contagem. Custos pagos a vista continuam separados. Se o indicador for `false`, os custos financiados sao somados explicitamente ao principal.

## Preco do veiculo

- Com `vehicle_id`, o backend consulta a tabela correspondente ao `vehicle_type`.
- Automoveis sao filtrados explicitamente como `car`.
- Motocicletas sao consultadas em `motorcycles`.
- `vehicle_id` sem override usa `price_source=catalog`.
- `vehicle_id` com `negotiated_price` usa `price_source=negotiated` e preserva catalogo e negociado na resposta.
- Sem ID, `vehicle_price` representa o unico preco manual aceito e usa `price_source=manual`.
- `vehicle_price` e `negotiated_price` sem ID sao ambiguos e retornam HTTP 422.
- `vehicle_price` junto de `vehicle_id` tambem retorna HTTP 422.
- O registro e seu preco persistido nunca sao modificados.

O resultado informa `catalog_price`, `manual_price`, `negotiated_price`, `price_used`, `price_source` e `is_demonstration_data`. IDs incompativeis com o tipo sao rejeitados.

## Parcelas e arredondamento

`price-v1.2` preserva a formula Price com precisao interna e reconcilia a exibicao monetaria. A resposta informa `regular_installment`, `number_of_regular_installments`, `final_installment`, `maximum_installment_in_schedule` e `total_installments`. As parcelas regulares usam centavos; a ultima absorve somente o residuo de arredondamento e a soma exibida fecha exatamente com o total. Limite, avisos e comprometimento usam a maior entre a parcela regular e a final.

## Compatibilidade financeira

O resultado separa `financing_status`, `monthly_budget_status` e `overall_status`. Assim, uma compra a vista pode ter `financing_status=zero_financing_required` e, simultaneamente, `overall_status=over_monthly_budget` quando o uso excede o limite mensal. `compatibility_status` permanece como alias depreciado de `overall_status`.

Na simulacao reversa, se `required_financed_additional_costs` superar `maximum_financed_amount`, o estado e `insufficient_for_financed_costs`. O principal disponivel para o veiculo fica em zero, nenhum custo e financiado parcialmente e `maximum_vehicle_price` representa somente o alcance da entrada. A capacidade matematica permanece visivel para auditoria.

`near_limit` usa inicialmente 85% e pode ser configurado por `FINANCING_NEAR_LIMIT_PERCENTAGE`. O indicador nao representa aprovacao ou recusa de credito.

## Comparacao

O endpoint compara de 2 a 10 cenarios e retorna sete rotulos independentes: menor parcela, menor custo total da aquisicao, menor acrescimo total do financiamento, menor total das parcelas, menor prazo, menor comprometimento e maior entrada. `highlight_details` inclui vencedores, valor, unidade, diferenca para o proximo valor e indicador de empate. Empates preservam e exibem todos os nomes separadamente.

`same_vehicle`, `same_price_basis` e `comparison_scope` tornam explicito se os cenarios usam o mesmo veiculo e a mesma base de preco. Escopos possiveis: `same_vehicle_same_price`, `same_vehicle_different_price`, `different_vehicles`, `mixed_manual_and_catalog` e `different_acquisition_scenarios`. Comparacoes nao equivalentes continuam permitidas, mas recebem aviso e nao usam a palavra economia para diferencas causadas pelo objeto de compra.

O contexto financeiro e uma dimensao independente. `same_monthly_budget_basis` e `same_vehicle_cost_basis` comparam valores normalizados em centavos e retornam `null` quando algum dado esta ausente. `financial_context_comparable` so e verdadeiro quando ambas as bases sao iguais e todos os percentuais existem. Os estados possiveis sao `comparable`, `different_monthly_budgets`, `different_vehicle_cost_bases`, `different_budget_and_vehicle_cost`, `insufficient_budget_data`, `insufficient_vehicle_cost_data` e `insufficient_financial_context`.

Quando o contexto nao e comparavel, `lowest_budget_commitment` sai de `highlights` e `highlight_details` e aparece em `suppressed_highlights` com o motivo. Nenhum vencedor ou economia e inferido de um orcamento maior. Os percentuais permanecem nos cenarios individuais, e os seis criterios independentes continuam comparaveis.

A mensagem generica de custos adicionais aparece somente quando existe custo financiado separado. Quando o CET informado ja declara esses custos incluidos, o frontend usa texto especifico; com todos os custos em zero, nenhuma mensagem e reservada.

Qualquer alteracao no formulario marca o resultado atual como desatualizado. Resultados desatualizados permanecem identificados visualmente e nao podem ser adicionados a comparacao.

## Compatibilidade da API

`vehicle_price`, `catalog_vehicle_price`, `financed_principal`, `estimated_installment`, `upfront_cost`, `total_interest_and_financed_costs` e `compatibility_status` continuam presentes temporariamente. A resposta inclui `deprecated_fields` apontando para os nomes canonicos. O calculo, a comparacao e o frontend usam apenas os campos canonicos; os aliases existem somente na serializacao de compatibilidade e em testes dedicados. A remocao esta planejada para a versao principal `2.0.0`.

## Regressao imutavel

`backend/tests/fixtures/financing_regression_v1.json` congela formula, arredondamento, ultima parcela, simulacoes direta e reversa, estados e semantica da comparacao. A fixture usa somente entradas controladas e funcoes puras: nao consulta banco, catalogo vivo, FIPE, rede ou interface.

## Limitacoes

- apenas parcelas fixas Price;
- sem SAC;
- sem consulta de taxas atuais;
- sem integracao bancaria;
- sem persistencia de propostas;
- sem aprovacao de credito;
- sem TCO funcional de motocicletas;
- custos mensais do veiculo precisam ser informados ou fornecidos externamente.
