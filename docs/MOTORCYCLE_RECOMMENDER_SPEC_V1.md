# Especificação técnica do futuro recomendador de motocicletas V1

**Status:** contrato metodológico em preparação  
**Módulo:** `motorcycles`  
**Versão do módulo:** `0.3.0`  
**Versão do algoritmo:** `null`  
**Versão dos pesos:** `null`  
**Versão do método de métricas derivadas:** `null`

Esta especificação não afirma que o SIGRA já recomenda motocicletas. Ela fixa o vocabulário, os dados e as decisões que deverão ser aprovados antes de qualquer Nota SIGRA, peso ou ranking.

## Legenda de maturidade

- **Implementado:** existe no código e possui teste.
- **Preparado:** estrutura técnica existe, mas ainda não toma decisão de recomendação.
- **Proposta metodológica:** hipótese documentada, sem implementação.
- **Decisão pendente:** exige evidência, especialista ou validação empírica.
- **Implementação futura:** depende da aprovação desta especificação.

## 1. Objetivo do recomendador

**Proposta metodológica.** Apoiar usuários leigos na comparação de motocicletas compatíveis com orçamento, custo de propriedade, uso, experiência e preferências de segurança. O resultado futuro deverá ser explicável e apresentar limitações, nunca certificar segurança ou substituir avaliação presencial.

## 2. Público-alvo

**Proposta metodológica.** Pessoas buscando a primeira motocicleta ou uma opção de baixa/média cilindrada para deslocamento, trabalho, economia, uso misto leve ou estrada ocasional. O sistema não deve inferir habilidade por idade, gênero, renda ou altura.

## 3. Escopo do MVP

**Decisão pendente.** Mercado brasileiro, motocicletas novas ou usadas recentes, dados rastreáveis, categorias de uso cotidiano e aproximadamente 100 a 500 cm³. O primeiro algoritmo deverá comparar somente registros estruturalmente elegíveis.

## 4. Categorias suportadas

**Preparado.** `scooter`, `underbone`, `street`, `naked` e `trail`. A elegibilidade estrutural reconhece essas categorias, mas ainda não mede adequação ao usuário.

## 5. Categorias excluídas

**Preparado.** Superbike, touring pesada, adventure de alta cilindrada, custom pesada, competição e off-road exclusivo ficam fora do primeiro MVP. Novas categorias exigem revisão do domínio, dos dados e dos guardrails.

## 6. Faixa de cilindrada

**Preparado.** De 100 a 500 cm³ para elegibilidade estrutural. Cilindrada é apenas limite de domínio; não será usada isoladamente como indicador de dificuldade, segurança ou desempenho.

## 7. Faixa de anos

**Preparado.** Modelos de 2018 em diante. O ano máximo aceito é o ano corrente mais um, para permitir catálogo do próximo ano-modelo. A política deverá ser revisada quando houver série histórica suficiente.

## 8. Perfil do motociclista

**Proposta metodológica.** O perfil futuro terá grupos financeiros, experiência, uso, ergonomia e preferências de segurança. Ele não está conectado ao endpoint reservado e não produz recomendação.

## 9. Campos obrigatórios do perfil

| Campo candidato | Finalidade futura | Risco e ausência |
|---|---|---|
| `purchase_budget` | verificar viabilidade de aquisição | sem valor, não há avaliação financeira |
| `monthly_cost_limit` | comparar com TCO desembolsável | não inclui parcela de financiamento |
| `monthly_mileage_km` | estimar custos por uso | zero é válido; vazio não vira zero |
| `fuel_price_per_liter` | estimar combustível | exige valor declarado e referência temporal |
| `experience_level` | aplicar guardrails candidatos | autodeclaração não certifica habilidade |
| `primary_use` | orientar critérios de adequação | domínio controlado; sem fallback silencioso |
| `abs_required` | respeitar preferência explícita | ausência deve ser perguntada, não inferida |

**Decisão pendente.** Domínios candidatos para experiência: `never_ridden`, `beginner`, `intermediate`, `experienced`. Usos candidatos: urbano, trabalho/entregas, aplicativo, misto, estrada ocasional, viagem frequente e lazer.

