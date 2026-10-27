# Coorte v6 no fluxo principal de Recomendação

## Fronteira e causa da integração anterior

O formulário enviava POST /recommendations. Esse handler carregava somente
public.vehicles, feedback operacional e peças; o banco acadêmico contém candidatos
em academic.cohort_vehicle, sem vínculos com public.vehicles. A aba separada
consultava avaliações congeladas e não executava o motor a partir da rotina do usuário.
A entrada “Teste acadêmico” foi removida da navegação.

## Contrato explícito e execução

GET /recommendations/metadata informa a fonte configurada no backend. Quando
ACADEMIC_COHORT_ENABLED=true, valida o snapshot PostgreSQL aprovado, seu manifesto,
fingerprints e cobertura, e retorna candidate_source=academic_v6, snapshot_id e
critérios/pesos do método. Uma falha não troca a coorte por cadastro vazio ou fixture.
Com a flag desabilitada, o fluxo operacional continua independente.

POST /recommendations?envelope=true mantém o endpoint principal. O opt-in envia:

- candidate_source=academic_v6 e academic_options.snapshot_id;
- use_case: cidade, app, trabalho, suv (Espaço/capacidade), familia ou estrada;
- budget e monthly_limit, filtros eliminatórios distintos;
- monthly_mileage positivo e fuel_price positivo;
- academic_options.scenario: low, base ou high;
- academic_options.criterion_weights: critérios documentais do perfil, disponíveis
  no contrato para diagnósticos; os controles visíveis de personalização enviam
  multifactor_profile.weights com os sete critérios históricos;
- recommendation_strategy: cost_benefit (classificação documental de referência) ou lowest_cost
  (TCO crescente, nota ponderada como desempate).

Outras estratégias legadas, pesos negativos, pesos
desconhecidos e opções acadêmicas enviadas ao fluxo operacional são rejeitados,
nunca aceitos sem efeito. Transmissão permanece com peso zero: sem preferência
explícita no contrato não existe uma ordenação universal de câmbios.

## Motor e custos

O adaptador lê todos os 60 payloads de evidência e revalida identidades e unidades.
As avaliações persistidas autorizam somente a cobertura documental do perfil.
Seus scores, TCOs e utilidades nunca são usados como entrada do ranking.

O cálculo reutiliza academic_cohort_v6._evaluate_extended_v4, com configuração de
cenário copiada em memória por requisição. Combustível = km mensais / consumo urbano
PBEV × preço por litro, com Decimal e arredondamento do contrato. Os cenários
baixo/base/alto preservam as taxas versionadas de IPVA, manutenção, seguro e
depreciação. Não há taxa nova ou custo demonstrativo copiado de outro veículo.

As utilidades absolutas e o proxy de habitabilidade são os existentes da v4.
Pesos explícitos recompõem contribuições com a mesma normalização Decimal v3/v4
(resíduo no último critério), sem alterar arquivos/fingerprints da metodologia.
Os pesos padrão da referência reproduzem a metodologia acadêmica v4, não o
recomendador operacional histórico. Requisitos
documentais continuam eliminatórios, mesmo quando um peso é zero.

O recomendador legado requer notas de confiabilidade, peças e qualidade não
observadas na coorte. Não são criados objetos Vehicle com scores padrão/fictícios
para simular essa compatibilidade: a referência da coorte é explicitamente v4.

## Restauração da personalização e da apresentação

Os controles anteriores de personalização foram restaurados: opt-in, sete pesos,
divisão cidade/estrada, distância, combustível, origem/preço manual, horizonte,
UF/município/semana e consumos informados. O payload multifactor_profile preserva
o contrato existente. O adaptador chama apply_multifactor_ranking, com a mesma
normalização, exigência de evidência e desempates da política anterior.
Critérios v4 não são convertidos em notas de conforto, segurança ou qualidade.

O cálculo misto de combustível reutiliza a política Decimal existente de simulação.
Sua contribuição substitui apenas o combustível do TCO de cenário; as demais
hipóteses versionadas ficam preservadas. Orçamento e limite mensal são aplicados
ao resultado recalculado. Horizonte aparece na projeção de combustível, não em
taxas silenciosamente alteradas de manutenção ou depreciação.

Com pesos positivos em critérios cujas notas não estão comprovadas, a composição
personalizada permanece indisponível e conserva a ordem de referência, com aviso
único. Pesos zero não transformam ausências em observações. Preço ANP regional
e consumo de etanol ausentes não recebem fallback falso: a resposta indica que
o cenário não foi aplicado. Preço manual e consumo fornecido são entradas do
usuário, nunca evidência observada do veículo.

As seis opções antigas de prioridade voltaram à interface. Quatro dependem de
notas operacionais ausentes nesta coorte e são rejeitadas com explicação antes
de executar, em vez de serem aceitas com comportamento de outra estratégia.
Assim, a restauração visual não é uma alegação de disponibilidade de todas as
estratégias históricas para os 60 veículos.

Cards e modal reutilizam os componentes/layout anteriores, com FIPE, referência,
unidades em português e composição do TCO atual. Proveniência continua no
payload; fontes e limitações ficam recolhidas. IDs acadêmicos continuam proibidos
em operações de Meu carro, Peças e Despesas sem vínculo real.

