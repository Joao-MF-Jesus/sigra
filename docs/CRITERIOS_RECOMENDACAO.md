# Critérios de recomendação

O SIGRA usa uma recomendação multicritério explicável. A versão V2 adiciona duas ideias importantes: TCO mensal, ou custo total de propriedade, e prioridade de compra. Assim, o sistema não escolhe sempre o carro mais barato; ele interpreta o que o usuário quer fazer com o orçamento informado.

## O que é TCO

TCO significa custo total de propriedade. No SIGRA, ele representa quanto o veículo tende a custar por mês considerando compra, uso e manutenção.

O TCO mensal estimado soma:

- Combustível mensal.
- Manutenção mensal.
- IPVA mensal estimado.
- Seguro mensal estimado.
- Depreciação mensal estimada.

## Fórmula do TCO mensal

```text
combustivel_mensal =
quilometragem_mensal / consumo_km_l * preco_combustivel

manutencao_mensal =
manutencao_anual / 12

ipva_mensal =
preco_veiculo * 4% / 12

seguro_mensal =
preco_veiculo * 5% / 12

depreciacao_mensal =
preco_veiculo * taxa_depreciacao_anual / 12

tco_mensal =
combustivel_mensal
+ manutencao_mensal
+ ipva_mensal
+ seguro_mensal
+ depreciacao_mensal
```

Os percentuais de IPVA e seguro são demonstrativos para o MVP. Em uma fase futura, eles podem ser substituídos por dados reais por estado, perfil do condutor, seguradora e cidade.

## Orçamento máximo e faixa desejada

O orçamento informado pelo usuário é tratado como limite máximo de compra. Porém, em algumas prioridades, o SIGRA também calcula uma faixa desejada dentro desse limite.

Exemplo: se o usuário informa R$ 200.000, isso não significa que o sistema deve recomendar automaticamente um carro de R$ 45.000. Para a prioridade "Econômico dentro do orçamento", veículos muito abaixo da faixa racional podem perder pontos, pois talvez não representem a melhor escolha para aquele perfil. Para a prioridade "Menor custo possível", esses veículos baratos voltam a ganhar força.

## Capacidade financeira mensal

A versão V2 também combina orçamento de compra e limite mensal. Essa análise evita dois erros comuns:

- Recomendar um carro simples demais apenas porque ele é barato, mesmo quando o usuário tem orçamento e limite mensal para manter algo superior.
- Recomendar um carro caro na compra quando o usuário informa um limite mensal baixo demais para manter esse veículo.

Para isso, o SIGRA calcula o `monthly_capacity_score`, que indica qual percentual da base tem TCO mensal dentro do limite informado. Se o limite mensal cobre 80% ou 90% dos veículos, o sistema entende que há boa capacidade mensal. Se cobre poucos veículos, o ranking fica mais conservador.

## Perfil financeiro estimado

O campo `financial_capacity_profile` classifica a combinação entre orçamento e limite mensal:

- `restricted`: orçamento e limite mensal baixos.
- `purchase_high_monthly_low`: orçamento de compra alto, mas limite mensal baixo.
- `balanced`: compra e mensal em faixa intermediária.
- `comfortable`: orçamento e mensal suficientes para considerar veículos médios ou superiores.
- `high_capacity`: orçamento alto e limite mensal alto para a base demonstrativa.

Um veículo pode caber na compra, mas não caber na posse. Por isso o SIGRA também retorna:

- `purchase_viable`: indica se o preço cabe no orçamento de compra.
- `monthly_viable`: indica se o TCO cabe no limite mensal.
- `fully_viable`: indica se cabe nos dois.
- `monthly_limit_gap`: diferença entre limite mensal e TCO estimado.
- `total_monthly_cost`: TCO mensal do veículo.

Quando o perfil é `comfortable` ou `high_capacity`, estratégias como `best_within_budget` e `comfort_space` passam a dar mais chance a veículos de categoria superior que cabem no orçamento e no mensal. Quando o perfil é `purchase_high_monthly_low`, veículos com TCO acima do limite mensal perdem força mesmo que o orçamento de compra seja alto.

## Quando nenhum veículo é plenamente viável

Em alguns cenários, o orçamento de compra pode ser alto, mas o limite mensal informado pode ser baixo demais para cobrir o TCO de qualquer veículo da base. Nesses casos, o SIGRA não esconde os veículos, porque eles ainda servem como referência comparativa, mas deixa claro que não há recomendação plenamente viável.

O backend identifica esse cenário quando nenhum veículo possui `fully_viable = true` ou quando todos possuem `monthly_viable = false`. A resposta passa a informar:

- `has_viable_options`: se existe pelo menos uma opção viável na compra e no mensal.
- `viable_count`: quantidade de opções plenamente viáveis.
- `total_count`: quantidade total de veículos avaliados.
- `message`: explicação curta sobre o limite mensal não cobrir o TCO.
- `suggested_monthly_limit`: limite mensal aproximado para começar a encontrar opções viáveis.
- `suggested_strategy`: estratégia alternativa sugerida, quando fizer sentido.

