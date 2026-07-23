# Plano de integracao futura com o recomendador

Este documento descreve evolucao futura. Nada abaixo participa da Nota SIGRA, do ranking de automoveis ou do endpoint reservado de motocicletas na versao atual.

## Possiveis papeis

### Filtro

Excluir da analise financeira um veiculo sem qualquer cenario compativel com entrada, prazo e parcela maxima explicitamente informados.

### Guardrail

Sinalizar quando parcela mais custos de uso excedem o orcamento mensal. Antes de ativar, sera necessario decidir como lidar com custos ausentes e ofertas com datas diferentes.

### Criterio explicavel

Comparar sustentabilidade da aquisicao sem premiar isoladamente a menor parcela. O modelo deve observar custo total, prazo, encargos e margem mensal.

### Explicacao

Exemplo futuro: "Este veiculo permaneceu viavel porque a entrada reduziu o saldo financiado e o desembolso mensal ficou dentro do limite informado."

## Condicoes antes da integracao

1. Definir contrato de perfil financeiro sem coletar dados bancarios sensiveis.
2. Validar cenarios com especialistas e casos reais anonimizados.
3. Versionar premissas e origem das propostas.
4. Criar regressao independente para rankings com e sem financiamento.
5. Definir politica para ofertas vencidas.
6. Garantir que confianca da proposta seja separada da nota.
7. Medir impacto antes de alterar pesos, filtros ou guardrails.

## Fora do escopo atual

- alterar `algorithm_version=2.1.2`;
- alterar `weights_version=cars-v1`;
- usar parcela no TCO atual;
- criar Nota SIGRA de motocicletas;
- recomendar bancos ou financeiras;
- prever aprovacao de credito.
