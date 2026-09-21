# Piloto acadêmico v4 — offline, aditivo e não operacional

## Escopo e interpretação

A v4 é uma hipótese metodológica explícita para experimentos limitados do TCC,
não uma validação empírica de conforto ou segurança. Reutiliza os 19 veículos
integrados, a identidade já aprovada e o contrato central de cenário de custos.
Não altera contratos, bytes, pesos, escalas ou resultados da v3. Não seleciona
veículos novos, não publica Gold e não possui integração com a interface.

Arquivos próprios: `profile_method_v4.json`, `profile_pilot_v4.py` e
`profile_safety_v4.py`. Entrada: objetos `ProfileVehicle` v3; saída: dicionários
diagnósticos exclusivos v4. Não é um DTO público nem entrada de ativação.

`academic_test_ready` significa calculabilidade acadêmica sob hipóteses
declaradas. Não significa elegibilidade para uma plataforma de transporte,
adequação real a uma família, homologação, eficácia, recomendação ou publicação.
`methodology_ready` e `observed_tco_complete` são copiados exclusivamente da
baseline inalterada. `operationally_active` e `recommended` permanecem falsos;
o ranking operacional permanece vazio, inclusive quando a v4 é calculável.

## Auditoria dos dados disponíveis

Os 19 IDs são 36, 37, 38, 39, 42, 43, 46, 47, 49, 58, 59, 68, 69, 70, 79,
80, 91, 92 e 93. Todos possuem lugares, entre-eixos e largura da carroceria.
Nenhum possui o par de medidas internas exigido pela v3 (espaço de pernas
traseiro e largura interna). As fontes, unidades, limitações e hashes de cada
entrada são preservados, sem converter largura externa em largura interna.

Não há inventário completo de segurança admitido nem resultado Latin NCAP
com aplicabilidade exata admitido para esses 19. Focus 80 continua com ABS e ESC,
mas sem quantidade de airbags inequívoca. O documento do Cruze 46 continua
insuficiente para vincular a configuração LT alvo às restrições de produção/VIN
da ficha do teste. Não há promoção dessas evidências ambíguas.

## Aplicativo: dois caminhos segregados

1. **Medidas internas diretas**: conserva a fórmula v3, espaço de pernas
   traseiro × largura interna ÷ 1.000.000. O produto continua sendo um índice
   geométrico, não uma medida de conforto.
2. **`academic_habitability_proxy`**: usa somente campos observados disponíveis:

   `x = wheelbase_mm × body_width_mm ÷ 1.000.000 ÷ seats`

   Unidade: m² por lugar nominal. O produto usa largura da **carroceria**, nunca
   com espelhos. É um envelope externo por capacidade nominal, **não espaço
   interno medido**, área útil, ergonomia ou conforto.

Entradas devem ser positivas, observadas e aplicáveis à versão exata ou ao
escopo nominal documentado já admitido pelo piloto. Ausência não vira zero;
unidade inválida e identidade divergente não são corrigidas por aproximação.
O caminho de medidas internas tem precedência. Os dois caminhos não são
misturados em um único ranking comparável.

Não há ponderação oculta entre dimensões: produto dimensional dividido pela
capacidade. Isso favorece envelopes maiores por lugar e pode penalizar veículos
de sete lugares mesmo quando úteis ao usuário. Distribuição das fileiras,
embalagem mecânica, altura e áreas utilizáveis não estão representadas.

Para compor um diagnóstico com os demais critérios da v3, usa-se
`u = 100 × x / (x + referência)`, referência explícita de 1 m²/lugar nominal.
Esse valor é uma referência aritmética exploratória, não um limiar de conforto.
O peso de 0,25 vem do critério `passenger_space` v3, sem alterar seu contrato.
Não há corte de prontidão baseado no valor desse proxy ou em atingir dez opções.

Sensibilidade pré-declarada: referências 0,5/1/1,5 m²/lugar; multiplicação do peso
do proxy por 0,5 e 2, com renormalização; comparação com envelope externo sem
divisão por lugares (m², referência 5 m²), identificado como especificação de
sensibilidade. As variações não calibram a fórmula para uma ordem desejada.
O uso substantivo exige posteriormente comparação com medidas internas reais
ou estudo com usuários; o piloto não prova validade externa do construto.

## Família e Estrada: evidência, não proxy de segurança

**A — inventário**: exige airbags, ABS e ESC observados para a configuração
exata. Preserva o índice v3 `100 × (min(airbags,6)/6 + ABS + ESC) / 3`.
Ausência explicitamente comprovada pode ser zero/false; campo não encontrado
permanece desconhecido. O índice não representa probabilidade de lesão.

**B — teste Latin NCAP**: contrato separado de dossiê revisado, com código FIPE,
ano-código, identidade comercial e combustível; geração, carroceria,
configuração, ano-modelo explicitamente coberto; ano do teste e período do
protocolo; resultado, métrica e máximo oficiais; citações do resultado,
aplicabilidade e protocolo, com URL pública, localizador, coleta e SHA-256.
Os três arquivos devem existir no cache autorizado e ter hashes verificados.
Restrições de VIN/data/versão não resolvidas, duplicidade e documentos adulterados
rejeitam o caminho. Não há busca ou inferência textual automática.

