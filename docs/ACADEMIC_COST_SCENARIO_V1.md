# Cenário acadêmico de custo v1

`academic_cost_scenario_v1` é uma camada exclusivamente offline para testar a
viabilidade metodológica de uma coorte. Ela não publica dados, não altera a
Gold, não muda os contratos v1/v2/v3 e não transforma estimativas em fatos
observados.

## Estados independentes

- `observed_tco_complete`: os cinco componentes do TCO atendem ao contrato
  operacional com observações ou derivações aceitas por ele.
- `scenario_tco_complete`: os cinco componentes foram calculados com entradas
  acadêmicas explícitas, uniformes e versionadas.
- `academic_test_ready`: identidade exata, critérios mínimos do perfil,
  elegibilidade, TCO de cenário completo e apresentação de cobertura e
  confiança descritiva.
- `operationally_active`: permanece sob o gate operacional existente. Um
  cenário acadêmico nunca o ativa.

`methodology_ready` também permanece inalterado. Ele continua sendo a
conjunção dos critérios do método v3, da elegibilidade e da cobertura mínima
vigente; não é sinônimo de recomendação.

O gate acadêmico possui uma projeção de critérios separada. Somente no perfil
Trabalho, `scenario_monthly_tco_brl` pode preencher `operating_cost` para
`academic_test_ready`, na mesma unidade `BRL/month`. Essa projeção não preenche
o custo operacional observado, não torna `profile_scoreable` ou
`methodology_ready` verdadeiros e nunca alcança `operationally_active`.

## Parâmetros e fórmulas

O contrato central está em
`data_platform/catalog/academic_cost_scenario_v1.json`. Baixo, base e alto usam
os mesmos parâmetros para todos os veículos comparáveis. Os valores são
hipóteses declaradas de sensibilidade, não estimativas de mercado, alíquotas
legais vigentes, cotações de seguro ou despesas observadas.

- combustível mensal = `1.000 km / consumo urbano PBEV × R$ 6/l`;
- IPVA mensal = `preço FIPE × taxa anual do cenário / 12`;
- manutenção mensal = `preço FIPE × taxa anual / 12` ou valor anual explícito
  do cenário dividido por 12;
- seguro mensal = a mesma alternativa explícita de taxa ou valor anual;
- depreciação mensal = `preço FIPE × taxa anual do cenário / 12`.

Cada componente informa unidade, fórmula, natureza, origem metodológica e
entradas. O preço e o consumo conservam sua proveniência observada; o custo
calculado é sempre `scenario_estimate`. A ausência de ANP não bloqueia o custo
de cenário porque o preço do combustível foi declarado pelo usuário, mas ela
continua bloqueando qualquer alegação de custo observado.

`body_footprint_m2 = length_mm × body_width_mm ÷ 1.000.000` é uma derivação
diagnóstica idempotente, com hashes e localizadores das duas observações de
entrada. Ela descreve somente a carroceria. Sua lista de critérios aceitos é
vazia: Cidade e Trabalho no método v3 exigem `width_with_mirrors_mm`, portanto
a área da carroceria não satisfaz `footprint` e não elimina essa lacuna.

## Guardrails

- ausente permanece `null/unavailable`, nunca zero;
- segurança não é estimada;
- Família e Estrada permanecem bloqueados sem airbags, ABS e ESC completos;
- nenhum parâmetro é calibrado para obter uma ordem desejada;
- largura de carroceria nunca é reinterpretada como largura com espelhos;
- TCO acadêmico pode completar apenas o critério acadêmico de Trabalho;
- nenhuma ordem exploratória é uma recomendação ou ranking publicado;
- limiares de cobertura servem apenas à sensibilidade e não promovem veículos;
- nenhum valor dos 34 veículos legados é regravado.

O preview pode ordenar separadamente o escore metodológico já existente e o
TCO de cenário, somente para observar sensibilidade. `recommended` permanece
`false`, `recommendation_ranking` permanece vazio e publicação/ativação ficam
proibidas pelo próprio contrato.
