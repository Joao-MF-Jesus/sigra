# Guardrails candidatos para motocicletas V1

> Especificação futura. Nenhuma regra abaixo participa de recomendação nesta versão.

## Princípios

- segurança e experiência não são determinadas apenas pela cilindrada;
- ausência de dado não vira valor médio ou zero;
- altura do usuário não determina sozinha compatibilidade;
- avisos explicam evidências e limites, sem certificar segurança;
- recomendações futuras não substituem treinamento, manual, legislação ou avaliação presencial.

## Classificação das regras candidatas

| Situação | Classe candidata | Tratamento futuro e evidência necessária |
|---|---|---|
| categoria fora do escopo | exclusão | não avaliar até existir domínio, dados e testes próprios |
| cilindrada/ano fora do MVP | exclusão | regra de domínio versionada, sem afirmar inadequação universal |
| dado demonstrativo | exclusão | manter no CRUD como `demonstration_only`, fora de decisão |
| campo objetivo indispensável ausente | requisito obrigatório | estado `incomplete`; informar campo faltante |
| fonte indispensável com baixa confiança | redução de confiança | `insufficient_confidence`, sem nota ou ranking |
| preço/ficha técnica sem atualidade | redução de confiança | `outdated_data` e data ausente/antiga explicada |
| preço acima do orçamento | requisito obrigatório ou alternativa comparativa | depende da política financeira futura |
| TCO acima do limite mensal | requisito obrigatório ou alternativa comparativa | exige TCO com cobertura mínima aprovada |
| ABS exigido pelo usuário e ausente | requisito obrigatório | preferência explícita + fonte técnica |
| esportiva/conjunto de alto desempenho para sem experiência | exclusão ou penalidade futura | combinar categoria, peso/potência, torque, entrega e experiência |
| relação peso/potência elevada | penalidade futura ou aviso | limiares especialistas, nunca dado isolado |
| peso elevado para preferência declarada | penalidade futura ou aviso | combinar manejo, assento e autodeclaração |
| assento alto para preferência de banco baixo | aviso | comparação objetiva, sem promessa de apoio físico |
| estrada frequente sem autonomia/desempenho útil | penalidade futura ou aviso | consumo, tanque, potência, proteção e carga |
| passageiro frequente sem dados/carga suficientes | requisito ou aviso | carga útil e evidências de passageiro |
| baixa autonomia | penalidade futura ou aviso | rota/uso declarado e cálculo rastreável |
| equipamentos e limitações relevantes | informação educativa | apresentar recurso, fonte e alcance da informação |

## Aprovação futura

Cada regra precisará de justificativa, limiar, comportamento em fronteiras, análise de sensibilidade, revisão técnica e casos que demonstrem quando não deve ser aplicada. Até lá, apenas a elegibilidade estrutural implementada pode classificar prontidão dos registros.
