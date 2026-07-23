# Roteiro de defesa - SIGRA

## 1. Abertura

Apresente o SIGRA como um MVP academico para apoiar usuarios leigos na escolha de veiculos. O foco e transformar criterios dispersos como preco, consumo, manutencao e uso principal em uma recomendacao explicavel.

## 2. Problema

Muitos compradores avaliam carros apenas por preco de compra. O sistema demonstra que a decisao tambem deve considerar custo mensal, consumo, confiabilidade, disponibilidade de pecas, depreciacao e adequacao ao perfil de uso.

## 3. Arquitetura

- Frontend: React com Vite.
- Backend: FastAPI.
- Banco local: SQLite por padrao.
- Banco evolutivo: PostgreSQL via Docker Compose.
- Regra de negocio: modulo separado em `backend/app/recommender.py`.

## 4. Demo sugerida

1. Rodar o projeto localmente seguindo o README, sem depender de `.venv`, `node_modules` ou banco empacotado.
2. Abrir o frontend e mostrar que ele inicia em modo visitante.
3. Explicar que o visitante ja consegue simular sem cadastro.
4. Alterar orcamento, limite mensal, uso principal e quilometragem.
5. Explicar que a recomendacao recalcula e mostra justificativas.
6. Abrir uma ficha tecnica.
7. Ir para comparacao e mostrar indicadores lado a lado.
8. Ir para busca online e explicar que os links externos sao demonstrativos.
9. Ir para despesas e mostrar que o registro exige login.
10. Entrar como usuario: `usuario@sigra.local` / `usuario123`.
11. Registrar uma despesa.
12. Abrir "Meu carro" e mostrar veiculos cadastrados, alertas preventivos e estatisticas do modelo.
13. Registrar um problema ou consumo real e explicar que isso alimenta os dados agregados.
14. Voltar para recomendacao e mostrar que os dados reais podem ajustar a nota.
15. Abrir "Pecas" e mostrar o Indice SIGRA de Manutencao, variacao de preco e compatibilidade.
16. Explicar que os precos/fornecedores sao demonstrativos e sem scraping real nesta etapa.
17. Sair e entrar como admin: `admin@sigra.local` / `admin123`.
18. Mostrar o painel administrativo com resumo dos dados.

## 5. Pontos para destacar

- A recomendacao nao e uma caixa-preta: cada resultado tem pontuacao, custo mensal e justificativas.
- A area "Meu carro" demonstra continuidade de uso apos a compra, com historico, relatos reais e alertas preventivos.
- A analise de pecas mostra facilidade de manutencao, fornecedores e alerta contra preco muito acima da media.
- A base atual tem 34 veiculos demonstrativos, adequada para MVP academico.
- O projeto foi estruturado para trocar a base por dados reais no futuro.
- A API possui documentacao automatica em `/docs`.

## 6. Fala curta sobre o algoritmo

"A recomendacao usa pesos por perfil. Primeiro o sistema normaliza criterios como preco, consumo, custo mensal, manutencao, confiabilidade, pecas e depreciacao. Depois aplica pesos diferentes conforme o uso: cidade prioriza custo e consumo; familia e estrada priorizam aderencia e confiabilidade; aplicativo prioriza custo mensal; SUV/espaco prioriza aderencia ao perfil. Por isso o resultado e explicavel e nao uma caixa-preta."

## 7. Fala curta sobre dados reais e alertas

"Apos a compra, o usuario pode continuar usando o SIGRA na area Meu carro. Ele registra km atual, problemas, custos de reparo e consumo real. O sistema agrega esses relatos por modelo, calcula indice de risco e mostra alertas preventivos quando o carro se aproxima de uma quilometragem em que outros usuarios relataram problemas."

## 8. Fala curta sobre pecas e manutencao

"O SIGRA tambem calcula um Indice de Manutencao com base em pecas importantes, fornecedores demonstrativos, variacao de preco e compatibilidade com outros modelos. Isso ajuda o usuario leigo a perceber se um carro tende a ser facil de manter e se uma peca pode estar com preco muito acima da media."

## 9. Fala curta sobre a base demonstrativa

"A base atual foi criada para validar o funcionamento do MVP. Ela nao substitui cotacao real. Em uma evolucao, o sistema pode integrar FIPE, seguradoras, oficinas, marketplaces e bases curadas para alimentar esses mesmos criterios com dados reais."

## 10. Encerramento

Concluir dizendo que o SIGRA valida o fluxo completo: cadastro/base de veiculos, perfil do usuario, recomendacao, comparacao, custos e possibilidade de evolucao para dados reais e autenticacao completa.