## 10. Campos opcionais do perfil

| Campo candidato | Impacto futuro | Tratamento da ausência |
|---|---|---|
| entrada disponível | simulação de aquisição separada | não altera TCO operacional |
| tempo de habilitação | contexto de experiência | não substituir autodeclaração |
| experiência urbana/estrada/passageiro | guardrails contextuais | desconhecido, sem penalidade automática |
| passageiro frequente | adequação de carga e passageiro | não inferir pelo uso principal |
| necessidade de bagagem | capacidade e acessórios | manter como preferência |
| altura do condutor | contexto ergonômico | nunca concluir compatibilidade sozinho |
| preferência por banco baixo | comparação de assento | não prometer apoio dos dois pés |
| tolerância a peso | facilidade de manejo declarada | não fazer afirmação biomecânica |
| posição de pilotagem preferida | ergonomia | exige taxonomia e fonte sustentáveis |
| prioridade de facilidade de controle | estratégia futura | não equivale a certificação de segurança |
| tolerância a desempenho | guardrail contextual | decisão autodeclarada |
| interesse em controle de tração | preferência de equipamento | não confundir presença com adequação total |

Financiamento será simulação separada com entrada, taxa e prazo informados; não será incorporado silenciosamente ao TCO.

## 11. Dados mínimos da motocicleta

**Implementado/Preparado.** A tabela objetiva é a fonte de verdade para a ficha técnica. Campos legados permanecem somente para leitura/migração compatível.

| Campo | Classificação | Decisão sustentada | Fonte comparável | Banco agora | Sobreposição |
|---|---|---|---|---|---|
| marca, modelo, versão, ano | cadastro | identidade inequívoca | fabricante/documento | sim | nenhuma |
| condição nova/usada e combustível | elegibilidade futura | contexto de mercado/energia | anúncio ou documento | sim | preço/TCO |
| categoria e cilindrada em cm³ | cadastro/elegibilidade | domínio do MVP | fabricante | sim | não pontuar isoladamente |
| preço e data de referência | elegibilidade futura | compra e depreciação | fonte de mercado datada | sim | controlar dupla contagem |
| consumo urbano/rodoviário em km/l | TCO futuro | combustível e autonomia | ensaio/metodologia | sim | usar como entrada, não bônus paralelo |
| manutenção anual em reais | TCO futuro | custo preventivo agregado | plano/metodologia | sim | evitar somar itens já incluídos |
| peso em ordem de marcha em kg | cadastro | ergonomia/controle futuros | fabricante | sim | uma entrada para rubricas |
| altura do assento em mm | cadastro | contexto ergonômico | fabricante | sim | não afirmar encaixe físico |
| tanque em litros | cadastro | autonomia derivável | fabricante | sim | autonomia substitui soma paralela |
| ABS e quantidade de canais | cadastro/guardrail futuro | preferência e segurança | fabricante | sim | guardrail antes de eventual rubrica |
| potência em cv e torque em Nm | elegibilidade futura | experiência/estrada | fabricante | sim | relação peso/potência derivável |
| transmissão, marchas e transmissão final | elegibilidade/TCO futuro | operação e manutenção | fabricante/manual | sim | transmissão final entra no TCO |
| carga útil em kg | opcional | passageiro e bagagem | manual | sim | usar em indicador único |
| intervalo de óleo em km | opcional/TCO futuro | manutenção preventiva | manual | sim | não duplicar manutenção agregada |
| CBS e controle de tração | opcional | equipamento de segurança | fabricante | sim | não pontuar duas vezes |

**Adiados:** alimentação, refrigeração, distância entre eixos, posição de pilotagem, tipos detalhados de freio, medidas e custos de pneus. Eles só entram após demonstrar decisão sustentada, cobertura e comparabilidade. Confiabilidade, disponibilidade de peças, depreciação e todas as notas são métricas derivadas, não fatos obrigatórios.

## 12. Estados de elegibilidade

