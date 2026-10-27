# Alternativa acadêmica aditiva dos sete pesos — v1

Versão: `academic-derived-seven-v1`. Desabilitada por padrão. Não é uma
aprovação acadêmica, não substitui a referência `user-profile-multifactor-v1`
e não altera V6, Revision6, catálogo, custos, taxas ou elegibilidade.

## Seleção e separação

O contrato central é `backend/app/academic_cohort/derived_personalization_v1.json`.
Em processo **isolado de validação**, habilitar
`SIGRA_DERIVED_PERSONALIZATION_ENABLED=true`. A requisição deve selecionar
explicitamente `multifactor_profile.policy_version=academic-derived-seven-v1`
e `candidate_source=academic_v6`. Sem ambos, não há execução da alternativa.
A API rejeita a seleção quando desabilitada ou com origem operacional.
Metadados anunciam a disponibilidade; o formulário oferece a seleção somente
quando anunciada e mantém o método original selecionado inicialmente.
Na resposta alternativa, algorithm_version e weights_version identificam
academic-derived-seven-v1; baseline_algorithm preserva academic-v4-live-v1.
Assim o registro existente de execuções não rotula a alternativa como v4.

Os sete nomes de transporte dos pesos são preservados por compatibilidade,
mas a interface apresenta os **nomes efetivos** abaixo. Os pesos históricos
25/20/10/15/10/10/10 são referência, não validação empírica dessa nova rubrica.
Nenhuma exclusão ou taxa é aplicada automaticamente. Peso zero é exclusão
explícita, registrada na API, revisão do formulário, resultados e detalhes.

## Métricas e cobertura auditada

Cobertura: mesmos 60 payloads verificados da Revision6 inativa, sem banco.
Fontes, localizadores, unidades, aplicabilidade, limitações e hashes são
mantidos nas entradas do cálculo; fontes não se tornam notas observadas.

| Peso/chave | Significado original | Significado efetivo v1 | Entrada/fórmula | Cobertura na origem |
|---|---|---|---|---:|
| Combustível / total_cost | Combustível no horizonte | Combustível estimado no cenário | km × (fração urbana/consumo urbano + fração rodoviária/consumo rodoviário) × preço/l × meses | 60/60 com cenário gasolina e preço explícito |
| Adequação / usage_fit | Avaliação original do uso | Compatibilidade documental | 100 após os gates publicado e recalculado do perfil; sem distinção entre igualmente compatíveis | 60 em Aplicativo; 10 Cidade; 10 Trabalho; 24 Espaço; 9 Família; 9 Estrada |
| Conforto / comfort | Avaliação de conforto | Capacidade do porta-malas | cargo_l observado e aplicável, em litros | 60/60 |
| Segurança / safety | Nota original de segurança | Inventário de equipamentos | 100 × (min(airbags,6)/6 + ABS + ESC)/3 | 9/60 completos |
| Desempenho / performance | Avaliação rodoviária | Massa/potência com gasolina | massa kg / potência cv; ambas da versão exata | 8/60 após lote complementar; anteriormente somente Sentra 55 |
| Eficiência / efficiency | Consumo combinado | Consumo combinado no cenário | 1 / (fração urbana/consumo urbano + fração rodoviária/consumo rodoviário) | 60/60 com combustível compatível |
| Qualidade / legacy_quality | Média de manutenção, confiabilidade, peças e revenda | Manutenção e desvalorização estimadas | (manutenção anual de cenário + depreciação anual de cenário)/12 | 60/60 como estimativa, zero observações históricas inventadas |

### Normalização e escolhas metodológicas

- Combustível e despesas estimadas: min/max inverso no grupo de comparação
  vigente, entre entradas válidas e financeiramente elegíveis. Eficiência:
  min/max crescente nesse mesmo escopo. A população e limites são expostos
  por dimensão. Ausência de outra dimensão não remove uma entrada válida
  desses limites. Não se misturam grupos documentais incompatíveis.
- Porta-malas: utilidade absoluta crescente, clamp entre 150 e 600 l,
  reutilizando as âncoras v3. Não são limites físicos universais.
- Massa/potência: utilidade absoluta decrescente, clamp entre 5 e 25 kg/cv,
  reutilizando as âncoras v3. Só com massa e potência da versão exata,
  combustível gasolina compatível; potência de outro combustível ou apenas
  shared_powertrain não substitui a evidência exigida.