O `suggested_monthly_limit` é calculado pegando o menor TCO mensal entre os veículos que cabem no orçamento de compra e arredondando para cima em centenas. Por exemplo, se o menor TCO viável encontrado é próximo de R$ 1.430, o sistema pode sugerir um limite mensal de aproximadamente R$ 1.500.

Assim, a tela não parece quebrada quando todos os cards aparecem como "Não recomendado": o SIGRA explica que os resultados estão sendo exibidos apenas como comparação e orienta o usuário a ajustar o limite mensal ou tentar uma estratégia mais conservadora.

## Prioridades de recomendação

O usuário pode escolher a estratégia da recomendação:

- `lowest_cost`: prioriza menor custo possível, favorecendo preço baixo e TCO baixo.
- `budget_economy`: busca uma opção econômica dentro de uma faixa racional do orçamento, evitando escolher apenas o carro mais barato quando o orçamento é alto.
- `cost_benefit`: estratégia padrão; equilibra TCO, preço, uso, confiabilidade, manutenção e segmento.
- `balanced`: distribui os pesos de forma mais uniforme.
- `comfort_space`: valoriza conforto, espaço, segurança e categoria.
- `best_within_budget`: busca a melhor categoria possível dentro do orçamento informado, sem escolher automaticamente o mais caro.

## Componentes da Nota SIGRA V2

Cada veículo recebe notas separadas de 0 a 100:

- `financial_score`: aderência ao orçamento de compra e ao limite mensal.
- `tco_score`: custo total mensal comparado aos outros veículos da base.
- `usage_score`: aderência ao uso informado.
- `maintenance_score`: custo e facilidade de manutenção.
- `reliability_score`: confiabilidade demonstrativa do modelo.
- `parts_score`: disponibilidade de peças e fornecedores.
- `segment_score`: categoria, nível do segmento, conforto, espaço, segurança e adequação ao uso.
- `purchase_intent_score`: nota específica da prioridade escolhida pelo usuário.
- `resale_score`: menor desvalorização.
- `risk_score`: risco financeiro e de manutenção.
- `final_score`: Nota SIGRA final após pesos, bônus e penalidades.

## Normalização da Nota SIGRA

A Nota SIGRA final fica sempre entre 0 e 100. Ela é calculada a partir dos componentes ponderados, depois recebe bônus e penalidades moderados conforme perfil, estratégia e viabilidade financeira.

A nota 100 é tratada como rara. Ela representa aderência quase perfeita ao perfil informado. Para evitar que vários veículos bons pareçam igualmente perfeitos, o algoritmo aplica uma compressão suave no topo da escala: veículos excelentes continuam com notas altas, mas diferenças pequenas de TCO, confiabilidade, manutenção, peças, segurança, espaço, conforto e desvalorização aparecem melhor no ranking.

O objetivo da nota não é declarar vários carros como perfeitos, e sim ordenar alternativas próximas de forma explicável. Por isso, dois SUVs bons podem ficar, por exemplo, em 92 e 75 em vez de ambos aparecerem como 100.

## Desempate previsível

Quando veículos ficam com notas muito próximas, o SIGRA usa critérios determinísticos de desempate.

Para `best_within_budget`, o desempate prioriza:

- Viabilidade completa de compra e mensal.
- Nível de segmento.
- Confiabilidade.
- Segurança.
- Espaço.
- Menor TCO mensal.
- Disponibilidade de peças.
- Menor desvalorização.

Para `lowest_cost`, o desempate prioriza menor TCO, manutenção menor, melhor consumo e menor preço. Para `budget_economy`, prioriza TCO, confiabilidade, segmento, consumo e manutenção.

Se todos os critérios de negócio também empatarem, o identificador persistente do veículo é usado somente como última regra técnica. Assim, inverter a ordem de entrada não muda o resultado. Essa regra não substitui nenhum desempate de negócio.

## Validação e processamento da base

Antes do cálculo, cada veículo é validado individualmente. Preço e consumo devem ser positivos; custos e depreciação não podem ser negativos; ano, categoria, casos de uso, indicadores booleanos e notas também precisam ser válidos. Notas técnicas devem estar entre 0 e 100 e não são corrigidas por `clamp` silencioso.

Um registro obrigatório inválido é ignorado sem interromper os demais. A resposta informa `total_found`, `evaluated`, `ignored` e motivos agregados. Campos opcionais só usam fallback quando existe regra documentada; ausência de evidência reduz ou limita a confiança, sem inventar dado.

Quando todos os valores usados por uma normalização são iguais, a implementação atual mantém nota normalizada 100. Esse comportamento está coberto por teste e permanece documentado como limitação metodológica. Bases com um veículo, sem veículo válido e com outliers também são tratadas sem alterar a fórmula nesta etapa.

## Melhor escolha e referência comparativa

