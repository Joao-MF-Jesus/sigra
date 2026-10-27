# Coorte acadêmica v6 — fechamento 60/60, sem publicação

`build_cohort(inventory, archive, baseline_report=...)` recebe os 67 veículos e
o relatório v5 congelados por fingerprint. O `academic_payload` fornece
identidade, proveniência por campo e avaliações baixo/base/alto. Não há acesso
ao banco, integração frontend, publicação, ativação ou ranking operacional.

## Resultado material e fronteiras

A decisão do replay é `ACADEMIC_COHORT_V6_COMPLETE`: exatamente 60/60 testáveis
(100%). O inventário tem 81 identidades: as 67 congeladas e 14 dossiês adicionados
(dez admissíveis e quatro bloqueados). A fila de
pesquisa não deve ser confundida com inventário integrado ou coorte selecionada.
Os 17 holdouts, o backlog, os IDs e os 56 resultados da etapa anterior são
preservados integralmente. Nenhuma observação, fórmula ou peso v3/v4/v5 mudou.

| ID | Identidade adicional | FIPE | Preço de referência |
|---|---|---|---|
| 96 | Honda WR-V EX 1.5 CVT 2020 | 014094-5 | outubro/2026 |
| 102 | Kia Rio LX 1.6 automático 2020 | 018095-5 | setembro/2026 |
| 104 | Caoa Chery Arrizo 5 RX 1.5 turbo CVT 2020 | 073020-3 | setembro/2026 |
| 106 | Honda WR-V EXL 1.5 CVT 2020 | 014095-3 | outubro/2026 |
| 108 | Honda Fit LX 1.5 CVT 2020 | 014081-3 | outubro/2026 |
| 109 | Honda City Sedan EX 1.5 CVT 2020 | 014061-9 | outubro/2026 |
| 122 | Honda City Sedan Personal 1.5 CVT 2020 | 014098-8 | outubro/2026 |
| 123 | Nissan Kicks SV 1.6 CVT 2020 | 023154-1 | outubro/2026 |
| 124 | Nissan Kicks SL 1.6 CVT 2020 | 023149-5 | outubro/2026 |
| 125 | Fiat Cronos Precision 1.8 automático 2020 | 001502-4 | outubro/2026 |

As dez admissões v6 são somente em Aplicativo. Cidade 10; Aplicativo 60;
Trabalho 10; Espaço/capacidade 24; Família 1; Estrada 1.
`operationally_active=0`, `recommended=0`. Segurança desconhecida não vira
`false` e não é inferida de estrelas, geração ou equipamento opcional.

## Janela FIPE exclusiva da v6

`preferred_reference_month=2026-09`, `accepted_latest_reference_month=2026-10`.
Cache exato de setembro tem preferência. Outubro só entra com código, marca,
modelo/acabamento, ano e combustível exatos. Mês ausente, fora da janela ou
identidade divergente falha fechado. `price_reference_month` está no resultado
e no TCO, incluindo as entradas dos componentes dependentes de preço; outubro
nunca é rotulado setembro. A referência técnica CarPedia é conservada separada
do mês FIPE, sem substituição do ano de fabricação/modelo ou ciclo PBEV.

A documentação FIPE v1 consultada descreve preços correntes. A documentação
v2 (`https://fipe.api.br/docs/api/fipe`) descreve `reference` e descoberta de
referências; nenhum código histórico, credencial ou parâmetro v1 foi inventado.
As quatro identidades com preços exatos de setembro reutilizaram cache; as
consultas correntes restantes registraram outubro conforme autorização v6.
O gate operacional continua comparado com setembro, e v3/v4/v5 não mudam.

IDs novos 101–129 são reservados monotonicamente, sem reutilizar IDs antigos.
Os IDs122–129 foram atribuídos após o maior ID previamente reservado121.
Somente 12 desses 29 IDs novos entraram no replay; nove entram na seleção,
além do ID96 já reservado no inventário original. Fila não é admissão.
Os IDs101/103/111 permanecem com ficha e TCO individuais comprovados, mas são
bloqueados na coorte porque repetem os códigos FIPE dos congelados45/52/14 em
outros anos. O ID116 repete exatamente o Captur Zen CVT2020 já selecionado91.
Nenhum desses quatro pode preencher vaga. A unicidade exigida da seleção é
por código FIPE, além de código+ano. Não basta ter um ID interno diferente.
O validador v6 estende o limite de ID
da estrutura de evidência v3; os validadores de unidades e proveniência são
herdados. Uma cópia estática do avaliador v4 altera somente o tipo validador e
a ligação à configuração v4. Um teste AST comprova essa paridade: nenhuma
fórmula, peso, limiar, cenário ou interpretação v4 foi alterada.

## Natureza dos componentes

Preço FIPE, consumo PBEV e campos técnicos permanecem evidências atribuídas às
fontes. O proxy `wheelbase_mm * body_width_mm / seats / 1000000`, m²/lugar, é
`derived_academic`, nunca espaço interno observado. O combustível usa consumo
PBEV e parâmetros de cenário; IPVA, manutenção, seguro e depreciação mantêm as
taxas e fórmulas versionadas. TCO completo de cenário não satisfaz TCO observado
completo, `methodology_ready` operacional, ativação ou recomendação.

Cada dossiê admissível vincula a linha PBEV individual por ciclo/página/linha/hash,
preço FIPE e ficha por SHA-256 e identificador. Acabamento, cilindrada, combustível
e transmissão são conferidos; versões agrupadas, cache adulterado, unidades
inválidas e associações por semelhança não são aceitos.

