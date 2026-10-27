# Personalização: sete critérios e evidências

A política de referência continua sendo `user-profile-multifactor-v1`, implementada
em `backend/app/multifactor_recommendation.py`, sem mudança de fórmula, peso,
desempate ou tratamento de ausência. Esta integração adiciona somente o contrato
diagnóstico `seven-criteria-diagnostics-v1`.

Pesos iniciais: combustível 25%, adequação ao uso 20%, conforto 10%, segurança
15%, desempenho rodoviário 10%, eficiência 10%, qualidade histórica 10%.
O campo histórico `total_cost` significa custo **de combustível no horizonte**,
não TCO completo. Os demais componentes do TCO continuam exibidos separadamente.

## Entradas e cálculo

| Critério | Entrada exigida pela política original | Cálculo preservado |
| --- | --- | --- |
| Combustível | Quilometragem, divisão urbano/rodoviário, consumos do combustível, preço e horizonte | Fórmula Decimal existente; min/max inverso do custo de combustível |
| Adequação ao uso | `usage_score` específico do uso, com avaliação comprovada | Nota original, sem substituir pelo escore v4 |
| Conforto | `comfort_score` documentado da versão | Nota original, não dimensões nem índice de habitabilidade |
| Segurança | `safety_score` na escala do método original | Nota original; inventário airbags/ABS/ESC não é essa avaliação |
| Desempenho | `road_score` documentado | Nota original, não potência ou uma avaliação inventada |
| Eficiência | Consumos urbano/rodoviário compatíveis com o combustível | Consumo combinado da fórmula existente; min/max direto |
| Qualidade histórica | Manutenção, confiabilidade, peças e desvalorização na política original | Média dos quatro subcritérios somente quando todos estão disponíveis |

Manutenção e desvalorização recuperadas pelo adaptador anterior continuam
**estimativas de cenário** (`legacy-scenario-subcriteria-v1`). Não completam,
isoladamente, qualidade histórica. Sem confiabilidade e peças, a nota permanece
nula. Não são criadas novas rubricas para preencher essas lacunas.

## Diagnósticos, pesos e ordem

- Todos os sete critérios retornam peso informado, percentual normalizado,
  disponibilidade, entradas/unidades/origem, contribuição e razão da ausência.
- A normalização dos pesos usa a soma de **todos** os pesos enviados, como na
  política original. Não normaliza novamente somente os critérios disponíveis.
- Para veículos efetivamente pontuados, notas e contribuições são copiadas do
  motor. A população min/max é exatamente a usada pelo motor naquele grupo.
- Para veículos sem nota final, combustível/eficiência recebem subcálculos
  diagnósticos usando membros com simulação válida do mesmo grupo de comparação.
  A população e os intervalos são explícitos. Esses subcálculos não são somados,
  não reordenam a classificação, nem equivalem a uma nota parcial.
- Peso positivo sem evidência: nota e contribuição nulas, sem nota final.
  Peso zero sem evidência: nota nula e contribuição aritmética zero; não imputação.
- Entradas iguais usam a regra original de 100, explicitamente sem discriminação
  entre os veículos.
- Consumo manual fica identificado como entrada do usuário e sem atribuição
  falsa ao PBEV. Sem consumo compatível (por exemplo, etanol sem evidência) ou
  preço ANP disponível e sem preço manual, os dois cálculos ficam indisponíveis.

## Interface e preservação

Os controles, cards e modal existentes são reutilizados. O detalhamento apresenta
os sete pesos, notas disponíveis e contribuições, com dados utilizados recolhidos.
Erros de consumo manual são apresentados e vinculados aos campos acessíveis.
Nenhuma aba acadêmica, vínculo operacional de identidade ou ativação é criado.

O V6 aprovado e a Revision6 continuam separados. Os nove inventários admitidos
em Família/Estrada não são promovidos para notas originais de segurança.
As demais elegibilidades documentais, custos, catálogo de 60 e desconhecidos não
são alterados. A integração PostgreSQL permanece, mas sua homologação real não
é executada nesta etapa offline.

## Verificação isolada

Os testes de `test_academic_seven_criteria.py` usam observações e notas
explicitamente fictícias somente nos testes: validam cada peso até o motor,
contribuições, ausência positiva, peso zero, origens, população de normalização,
idempotência e contrato HTTP com repositório em memória. Nenhuma nota fictícia é
inserida no catálogo. O teste de todos os sete critérios calculáveis comprova o
algoritmo, não a existência das avaliações originais nos 60 veículos reais.

Os relatórios offline de cobertura devem separar implementação disponível de
evidência ausente. A conclusão dos sete critérios sobre o catálogo depende de
avaliações por versão/uso na escala original e evidência de confiabilidade/peças;
dados dimensionais, potência ou equipamentos não substituem essas entradas.