`is_best_choice` só pode ser verdadeiro para uma opção plenamente viável na compra e no limite mensal. Quando nenhuma opção é viável, nenhum veículo recebe esse rótulo; o primeiro resultado recebe `is_best_available_reference` e é apresentado apenas como `Melhor alternativa comparativa`.

## Nota, confiança e índice complementar

A Nota SIGRA mede aderência ao perfil e participa do ranking. A confiança mede cobertura e qualidade da evidência, com nível `baixa`, `moderada` ou `alta`, motivos e limitações. Ela permanece separada e não altera a ordenação.

O `decision_score` é um índice complementar de valor. Ele pode apoiar a leitura do resultado, mas não participa da ordenação principal e não deve ser interpretado como decisão automática.

## Reprodutibilidade da API

Com `POST /recommendations?envelope=true`, a API retorna a versão do algoritmo (`2.1.2`), versão dos pesos (`cars-v1`), categoria (`car`), horário ISO 8601, referência temporal quando disponível e contagem de registros processados. `data_reference` é `null` quando não há referência confiável.

## Segmento e intenção de compra

O `segment_score` ajuda o sistema a diferenciar veículos que antes pareciam parecidos apenas pelo preço. Ele considera:

- Categoria: hatch, sedã, SUV, minivan ou subcompacto.
- Nível do segmento.
- Conforto.
- Espaço interno.
- Segurança.
- Adequação para cidade, família, estrada, aplicativo ou SUV.

O `purchase_intent_score` muda conforme a prioridade selecionada. Por isso, com o mesmo orçamento de R$ 200.000, o ranking pode mudar:

- Em "Menor custo possível", carros populares podem subir.
- Em "Econômico dentro do orçamento", opções intermediárias tendem a subir.
- Em "Melhor categoria dentro do orçamento", sedãs médios e SUVs mais completos podem ganhar força.
- Em "Conforto e espaço", veículos mais espaçosos e seguros recebem mais peso.

## Perfil Aplicativo

No SIGRA, o uso "Aplicativo" não significa automaticamente escolher o carro mais barato. O sistema considera economia, mas também avalia se o veículo é adequado para trabalho recorrente, levando em conta:

- TCO mensal.
- Consumo.
- Manutenção.
- Confiabilidade.
- Disponibilidade de peças.
- Conforto.
- Espaço interno e porta-malas.
- Segurança.
- Nível de segmento.
- `app_score`.

Carros de entrada como Mobi, Uno, March e Gol podem aparecer quando a estratégia é `lowest_cost`, especialmente com orçamento e limite mensal baixos. Porém, quando o perfil financeiro é `comfortable` ou `high_capacity` e a estratégia não é `lowest_cost`, esses modelos perdem pontos por terem menor conforto e espaço para uso profissional recorrente.

Para `budget_economy`, o algoritmo busca economia com maior adequação profissional, favorecendo opções como sedãs compactos, hatches mais completos e modelos com bom equilíbrio entre TCO, peças e espaço. Para `best_within_budget`, o sistema dá mais chance a veículos de categoria superior que ainda cabem no orçamento e no limite mensal.

## Penalidades

O sistema penaliza o veículo quando:

- O preço passa do orçamento de compra informado.
- O TCO mensal passa do limite mensal informado.
- O perfil de uso não é ponto forte do modelo.
- A prioridade escolhida indica uma faixa desejada e o veículo fica muito abaixo dela.
- Dados reais de usuários indicam recorrência de problemas.
- Análise de peças indica custo, variação ou baixa disponibilidade.

## Saídas da API

Cada recomendação retorna:

- `recommendation_strategy`: estratégia usada no cálculo.
- `tco`: detalhamento do custo total mensal.
- `score_components`: notas separadas por categoria.
- `score_components.purchase_viable`: se cabe no orçamento de compra.
- `score_components.monthly_viable`: se cabe no limite mensal informado.
- `score_components.fully_viable`: se cabe na compra e no mensal.
- `score_components.monthly_capacity_score`: percentual da base que cabe no limite mensal.
- `score_components.financial_capacity_profile`: perfil financeiro estimado.
- `score_components.monthly_limit_gap`: folga ou estouro mensal.
- `score_components.total_monthly_cost`: TCO mensal usado no cálculo.
- `final_score`: Nota SIGRA final.
- `monthly_cost`: mantido por compatibilidade, agora representando o TCO mensal.
- `recommendation_summary`: resumo explicável com vantagem, risco, aderência e estratégia.
- `explanations`: justificativas textuais.
- `recommendation_status`: recomendado, atenção ou não recomendado.

## Por que o sistema é explicável

O SIGRA não usa uma caixa-preta. Cada decisão pode ser explicada por:

- Quanto custa por mês.
- Se cabe no orçamento de compra.
- Se cabe no limite mensal.
- Se combina com o uso informado.
- Qual prioridade de compra foi escolhida.
- Quais critérios puxaram a nota para cima.
- Quais riscos puxaram a nota para baixo.

Assim, a resposta para "por que este carro foi recomendado?" pode ser demonstrada olhando o TCO, os componentes da nota, a estratégia escolhida e as justificativas do ranking.