## Resultado, identidade e limites

Cada item contém catalog_id, identity_namespace=academic_v6 e
operational_vehicle_id=null. Nenhum ID acadêmico entra em Meu carro, Despesas,
Peças ou Comparar operacional. O detalhe usa somente o endpoint acadêmico, com
snapshot fixo, mas mostra o TCO/critério da execução atual, não a avaliação congelada.

O resultado declara ranking_executed=true e stored_scores_used=false. Isso significa
execução em memória para o cenário do usuário, não publicação ou ativação Gold.
operationally_active=false e recommended=false continuam explícitos; nenhuma
flag ou tabela persistida é alterada. TCO é scenario_estimate; habitabilidade é
derived_academic, não espaço interno medido. Confiança não recebe percentual inventado.

Posições são locais a grupos com a mesma evidência/protocolo. Não se cria ordem
global entre grupos incompatíveis. Empates de nota usam catalog_id apenas para
ordem determinística de exibição, não preferência substantiva.

Cobertura máxima do snapshot: Cidade 10, Aplicativo 60, Trabalho 10, Espaço 24,
Família 1, Estrada 1. Filtros financeiros podem reduzir esses totais. A resposta
explica separadamente orçamento de compra, limite mensal, TCO incompleto e
exigências documentais; não oferece fallback inelegível.

## Inicialização e verificação

Reinicie o backend que já usa sigra_academic_v6_test, no terminal seguro de origem.
Não aplique migrations, materialize novamente, ou aponte para o banco demo.
O launcher externo start-academic-v6-existing-backend.py exige
DATA_PLATFORM_TEST_POSTGRESQL_URL nesse processo, valida banco e host exatos e
não persiste credenciais. A porta 8010 deve estar livre; ele não encerra processos.

Frontend: VITE_API_URL=http://127.0.0.1:8010, npm run dev -- --host 127.0.0.1
--port 5173 --strictPort. Não é necessária flag VITE_ACADEMIC_TEST_MODE ou aba especial.
O modo decorre do contrato de metadata do backend, não do hash do navegador.

Smoke manual: Aplicativo, orçamento 1000000, limite mensal 100000, 1000 km/mês,
R$ 6/l, cenário base, pesos padrão. A página deve mostrar 60 candidatos únicos e
60 elegíveis. Abra detalhes, varie km/preço do combustível, orçamento, cenário e
pesos e recalcule. Confira Família/Estrada: somente uma configuração coberta.
O smoke externo validate-main-cohort-http.ps1 verifica os mesmos contratos sem
SQL, segredo, migration, bootstrap ou escrita. Aprovação visual continua humana.

## Diagnóstico de personalização e elegibilidade

Solicitar o perfil multifator não significa obter uma nota. A política original
`user-profile-multifactor-v1` exige evidência de todos os critérios com peso
positivo. Com os pesos iniciais 25/20/10/15/10/10/10, combustível e eficiência
cobrem 35% do peso; as notas de adequação ao uso, conforto, segurança, desempenho
rodoviário e qualidade histórica não estão comprovadas nos 60 payloads.
O `neutral_score=50` de `academic_demo_v1` expressa ausência de evidência, não
uma observação aceitável. Habitabilidade v4 e inventário de equipamentos não
podem ser convertidos nessas notas. Não se renormalizam os pesos ausentes.

`multifactor.evidence_coverage` apresenta os sete critérios, pesos recebidos,
entradas exigidas, disponibilidade e critérios solicitados não avaliados.
A cobertura dos cards e detalhes usa esse contrato quando há personalização,
nunca a cobertura documental v4. Uma nota de referência permanece explicitamente
de referência. Os controles e valores iniciais não foram trocados.

O critério original `total_cost` normaliza a projeção de **combustível** no
horizonte, não o TCO completo exibido. Este conserva combustível, manutenção,
IPVA, seguro e depreciação de cenário. A descrição das fontes distingue ambos;
nenhuma fórmula original foi alterada nesta correção.

`candidate_diagnostics` explica os 60 candidatos, inclusive os excluídos, e
separa requisitos documentais dos limites financeiros. `exclusion_counts` conta
cada motivo de forma independente (um veículo pode ter mais de um motivo).
O campo obrigatório considera exclusivamente o perfil atual; um peso zero não
remove uma exigência documental. Cidade/Trabalho exigem comprimento e largura
com retrovisores abertos, não apenas largura corporal. Família/Estrada exigem
o inventário de segurança ou o caminho de teste compatível já aprovado.

O auditor externo `audit-personalization-evidence.py --phase after` verifica a
API local real, compara os 60 payloads com o replay aprovado, gera a matriz
60 × 6 e compara contribuições de dois conjuntos explícitos de pesos suportados.
Também separa o limite mensal de R$ 1.200 do caso R$ 1.800. O auditor de caches
verifica SHA-256 sem rede e distingue rótulos brutos ainda não admitidos no
manifesto de perdas no adaptador PostgreSQL. Um rótulo bruto não autoriza
alterar o snapshot aprovado nem os gates de publicação.