- Segurança: índice v3, limitado a seis airbags, três parcelas com igual
  participação. São escolhas metodológicas declaradas, não eficácia em
  colisão. `false` e zero comprovados são válidos; `null` não é ausência.
  O Fiesta 44 mantém ESC explicitamente ausente e índice inferior.
- Compatibilidade: condição de entrada. Todos os veículos admitidos recebem
  100, sem fabricar diferenciação. O peso ocupa parte da soma, mas não
  distingue veículos; isso é informado explicitamente.
- Despesas: soma monetária das entradas anuais **não arredondadas** do
  contrato academic_cost_scenario_v1, seguida de divisão por 12. Não usa
  notas de peças ou confiabilidade, nem recalibra taxas para obter posições.
- Min/max igual: 100 para todos, sem discriminação, como na referência.
  Escalas absolutas: mesma entrada gera mesma utilidade. Desempate por
  posição de referência e ID acadêmico; nunca uma diferença fictícia.
- Decimal, ROUND_HALF_UP, notas e contribuições com quatro casas. Peso
  normalizado = peso enviado/soma de **todos** os pesos enviados. Nota final
  = soma das contribuições somente com todas as dimensões positivas válidas.
  Desconhecido positivo: nota final null e posição relativa de referência
  preservada entre os não pontuados. Não há soma parcial, imputação ou
  redistribuição por ausência. Peso zero mantém raw_score null se faltar
  evidência e contribuição aritmética zero, não uma nota inventada.

### Dependências e limites

Combustível e eficiência compartilham os mesmos consumos e frações do trajeto:
não são evidências independentes. Com preço e distância comuns, tendem à
mesma preferência. Manutenção/depreciação de cenário podem acompanhar o preço
FIPE: menor preço não demonstra confiabilidade. Porta-malas não mede conforto;
massa/potência não mede comportamento rodoviário; inventário não mede colisão.
Não há percentual de confiança estatística calibrado. Cobertura e rastreabilidade
são apresentados separadamente. As limitações dos documentos permanecem.

## Notas finais possíveis, sem filtros financeiros restritivos

Resultado histórico da entrega anterior ao lote complementar (preservado para
comparação), idêntico em baixo/base/alto para estas três configurações:

| Configuração explícita | Cidade | Aplicativo | Trabalho | Espaço | Família | Estrada |
|---|---:|---:|---:|---:|---:|---:|
| Todos os pesos históricos positivos | 0 | 1 | 0 | 1 | 1 | 1 |
| performance=0, demais pesos históricos | 0 | 9 | 0 | 3 | 9 | 9 |
| performance=0 e safety=0, demais históricos | 10 | 60 | 10 | 24 | 9 | 9 |

Zero em segurança na personalização **não** remove o gate documental de Família
ou Estrada. Os nove inventários aceitos permanecem 31,34,44,55,62,76,80,108,124.
Tiguan 70 permanece desconhecido/bloqueado; Cruze mantém 1.807 mm de carroceria
e 2.042 mm com espelhos. Não se combina o experimento de altura livre.

Caso Cidade, R$70.000 de compra, R$1.800/mês, 1.000 km/mês, gasolina R$6/l,
50/50 urbano/rodoviário, Base, com performance=safety=0 explicitamente:
60 na origem, 10 documentalmente elegíveis, quatro financeiramente elegíveis
e quatro pontuados. Com todos os pesos positivos, essas lacunas continuam
impedindo a personalização desses quatro.

## Evidência ainda necessária

- Na entrega anterior, massa da versão exata ausente em 59 e potência com gasolina ausente em 57,
  e nos IDs 36/37 o vínculo existente é shared_powertrain, não exact_variant.
  É necessária ficha da configuração exata que comprove ambas em kg e cv.
  O lote complementar abaixo resolve sete pares adicionais, sem substituir
  o Sentra; a massa do Focus SE Plus 2018 continua pendente.
- Inventário completo de airbags/ABS/ESC: 51 incompletos. Só evidência da
  versão/ano/mercado, inclusive ausência explícita, pode completar; conflito
  não é decidido arbitrariamente. A busca documental permanece encerrada.
- Para o **método original**, continuam ausentes avaliações originais de uso,
  conforto, segurança, comportamento rodoviário, confiabilidade e peças.
  Esta alternativa não fabrica essas avaliações nem promete substituí-las.
- ANP e consumos de outros combustíveis não são inventados. Sem preço e
  consumo compatíveis, combustível/eficiência ficam indisponíveis.

## Reprodução isolada