**Implementado, sem pontuação.** `eligible`, `incomplete`, `insufficient_confidence`, `demonstration_only`, `excluded_by_domain_rule`, `unsupported_category` e `outdated_data`. Cada resposta contém códigos, campos e mensagens. Elegibilidade significa apenas prontidão estrutural para futura avaliação.

## 13. Política de fontes

**Implementado.** Fontes são registradas por grupo: identidade, preço, ficha técnica, consumo, manutenção, confiabilidade, peças, segurança, ergonomia, impostos, seguro e métricas derivadas. Uma moto pode ter várias fontes e no máximo uma principal por grupo. Fonte oficial exige nome; URL é validada; estimativa exige método ou referência; relato de usuário não pode expor e-mail. Nenhuma fonte é criada para preencher lacunas.

Os campos gerais de origem em `motorcycles` são compatibilidade legada. `motorcycle_data_sources` é a fonte de verdade por grupo. Divergências devem favorecer a estrutura agrupada e ser resolvidas por correção explícita, nunca por mesclagem silenciosa.

## 14. Política de confiança

**Preparado.** Confiança varia de 0 a 100 e mede qualidade/cobertura da evidência, não qualidade da motocicleta. Fontes primárias dos grupos indispensáveis precisam atingir 60 para o estado estrutural `eligible`. A futura confiança global deverá expor cobertura, atualidade e limitações e permanecer separada da eventual Nota SIGRA.

## 15. Política de atualidade

**Preparado.** Preço principal: até 548 dias; ficha técnica principal: até 1.825 dias. Ausência de data nesses grupos produz `outdated_data` quando os demais requisitos já existem. Prazos são configuração inicial, devem ser validados e não criam data fictícia.

## 16. TCO conceitual V1

**Proposta metodológica.** O TCO separará desembolso, custo econômico, aquisição, financiamento e equipamentos. Não existe cálculo de TCO de motos. A fórmula conceitual e a cobertura por componente estão em `TCO_MOTOCICLETAS.md`.

## 17. Critérios candidatos

**Proposta metodológica.** Viabilidade financeira, TCO, adequação urbana, trabalho, facilidade para iniciantes, segurança, ergonomia, manutenção, confiabilidade, peças, consumo, autonomia, passageiro, bagagem, estrada e risco econômico. Nenhum critério possui peso aprovado.

## 18. Matriz contra dupla contagem

**Proposta metodológica.** Dados que alimentam TCO ou rubricas compostas não devem ser premiados novamente como critérios independentes. A matriz de precedência está em `MATRIZ_CRITERIOS_MOTOCICLETAS.md` e deverá ser aprovada antes dos pesos.

## 19. Guardrails candidatos

**Proposta metodológica.** Regras candidatas são classificadas como exclusão, requisito obrigatório, penalidade futura, aviso, redução de confiança ou informação educativa. Não há guardrail funcional de recomendação. Consulte `GUARDRAILS_MOTOCICLETAS.md`.

## 20. Estratégias candidatas

| Estratégia | Público/objetivo | Prioridades candidatas | Diferença e risco |
|---|---|---|---|
| `beginner_friendly` | primeira moto; facilitar controle | guardrails, ergonomia, segurança, peso | não reduzir dificuldade à cilindrada |
| `urban_economy` | deslocamento urbano econômico | TCO, consumo, manejo urbano, peças | não duplicar consumo dentro e fora do TCO |
| `work_and_delivery` | uso profissional intensivo | TCO desembolsável, confiabilidade, peças, bagagem | não assumir que toda scooter serve para carga |
| `cost_benefit` | equilíbrio financeiro geral | compra, TCO, confiabilidade, manutenção | pode ficar genérica; exige contraste empírico |
| `balanced_use` | uso urbano e misto leve | uso, ergonomia, segurança, autonomia | evitar virar média sem identidade |
| `light_road_use` | estrada ocasional | autonomia, desempenho útil, estabilidade e segurança | não incentivar uso incompatível com experiência |

