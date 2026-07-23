# Algoritmo SIGRA V2.1 auditavel

## Objetivo

O SIGRA usa uma analise multicriterio deterministica, sem machine learning e sem randomizacao. A Nota SIGRA mede aderencia ao perfil informado. Ela nao representa garantia de compra, ausencia de defeitos ou precisao absoluta de mercado.

## Etapas do calculo

1. O sistema estima o TCO mensal: combustivel, manutencao, IPVA, seguro e depreciacao.
2. Verifica se o veiculo cabe no orcamento de compra e no limite mensal.
3. Calcula notas de 0 a 100 para financas, TCO, uso, manutencao, confiabilidade, pecas, segmento e intencao de compra.
4. Aplica os pesos da estrategia escolhida e produz a nota base.
5. Aplica um ajuste contextual limitado entre -18 e +8 pontos.
6. Aplica separadamente evidencias de relatos reais e analise de pecas.
7. Aplica travas de coerencia antes de gerar a Nota SIGRA final.

## Por que os componentes combinam valor absoluto e relativo

Uma nota apenas relativa pode produzir resultados enganosos. O pior TCO da base viraria zero mesmo que ainda fosse financeiramente aceitavel, e uma confiabilidade 94/100 poderia virar 100 apenas por ser a maior da amostra.

Por isso, a V2.1 combina:

- valor absoluto informado na base;
- posicao relativa entre os 34 veiculos;
- aderencia aos limites do usuario;
- evidencia de pecas e relatos cadastrados.

## Nota base e contribuicoes

Cada item de `score_breakdown.criteria` informa:

- `score`: nota do criterio, entre 0 e 100;
- `weight`: peso percentual usado na estrategia;
- `contribution`: resultado de `score * weight / 100`.

As contribuicoes somadas formam `base_score`. Os pesos sempre somam 100%.

## Validacao dos dados

Preco, consumo e preco do combustivel sao indispensaveis e devem ser numeros
finitos maiores que zero. Manutencao, depreciacao, quilometragem, IPVA e seguro
nao podem ser negativos. Valores ausentes, nao numericos ou invalidos nao recebem
fallback inventado: o TCO rejeita o calculo e o recomendador ignora o veiculo,
registrando o motivo no log. Um preco FIPE sincronizado e uma fonte valida para
substituir o preco demonstrativo antes dessa validacao.

Ausencia de relatos e evidencia neutra e produz ajuste zero. Bonus exige ao
menos um relato e baixa recorrencia; evidencias negativas continuam gerando
penalidades. A confianca mede cobertura de dados e permanece separada da nota.

## Principal vantagem e fator limitante

A principal vantagem e escolhida pela maior contribuicao efetiva:
`score normalizado * peso aplicado`. O fator limitante usa a maior perda
ponderada ou, quando maior, uma penalidade, evidencia negativa ou trava de
coerencia. Indicadores informativos sem peso direto, como `risk_score` e
`resale_score`, nao podem ser apresentados como causa principal do ranking.
Os campos `main_advantage_source`, `main_advantage_impact`, `main_risk_source`
e `main_risk_impact` tornam essa escolha auditavel.

## Localizacao do banco

Sem `DATABASE_URL`, o SQLite fica em `backend/sigra.db`. URLs SQLite relativas
tambem sao resolvidas a partir de `backend`, independentemente do diretorio de
execucao. URLs absolutas e bancos externos continuam configuraveis pela
variavel de ambiente. Nenhum banco antigo e removido automaticamente.

## Ajustes limitados

O ajuste contextual considera categoria, faixa de compra, uso e capacidade financeira. Ele nunca adiciona mais de 8 pontos. Isso impede que varios bonus escondidos transformem uma opcao apenas razoavel em uma recomendacao quase perfeita.

Relatos reais e analise de pecas ficam em `evidence_adjustment`. Eles nao sao escondidos dentro do ajuste contextual.

## Travas de coerencia

A nota final possui limites obrigatorios quando:

- compra ou TCO nao cabem nos limites informados;
- o TCO excede o limite mensal em mais de 25% ou 50%;
- a aderencia ao uso e insuficiente;
- a eficiencia financeira ou disponibilidade de pecas e fraca;
- relatos reais relevantes indicam risco;
- algum criterio essencial esta abaixo de 60/100.

As travas aplicadas aparecem em `score_breakdown.guardrails`.

## Confianca dos dados

`confidence` nao altera a Nota SIGRA. Ele informa quanto respaldo de dados existe para interpretar a recomendacao.

- Base demonstrativa sem validacao suficiente: confianca baixa.
- Base com analise de pecas ou alguns relatos: confianca moderada.
- O MVP limita a confianca a 80/100, pois ainda nao usa precos, seguros e historicos completos de fontes oficiais em tempo real.

Assim, o sistema separa duas perguntas:

1. Este veiculo combina com o perfil?
2. Quanto respaldo de dados existe para sustentar essa conclusao?

## Formula resumida

```text
nota_base = soma(nota_criterio * peso_criterio)

nota_preliminar =
    nota_base
    + ajuste_contextual_limitado
    + ajuste_de_evidencias

nota_sigra = aplicar_travas_de_coerencia(nota_preliminar)
```

## Limites academicos

Os valores de veiculos, manutencao, seguro, IPVA, depreciacao, confiabilidade e pecas continuam demonstrativos. A arquitetura esta pronta para receber fontes reais, mas a interface deve comunicar essa limitacao ao usuario.