Sem PostgreSQL, SQLite, lifespan/bootstrap ou rede externa, executar os testes
`backend/tests/test_academic_derived_personalization.py` e regressões de
personalização, recomendação, sete critérios e subcálculos originais. O teste
HTTP substitui a dependência de banco por fixture fictícia exclusivamente nos
testes. No Windows, TestClient usa socketpair interno do event loop; isso não
é chamada de API externa. Fixtures nunca entram no catálogo/runtime.

No frontend: `npm test` e `npm run build`. A interface recebe notas,
contribuições e nomes do método efetivamente selecionado; nenhuma conta
financeira é replicada no navegador.

O acompanhamento offline com os dados reais aprovados é entregue fora do
repositório, com respostas, matriz, exemplo de alteração dos pesos e comandos
de reprodução. Homologação PostgreSQL, ativação de Revision6, coleta real,
Supabase e deploy não foram executados nesta etapa.

## Lote complementar de massa/potência v1

Contrato independente: `backend/app/academic_cohort/derived_mass_power_v1.json`,
versão `academic-derived-mass-power-evidence-v1`. O resolvedor próprio
`derived_mass_power.py` confere o hash do contrato, os nove IDs autorizados,
FIPE, ano, identidade comercial, combustível, transmissão e a revisão de
aplicabilidade. Não existe vínculo por semelhança textual.

Somente `derived_personalization.measurements` usa uma cópia com esses dois
campos complementares. A avaliação v4, a seleção documental, o TCO, o DTO
técnico original do veículo e os replays aprovados **não** recebem o overlay.
As entradas do critério na resposta da API incluem citações, definição,
representação, hash original quando disponível, hash da captura e decisão.
A interface mostra definição, combustível e limitações na seção recolhida de
dados, sem expor hashes na apresentação principal.

| ID | Versão/ano brasileiro | Massa kg | Potência gasolina cv | kg/cv | Decisão |
|---|---|---:|---:|---:|---|
| 31 | Kicks S CVT 2020 | 1129 | 114 | 9,9035 | Par admissível |
| 34 | EcoSport SE 1.5 automático 2018 | 1255 | 130 | 9,6538 | Par admissível |
| 44 | Fiesta SE 1.6 manual 2018 | 1127 | 125 | 9,0160 | Par admissível; ESC ausente preservado |
| 55 | Sentra SV 2.0 CVT 2020 | 1337 | 140 | 9,5500 | Observações e citações anteriores preservadas |
| 62 | Golf Comfortline 200 TSI automático 2018 | 1259 | 116 | 10,8534 | Par admissível |
| 76 | 5008 Griffe THP automático 2019 | 1632 | 165 | 9,8909 | Par admissível |
| 80 | Focus Fastback SE Plus 2.0 automático 2018 | desconhecida | 175 | indisponível | Potência admissível, massa bloqueada |
| 108 | Fit LX CVT 2020 | 1082 | 115 | 9,4087 | Par admissível |
| 124 | Kicks SL CVT 2020 | 1136 | 114 | 9,9649 | Par admissível |

### Fontes e aplicabilidade

- Nissan Kicks MY2020: catálogo oficial, p.13, colunas S CVT e SL CVT;
  114 cv é explícito para gasolina e etanol. PDF original preservado.
- Ford EcoSport MY2018: ficha oficial, p.2, coluna SE AT 1.5; não se usa
  massa SE manual, Freestyle ou Titanium. Potência 130 cv gasolina,
  não 137 cv etanol.
- Ford Fiesta MY18: ficha oficial, p.2, SE 1.6 manual; 125 cv gasolina,
  não 128 cv etanol, nem massa SE Plus automático.
- Nissan Sentra MY2020: catálogo oficial, p.11, coluna SV. Esta verificação
  não recria nem altera as observações já admitidas.
- Volkswagen Golf: ficha oficial Comfortline automático, p.1, impressa em
  junho/2018; vínculo MY2018 200 TSI também documentado no release oficial
  preservado na Revision6. 116 cv é a coluna gasolina; 128 cv é etanol.
- Peugeot 5008: imagem original da ficha técnica Stellantis, cabeçalho
  ANO MODELO 18/19, coluna Griffe THP. A célula comum Griffe/Griffe Pack
  declara a massa e potência; não se transfere equipamento do Pack.
- Ford Focus Fastback MY18: ficha oficial, p.2, motor 2.0 Direct Flex,
  seis marchas, coluna SE Plus; 175 cv gasolina, não 178 cv etanol.
  Não há massa nessa ficha.