**Decisão pendente.** Estratégias redundantes serão removidas após testes de cenários. Não há pesos ou cálculo.

## 21. Rubricas candidatas

**Proposta metodológica.** `urban_score`, `road_score`, `passenger_comfort_score`, `luggage_score`, `ergonomics_score`, `beginner_friendliness_score`, `safety_score`, `maintenance_score`, `parts_availability_score` e `reliability_score` têm domínio controlado, mas não possuem fórmula. Escala candidata: 0 a 100, maior é melhor, com confiança e versão de método. Entradas, riscos e validação estão em `DADOS_E_INDICADORES_MOTOCICLETAS.md`.

`recommended_experience` será uma combinação futura de faixa derivada explicativa e resultado de guardrails. Não será um fato objetivo nem uma opinião obrigatória do cadastro.

## 22. Tratamento de dados ausentes

**Implementado/Preparado.** Ausência permanece `null`, não vira zero. Campo objetivo mínimo ausente deixa o registro incompleto; fonte indispensável ausente impede elegibilidade; métrica derivada ausente não invalida a ficha. Fallback só será permitido com fonte e regra documentadas.

## 23. Tratamento de dados demonstrativos

**Implementado.** O registro explicitamente demonstrativo ou uma fonte principal demonstrativa de identidade, ficha técnica ou preço recebe `demonstration_only`. Uma fonte secundária demonstrativa produz observação apenas no grupo. Dados demonstrativos podem ser exibidos no CRUD e nunca recebem Nota, ranking ou recomendação.

## 24. Explicabilidade futura

**Implementação futura.** Uma recomendação deverá informar elegibilidade, dados usados, cobertura, critérios e contribuições, guardrails acionados, custo coberto e ausente, vantagem, risco e limitações. Indicadores não ponderados não poderão aparecer como causa principal.

## 25. Versionamento

**Implementado/Preparado.** Módulo `0.3.0`; algoritmo, pesos e método calculado `null`. A migração `0.3.0` separa estimativas econômicas e torna fontes agrupadas canônicas. Métricas demonstrativas usam `demonstration-v0`. Qualquer algoritmo real deverá declarar versões próprias e não reutilizar `cars-v1`.

## 26. Plano de testes

**Preparado.** Cobrir validação objetiva, ausência de métricas, fontes por grupo, unicidade da principal, cascatas, migração idempotente, banco legado, estados de elegibilidade, resposta `501`, ausência de Nota/ranking, UI neutra e regressão imutável dos automóveis. Antes do algoritmo: cenários especialistas, análise de sensibilidade, empates, outliers e explicações por contribuição.

## 27. Critérios para aprovação dos pesos

**Decisão pendente.** Pesos só serão aprovados após: rubricas versionadas; cobertura mínima da base; revisão por especialista; matriz de dupla contagem; cenários de referência; estabilidade a pequenas variações; justificativas coerentes; comparação entre estratégias; documentação das escolhas e regressão congelada. Não haverá ajuste apenas para produzir um ranking desejado.

## 28. Itens fora do escopo

Nota SIGRA, ranking, recomendação, pesos, soma ponderada, TCO funcional, guardrails funcionais, comparação carro-moto, machine learning, AHP, DEA, financiamento integrado, diagnóstico mecânico, certificação de segurança e categorias de alta especialização.

## 29. Riscos

- baixa cobertura ou fontes heterogêneas;
- dados de consumo e custo não comparáveis;
- subjetividade nas rubricas;
- dupla contagem entre TCO e critérios;
- uso indevido de dados demonstrativos;
- inferências excessivas sobre ergonomia e experiência;
- falsa precisão por notas sem confiança suficiente;
- desatualização de preço, seguro, imposto e manutenção.

## 30. Limitações

O módulo atual é cadastro auditável e preparação estrutural. `eligible` não significa recomendado ou seguro. Não existem base real consolidada, TCO calculado, pesos aprovados, perfil conectado, Nota SIGRA ou ranking. O endpoint de recomendação permanece HTTP 501 até a aprovação metodológica e técnica de uma versão futura.
