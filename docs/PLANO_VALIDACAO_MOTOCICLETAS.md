# Plano de validação do futuro recomendador de motocicletas

> Plano futuro. Nenhuma calibração, AHP ou aprendizagem de máquina foi executada.

## Validação estrutural já disponível em 0.3.0

A suíte atual cobre ficha sem métricas, separação e validação de métricas, fontes por grupo, unicidade da fonte principal, cascatas, migração idempotente, preservação dos automóveis, ausência de fontes falsas, estados estruturais de elegibilidade, resposta HTTP 501 e interface sem Nota ou ranking. Esses testes validam a fundação; não validam qualidade de recomendação.

## Etapas

1. Revisar campos, critérios e linguagem com motociclistas de diferentes níveis.
2. Revisar manutenção, desgaste e segurança com mecânico ou profissional técnico.
3. Validar o formulário com usuários leigos por questionário e teste de compreensão.
4. Construir base auditável de 20 a 30 modelos do escopo aprovado.
5. Definir rubricas objetivas e registrar divergências entre especialistas.
6. Propor pesos somente após análise de dependências; AHP pode apoiar validação, não substituir julgamento.
7. Executar análise de sensibilidade alterando um critério por vez.
8. Comparar estratégias e verificar se produzem diferenças justificáveis.
9. Criar fixture imutável independente do banco vivo e de APIs externas.
10. Validar explicações com usuários antes da disponibilização.

## Cenários obrigatórios

- iniciante com orçamento alto e preferência por moto esportiva;
- iniciante sem opção segura;
- exigência de ABS sem modelos elegíveis;
- uso urbano intenso e trabalho/entregas;
- viagem frequente com passageiro e bagagem;
- limite mensal inviável;
- moto barata com manutenção elevada;
- moto mais cara com menor custo operacional;
- dados incompletos, antigos, conflitantes ou de baixa confiança;
- empates completos e inversão da ordem de entrada.

## Métricas de qualidade

- estabilidade do top N sob pequenas variações;
- sensibilidade coerente a mudanças relevantes;
- diferenciação real entre estratégias;
- taxa de casos sem opção segura tratados corretamente;
- concordância e divergência dos especialistas;
- compreensão da explicação pelo usuário;
- cobertura e confiança dos dados;
- regressão determinística de ranking, status e guardrails.

## Critérios de liberação

Não liberar o ranking enquanto não houver dados mínimos auditáveis, rubricas revisadas, guardrails testados, explicações consistentes e separação comprovada entre confiança e adequação. Machine learning, DEA e recomendação entre carros e motos permanecem fora do escopo.