- Honda Fit2020: folheto oficial, p.3, LX; massa da linha manual/CVT
  seleciona CVT; 115 cv gasolina, não 116 cv etanol.

URLs, páginas, identidades, valores, transformações, hashes e data de consulta
estão no contrato. PDFs Nissan/Volkswagen e a imagem original Peugeot foram
preservados fora do Git. O acesso direto aos PDFs Ford/Honda retornou HTTP403:
foram preservadas capturas normalizadas da leitura integral das tabelas pelo
leitor público documental, com colunas e contexto de aplicação. Não são
trechos de resultado de busca. Não há imagem original dessas páginas retida;
o hash da captura **não** é apresentado como hash do PDF original.

### Definição e comparabilidade

A rubrica usa massa nominal publicada em ordem de marcha, dentro da família
de definições de massa do veículo pronto para uso sem carga útil. Não aceita
PBT, massa de ensaio, carga útil ou peso seco. A ficha Peugeot usa a expressão
“peso vazio em ordem de marcha”; ela não é reinterpretada como PBT.
As condições de abastecimento/condutor não são harmonizadas nem inferidas:
o índice é carga de potência nominal entre fichas, não resultado de um mesmo
protocolo de medição. Essa limitação acompanha cada entrada e não autoriza
ajuste de massa nem alegação de aceleração ou desempenho rodoviário.

Todos os valores foram usados diretamente em kg e cv. No Golf, utiliza-se
o valor **116 cv publicado**, sem recalcular os 85 kW arredondados.
Se futuramente houver conversão, deverá haver nova evidência versionada:
1 cv métrico = 0,73549875 kW; cv não é hp SAE e torque não é potência.
Nenhuma conversão, taxa, âncora de utilidade ou peso mudou neste lote.

O manual Focus cujo nome contém 2018 tem edição impressa 2016 e colunas
SE/SEL/Titanium, sem SE Plus. Não comprova a massa da identidade-alvo.
É necessária ficha oficial MY2018 brasileira que individualize SE Plus
2.0 automático e sua massa em ordem de marcha. Sem ela, peso positivo
em massa/potência mantém a nota final desconhecida, sem redistribuição.

### Replay antes/depois com todos os sete pesos positivos

Mesmos 60 veículos, 1.000 km/mês, gasolina R$6/l, percurso 50% urbano e 50%
rodoviário, sem filtros financeiros restritivos. Pesos explicitamente enviados:
combustível 25%, adequação 20%, porta-malas 10%, equipamentos 15%,
massa/potência 10%, eficiência 10%, despesas estimadas 10%.
Contagens iguais em baixo/base/alto:

| Perfil | Elegíveis documentais, inalterados | Pontuados antes | Pontuados após lote |
|---|---:|---:|---:|
| Cidade | 10 | 0 | 0 |
| Aplicativo | 60 | 1 | 8 |
| Trabalho | 10 | 0 | 0 |
| Espaço/capacidade | 24 | 1 | 3 |
| Família | 9 | 1 | 8 |
| Estrada | 9 | 1 | 8 |

Nos nove inventários de segurança, oito obtêm os sete critérios; Focus 80
permanece com diagnóstico 6/7 e nota final null. Não foram removidos
requisitos dos outros perfis nem ampliada a busca aos veículos restantes.
Cidade e Trabalho continuam com ausências positivas de inventário e/ou
massa/potência; isso não é exclusão financeira.

Exemplo real em Família/Base: com os pesos de referência, Fit 108 recebe
83,7873 pontos e posição local 1; Kicks SL 124, 79,2334 e posição 3;
Sentra 55, 60,7546 e posição 7. Uma escolha explícita de pesos
5/10/30/15/30/5/5 (todos positivos, soma 100) produz respectivamente
71,6319/posição 4, 75,9241/posição 1 e 73,4386/posição 2.
Sete posições mudam, sem alteração de evidência, custo ou elegibilidade.
Não se trata de uma ordem universal nem de veículos igualmente seguros.
As nove entradas do grupo, inclusive o Focus com dimensão ausente,
continuam participando dos intervalos dos critérios que possuem dados.

Para Kicks S 31, as sete contribuições com os pesos de referência são:
18,8434 + 20,0000 + 6,2667 + 11,6667 + 7,5483 + 7,1207 + 5,3403
= 76,7861. A demonstração auditável fora do repositório contém valores,
utilidades, pesos, intervalos e contribuições de todos os veículos do exemplo.
Os fingerprints V6 e Revision6, as 1.080 avaliações de cada replay,
o método original e todos os custos e gates nos três cenários permanecem
iguais. A idempotência exclui somente generated_at, metadado da execução.