## Auditoria anterior (50 para 56), preservada

Fila prioritária:21 alvos, dos quais20 não existiam como identidade código+ano
no inventário congelado; a auditoria rejeita a duplicação exata do ID116.
A matriz versionada registra25 decisões, incluindo quatro candidatos antigos.
Dezessete possuem decisão de admissão ou rejeição definitiva em requisito
obrigatório: seis admitidos e onze rejeitados. Os oito restantes param no gate
de preço; suas fichas não foram coletadas nem
declaradas integralmente validadas. Falha em requisito obrigatório encerra o
dossiê daquele candidato, não os candidatos seguintes.

| Candidato | Bloqueio preservado |
|---|---|
| Kwid Zen 35 | documentos de comprimento 3679/3680 mm ainda divergem |
| Peugeot 3008 Allure 61 | ficha 4365/1837/2613 mm não reconcilia a geração MY2020 |
| Hyundai ix35 GL 74 | PBEV GL aro17 versus ficha 225/55 R18 |
| Arrizo 5 RX 2019, ID105 | ciclo local não tem linha RX/CVT individualizada do ano |
| Honda Fit DX 2020, ID107 | rota FIPE exata retornou404; não há preço em cache |
| Honda City DX 2020, ID110 | rota FIPE exata retornou404; não há preço em cache |
| New QQ Look 2020, ID121 | FIPE Gasolina contradiz PBEV/ficha Flex |
| IDs101/103/111 | FIPE já selecionadas45/52/14; outro ano não é nova vaga |
| ID116 | Captur Zen CVT2020 já selecionado91; nenhuma chamada repetida |
| IDs112–115 e117–120 | sem snapshot de preço exato no cache; saldo FIPE zero |

Nesta continuação: CarPedia 9/13 (nove respostas200, saldo4); FIPE 6/6
(quatro200, dois404, saldo0); documentos oficiais 2/25 (duas falhas de conexão
no mesmo manual Peugeot, incluindo um único retry, saldo23); buscas web4/30
(saldo26). Não existe indisponibilidade global demonstrada. Orçamentos não são
fungíveis: ficha ou manual não substitui preço/identidade FIPE obrigatório.
As quatro fichas restantes não resolvem preços ausentes ou conflito de
combustível; documentos genéricos não corrigem configuração exata por hipótese.

Esses bloqueios e respostas anteriores continuam preservados. A rodada final
não os investigou novamente. Família/Estrada permanecem lacunas independentes,
com uma opção cada; nenhuma pesquisa adicional de segurança foi realizada.

## Rodada final (56 para 60)

Fila local pré-rede de oito alvos PBEV individualizados: City Personal,
Kicks SV/SL, Cronos Precision/HGT, Argo Precision/HGT e HB20X Vision, MY2020.
Cada alvo foi vinculado explicitamente ao modelo FIPE do inventário em cache.
O inventário de modelos FIPE contém identificador de consulta, não o código
canônico. A resposta de preço exata confirmou o código e sua ausência entre
os 56 anteriores, antes de qualquer chamada técnica. Não houve join fuzzy.

Os quatro primeiros passaram e a coleta foi imediatamente encerrada; os quatro
restantes ficaram na fila sem consulta nem admissão. O ID121 e os IDs101/103/111
continuam bloqueados; as três variantes com código repetido não entram nos60.

| ID | TCO baixo | TCO base | TCO alto | Natureza/unidade |
|---|---|---|---|---|
| 122 | 1610,03 | 2101,01 | 2732,26 | estimativa acadêmica, R$/mês |
| 123 | 1618,39 | 2096,17 | 2710,45 | estimativa acadêmica, R$/mês |
| 124 | 1639,33 | 2126,27 | 2752,32 | estimativa acadêmica, R$/mês |
| 125 | 1503,67 | 1893,67 | 2395,09 | estimativa acadêmica, R$/mês |

Parâmetros permanecem versionados: 1000 km/mês e R$6/l, cenários baixo/base/alto
já existentes. Nenhuma taxa foi calibrada. FIPE outubro está explícita em cada
registro e entrada dependente de preço. PBEV é do ciclo2020 e a ficha preserva
separadamente sua referência técnica setembro2026.

Orçamento exclusivo final: FIPE4/10 e CarPedia4/8, todos HTTP200, zero retries,
zero falhas. Saldo FIPE6 e CarPedia4. Documentos0/23, buscas0/20. Oito inventários
de modelo FIPE e quatro linhas/documentos/parses PBEV foram reutilizados do cache,
sem chamadas de descoberta. Respostas brutas nunca integram os contratos Git.

## Validação e entrega

Replay individual/conjunto, idempotência, exclusão/reinserção lógica, unicidade
FIPE e FIPE/ano, 56 resultados anteriores, 17 holdouts e fingerprints v3/v4/v5 são
verificados offline. Testes v6 74; v5 51; v4 58; focais 616; Data Platform 961
aprovados e 17 skips condicionais (dependências de ativos/PostgreSQL não
configuradas). Skips não comprovam PostgreSQL real. Zero chamadas de rede nos
testes, zero publicação. JSON, compilação, bytes anteriores, segredos e whitespace
são auditados também nos seis arquivos ainda não rastreados.

Respostas brutas, PDFs, matriz detalhada, relatório, replay e manifesto SHA-256
permanecem fora do repositório. Nenhum checkpoint está preparado nesta etapa.