A revisão documental humana precisa demonstrar o vínculo entre a identidade
canônica e a configuração testada. Um hash correto ou hostname oficial sozinho
não demonstra essa equivalência. O contrato vazio de registros admitidos é
deliberado: somente fixtures sintéticas de teste exercitam o caminho B nesta
rodada. Elas não são evidências dos veículos reais.

O resultado fica como `latin_ncap_configuration_test`; jamais preenche airbags,
ABS ou ESC. A projeção diagnóstica `100 × resultado / máximo` só é comparável
dentro do mesmo protocolo, período, métrica, escala e hash do documento de
protocolo. Não equivale ao índice de equipamentos. Caminhos A/B e protocolos
distintos permanecem em grupos separados; não há ranking agregado entre eles.

## Cobertura, confiança, cenário e ordenação

Cada linha contém inventário original dos campos, critérios e sua natureza:
`observed`, `derived_academic`, `scenario_estimate` ou `unavailable`; cobertura
ponderada e por natureza; entradas, fórmulas, versões, citações e bloqueios.
Confiança numérica é `null`: rastreabilidade/cobertura não são confiança
estatística. O proxy pode ter cobertura completa de entradas e ainda assim
continuar sendo uma hipótese fraca sobre habitabilidade.

Combustível e TCO reutilizam, sem mudança, os cenários baixo/base/alto existentes
(1.000 km/mês, R$ 6/l). Custos de cenário não satisfazem TCO observado nem
ativação operacional. Cidade/Trabalho continuam exigindo largura com espelhos;
o proxy de Aplicativo não supre essa lacuna.

Os critérios obrigatórios, regras eliminatórias, identidade, revisão humana e
completude de TCO de cenário continuam obrigatórios. Somente o caminho acadêmico
de evidência difere. Rankings diagnósticos incluem apenas linhas academicamente
prontas e são separados por perfil, caminho/protocolo e máscara de critérios
de peso positivo disponíveis. ID desempata somente a exibição; empates de nota
são explícitos e todos os empates no limite do top 10 entram no Jaccard.
Kendall tau-b usa IDs comuns e empates de nota; comparação indisponível é `null`,
não zero. Rankings incompatíveis não são comparados como uma única população.

## Replay material desta rodada

| Perfil | Camada acadêmica anterior | v4 |
|---|---:|---:|
| Cidade | 10 | 10 |
| Aplicativo | 0 | 19 |
| Trabalho | 10 | 10 |
| Família | 0 | 0 |
| Estrada | 0 | 0 |
| Espaço/capacidade | 10 | 10 |

São 19 veículos distintos academicamente testáveis na v4, contra 14 antes,
sem qualquer ativação ou recomendação operacional. A v3 continua com zero
`methodology_ready` em Trabalho: as dez opções de Trabalho vêm do caminho de
TCO de cenário já existente, não de TCO observado ou mudança na v3.

Aplicativo alcança dez apenas no sentido limitado do piloto proxy. Família e
Estrada continuam sem dez resultados: precisam de dez inventários exatos ou
dossiês Latin NCAP realmente compatíveis. Dez resultados espalhados por protocolos
incompatíveis também não dariam automaticamente dez opções comparáveis.

A meta permanece 60 automóveis totais: 34 legados preservados + 26 novos.
Esta rodada não adiciona veículos: são 19 novos existentes, faltam sete para
a quantidade-alvo, além dos gates necessários à publicação acadêmica futura.
Nenhuma prontidão aqui comprova essa publicação.

Na sensibilidade material de Aplicativo, alterar a referência para 0,5/1/1,5
preservou a ordem (Jaccard e Kendall = 1). Alterar o peso e retirar a divisão por
lugares resultou em Jaccard do top 10 entre 0,8182 e 1 e Kendall tau-b entre
0,9064 e 1: a escolha do proxy/peso influencia a ordem e deve ser relatada.
Não houve mudança da quantidade calculável nessas variações.

Trabalho tem dez linhas prontas, mas duas máscaras de evidência (nove com carga
útil e uma sem esse campo, admitida pelo `required_any` já existente). A v4
mantém esses grupos separados, não anuncia dez notas diretamente equivalentes.
No grupo de nove, mudar TCO base para baixo/alto produz Kendall de 0,8333/0,5556.
O grupo unitário não permite Kendall. Cidade e Espaço/capacidade preservam
Jaccard/Kendall = 1 frente à v3 nos conjuntos comparáveis. Sem ranking v3
Aplicativo admissível, não existe Kendall v3/v4 para esse perfil.

## Verificação e limites

Testes v4 cobrem separação de natureza, identidade, unidades, ausências, zero,
escopo, adulteração, duplicidade, protocolos, empates, Decimal, idempotência,
invariância v3 e perfis não afetados. O replay externo compara SHA-256 de todos
os arquivos previamente rastreados e fingerprints de v3, veículos e cenário v1
antes/depois; caches e documentos brutos permanecem externos. Compilação e
artefatos de teste também ficam externos.

Defensável como experimento offline de **sensibilidade metodológica**, com
limitações explícitas; não como evidência de habitabilidade real, segurança de
versões não comprovadas, aprovação visual, eficácia de recomendação ou liberação
dos seis perfis. Não há autorização de checkpoint, publicação ou ativação.