Testes adicionais em `backend/tests/test_academic_derived_mass_power.py`
cobrem definição/unidade, combustível, FIPE/ano/versão/transmissão,
conflitos, desconhecidos, adulteração, preservação de observação prévia,
cópia idempotente, direção de kg/cv e resposta HTTP com efeito de pesos.
Não houve homologação PostgreSQL, Supabase, coleta real nem ativação.

## Configurações explícitas por perfil — v1

O registro `backend/app/academic_cohort/derived_configurations_v1.json`
adiciona dois presets ao método `academic-derived-seven-v1`. Não muda suas
métricas, âncoras, fórmulas, custos, evidências ou gates. O método original
`user-profile-multifactor-v1` permanece como referência. A alternativa
continua desabilitada por padrão (`SIGRA_DERIVED_PERSONALIZATION_ENABLED`),
independentemente da disponibilidade de dados.

- `academic-derived-base-five-v1`: Base — cinco dimensões. Proposta para
  Cidade, Aplicativo, Trabalho e Espaço/capacidade; opção explícita em
  Família/Estrada.
- `academic-derived-expanded-seven-v1`: Ampliada — sete dimensões.
  Proposta para Família/Estrada; opção explícita nos demais perfis.

Vetor fixo na ordem combustível, compatibilidade documental, porta-malas,
equipamentos de segurança, massa/potência, eficiência e despesas estimadas:

| Dimensão efetivamente medida | Base (%) | Ampliada (%) |
|---|---:|---:|
| Custo de combustível estimado | 33,3333 | 25 |
| Compatibilidade documental com o uso | 26,6667 | 20 |
| Capacidade do porta-malas | 13,3333 | 10 |
| Equipamentos de segurança documentados | 0 | 15 |
| Relação massa/potência | 0 | 10 |
| Eficiência de consumo | 13,3333 | 10 |
| Manutenção e desvalorização estimadas | 13,3334 | 10 |
| Total | 100 | 100 |

Os pesos são uma escolha metodológica do projeto, não inferida das lacunas
de cada veículo. Os cinco pesos ativos da referência somam 75. A Base usa
`peso_referência × 100 / 75`, arredondamento Decimal half-up em quatro
casas e resíduo de 0,0001 ponto percentual na última dimensão ativa.
Os zeros de equipamentos e massa/potência são explícitos e uniformes.
Não constituem evidência, nota zero para dado desconhecido nem dispensa de
inventário obrigatório em Família/Estrada. Porta-malas não mede conforto;
equipamentos não são resultados de colisão; kg/cv não é avaliação
rodoviária; despesas estimadas não comprovam confiabilidade histórica.
Combustível e eficiência compartilham consumo, conforme limitação anterior.

### Seleção, ajustes e contrato HTTP

A interface exige uma escolha explícita, mostra as dimensões, os pesos
efetivos normalizados e o aviso de não comparabilidade. Trocar o perfil
não muda o preset nem os pesos. Selecionar outro preset aplica seu vetor
por ação do usuário; o botão de restauração recupera esse preset.
Edições explícitas continuam permitidas pelo contrato existente.

O seletor reutiliza a grade de campos existente, com label associado ao
controle e wrapper normal. A inspeção Chromium detectou que usar um label
com `container-type: inline-size` nesse novo campo fazia o controle
colapsar após a seleção. A regressão verifica sua visibilidade e pelo
menos 44 × 44 px, além do valor enviado; não usa espera arbitrária.

Em `multifactor_profile`, envie `policy_version=academic-derived-seven-v1`
e `configuration_id` com um dos dois identificadores. Omitir `weights`
aplica o preset selecionado; ao ajustar, envie todos os sete pesos,
incluindo zeros. Vetores parciais, IDs desconhecidos, pesos negativos,
não finitos ou acima de 100 são rejeitados. A normalização existente
continua determinística, sem redistribuição por falta de evidência.
Requisições antigas sem configuração mantêm os pesos explicitamente
enviados e registram ausência de preset, sem escolha automática.

Se qualquer dimensão com peso positivo ficar desconhecida, a nota final
continua `null`, com motivo e preservação da ordem de referência. O Focus
80 permanece sem massa comprovada: indisponível na Ampliada e também na
Base quando o usuário explicitamente lhe atribui peso positivo em
massa/potência. A Base padrão pode pontuá-lo pelas outras cinco dimensões,
sem preencher sua massa nem alterar sua identidade.