## Recuperação das fórmulas originais, sem mudança de significado

A inspeção dos commits `103ab2e`, `c9cb60b` e `a5d4d34` e do backup
`profile-v3-local-validation-ababc5aaab/source-mirror` confirma a origem:
`sample_data.SEGMENT_DATA` fornece notas demonstrativas de conforto, segurança,
uso e desempenho. Não há nesses arquivos uma fórmula que transforme dimensões,
potência ou equipamentos em tais notas. `recommender.py` do backup tem os mesmos
bytes da versão atual. O exemplo demonstrativo não é evidência para a coorte.

| Critério | Regra original e entrada | Situação nesta integração |
| --- | --- | --- |
| Custo | Normalização inversa da projeção de combustível no horizonte | Calculado com cenário informado e consumo admissível; não é o TCO completo |
| Adequação ao uso | 55% `profile_fit_score` + 45% avaliação específica do uso; Trabalho combina urbano/aplicativo/espaço; Espaço combina estrada/família/espaço/conforto | Classificação de usos e avaliações originais não comprovadas; elegibilidade v4 não substitui essas entradas |
| Conforto | Nota 0–100 recebida do catálogo | Notas originais demonstrativas; nenhuma rubrica de cálculo por atributos recuperada |
| Segurança | Nota 0–100 recebida do catálogo | Inventário ou Latin NCAP não têm conversão aprovada para essa escala; manter ausência |
| Desempenho rodoviário | `road_score` recebido do catálogo | Nenhuma rubrica de comportamento rodoviário recuperada; potência não substitui a avaliação |
| Eficiência | Normalização positiva do consumo ponderado cidade/estrada | Calculado com PBEV ou consumo explícito do usuário |
| Qualidade histórica | Média das quatro notas de manutenção, confiabilidade, peças e desvalorização; exige todas | Recuperadas apenas manutenção/desvalorização de cenário; confiabilidade e peças permanecem ausentes, média indisponível |

O adaptador executa agora os subcálculos originais recuperáveis em
`legacy_calculations.py`, antes de eliminar candidatos por documentação/orçamento:

- manutenção: `0.25 * normalize_cost(annual_maintenance) + 0.35 * absolute +
  0.40 * maintenance_index`, com `absolute=clamp(100-annual_maintenance/70)`;
  sem feedback comprovado, o fallback original é `maintenance_index=absolute`;
- desvalorização: `normalize_cost(annual_depreciation_rate)`;
- `normalize_cost(x)=(max-x)/(max-min)*100`; intervalo igual retorna 100 pela
  regra original, **sem poder discriminatório**, não por preenchimento de lacuna.

As entradas anuais vêm dos parâmetros explícitos de `academic_cost_scenario_v1`
e preço FIPE observado, não de custo mensal arredondado multiplicado por doze.
A normalização usa os 60 candidatos antes dos filtros, como no motor original.
Precisão/clamp/arredondamento são comparados diretamente com
`recommender.build_score_components`. Nenhuma taxa foi criada ou alterada.
As subnotas têm natureza `scenario_estimate`, fórmula, parâmetros, fontes e
população de comparação. **Não são observações históricas**. Não se inventam
confiabilidade, peças ou feedback; `legacy_quality` continua indisponível.

### Proposta metodológica separada — não aplicada

Completar os sete critérios exige uma decisão explícita e versionada, não apenas
um novo mapeamento. Caminho mínimo preservando os significados:

1. Adequação: aprovar rubrica por uso com entradas observáveis, escala 0–100,
   critérios eliminatórios e tratamento de ausência; validar etiquetas de uso e
   avaliações específicas. Somente depois reutilizar a combinação 55/45 original.
2. Conforto: obter avaliação padronizada da versão (assentos, ruído, suspensão e
   ergonomia) com rubrica publicada; dimensões externas podem ser descritas,
   mas não equivalem a conforto nem a espaço interno medido.
3. Segurança: aprovar conversão por configuração e protocolo compatível de teste
   ou rubrica de equipamentos, mantendo essas duas bases em grupos separados.
   Não comparar estrelas de protocolos distintos nem inferir equipamento.
4. Desempenho: avaliação ou medidas compatíveis de aceleração/retomada/frenagem
   e estabilidade, com escala e regra de agregação previamente aprovadas.
5. Qualidade histórica: amostra/versionamento de falhas e reparos para
   confiabilidade e dados verificáveis de estoque/fornecedores para peças.
   A fórmula original usa 65% confiabilidade absoluta + 35% relativa e
   65% peças absolutas + 35% disponibilidade de fornecedor. Manutenção e
   desvalorização de cenário continuam claramente estimadas; aceitar essas
   entradas em um indicador misto requer explicitar o nome/natureza, não afirmar
   que toda a qualidade é observada.

Impacto: um contrato aditivo de avaliação, validação de proveniência/unidade,
adaptador e testes de ausência/sensibilidade. Pesos iniciais e soma ponderada
podem ser preservados; qualquer alteração de semântica precisa de aprovação.
Não foi implementada uma rubrica nova nem preenchida uma nota nesta etapa.