### Matriz calculada, não imposta

Replay isolado dos mesmos 60 veículos da Revision6 inativa; 1.000 km/mês,
gasolina R$6/l, percurso 50% urbano/50% rodoviário, sem filtros financeiros
restritivos. Os resultados abaixo foram calculados em **cada** cenário
baixo, base e alto (36 combinações perfil/cenário/configuração).

| Perfil | Elegíveis documentais | Base pontuados | Ampliada pontuados | Ampliada na referência |
|---|---:|---:|---:|---:|
| Cidade | 10 | 10 | 0 | 10 |
| Aplicativo | 60 | 60 | 8 | 52 |
| Trabalho | 10 | 10 | 0 | 10 |
| Espaço/capacidade | 24 | 24 | 3 | 21 |
| Família | 9 | 9 | 8 | 1 |
| Estrada | 9 | 9 | 8 | 1 |

Não há divergência com as referências esperadas. Família/Estrada mantêm
nove inventários documentais; oito têm massa/potência suficiente para
sete dimensões. Cidade/Trabalho sem pontuação Ampliada não são exclusões
financeiras nem desaparecem: as ausências positivas são diagnosticadas.
Todos os veículos continuam inativos operacionalmente e não recomendados
operacionalmente; o bloco documental do Tiguan e o ESC ausente do Fiesta
não foram alterados.

Exemplos reproduzíveis em Família/Base: trocar explicitamente os pesos
de combustível e porta-malas no preset Base muda quatro posições. Na
Ampliada, usar `5/10/30/15/30/5/5` muda sete posições. Custos e evidências
permanecem idênticos nos dois casos. Os exemplos completos incluem
valores, utilidades, pesos, contribuições, posições e motivos de ausência;
as notas de vetores ou configurações distintos **não** são diretamente
comparáveis como se utilizassem o mesmo método.

### Proveniência, instrumento, histórico e exportação

Os resultados registram versão do método/registro, configuração escolhida,
pesos do preset, pesos enviados e normalizados, ajustes explícitos,
fingerprint do contrato/vetor e versão/hash do lote massa/potência.
Perfil, cenário, evidências, resultados e exclusões permanecem nos JSON
existentes da execução. Não há nova migration ou tabela nesta camada.

O histórico apresenta o resultado gravado, sem recalcular com pesos
atuais. O registro técnico do instrumento agrega configuração e cenário;
as perguntas e o cenário de pesquisa existente não são remapeados.
O CSV administrativo acrescenta configuração, método, pesos efetivos,
pesos normalizados, indicação de ajuste, lote, perfil e cenário, usando
código pseudônimo e sem colunas de nome/e-mail. Não se definiu mapeamento
A–E nem decisão pendente de consentimento/retenção.

O detalhamento distingue o peso informado do peso efetivo normalizado;
o primeiro não é uma porcentagem enquanto o vetor não somar 100. A falta
de entradas das métricas derivadas não significa falta de notas observadas
nem transforma essas métricas nas avaliações originais ausentes.

Nas novas execuções, o índice técnico `ranking-basis-v1` identifica a base
da nota apresentada, a nota personalizada (ou `null`) e a nota de referência
separadamente. Os fatores principais explicam a classificação realmente
utilizada: contribuições diagnósticas parciais nunca são motivos da ordem
de referência. Os subcálculos completos continuam na resposta original
gravada e no CSV. Registros anteriores não são reescritos ou recalculados.

### Limites da validação e homologação seguinte

Testes de backend/HTTP/histórico/questionário/exportação usam doubles;
o replay usa as evidências reais já aprovadas, sem banco. A navegação
isolada exercita componentes produtivos em 360 e 1440 px com transporte
das respostas offline verificadas, não uma API PostgreSQL. Não prova
persistência, reinício da API, privilégios/RLS ou homologação remota.

Antes de homologar em PostgreSQL dedicado: confirmar identidade do
destino, TLS e roles conforme o guia Revision6 existente; executar as
migrations e materialização somente na etapa autorizada; habilitar a
alternativa exclusivamente no ambiente fictício; validar os dois presets
no motor real, registro e exportação após reinício e isolamento entre
participantes. Depois revisar HTTPS, cookies, CORS, administrador,
protocolo e consentimento antes de qualquer publicação/coleta real.
Nada disso foi executado ou aprovado nesta rodada offline.
