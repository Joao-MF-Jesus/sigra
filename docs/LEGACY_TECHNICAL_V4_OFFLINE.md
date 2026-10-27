# Evidência técnica dos legados — piloto v4 offline

Decisão: `LEGACY_TECHNICAL_EVIDENCE_PARTIAL`. Não é publicação nem homologação.

## Escopo e fronteira

O adaptador opt-in `data_platform/catalog/legacy_technical_v4.py` recebe os 34
registros do adaptador legado v4 e um `SourceArchive` local explícito. Enriquece
somente os 18 IDs previamente reconciliados: 2, 3, 4, 5, 8, 9, 10, 14, 15, 16,
20, 22, 29, 30, 31, 32, 33 e 34. Os demais 16 permanecem exatamente iguais.
Nenhum consumidor operacional chama esse adaptador. Não há rede, banco,
publicação, ativação ou nova metodologia nele.

`legacy_technical_v4_evidence_v1.json` fixa separadamente descoberta, ficha,
identidade de catálogo/FIPE, ano, configuração, procedência, timestamp e SHA-256.
Não contém respostas brutas nem credenciais. O replay requer os arquivos externos
com os hashes registrados; cache ausente, adulterado ou identidade divergente
interrompe o processamento antes de retornar veículos.

## Admissão conservadora

- Descoberta: exatamente uma linha para o ID externo documentado, nome comercial
  FIPE exato, ano listado e combustível Flex. Normaliza somente caixa e espaços,
  nunca aproxima texto nem remove palavras de acabamento.
- Ficha: ID, marca, modelo, versão, ano e identificação da fonte devem coincidir
  com o manifesto; motorização nominal deve concordar com a revisão FIPE/PBEV.
- Combustível e transmissão devem concordar com PBEV; seus valores oficiais nunca
  são substituídos. O booleano CarPedia `manual` não é usado.
- Reutiliza `carpedia-spec-normalizer-v2` e a regra já versionada para o rótulo
  inequívoco `Vão livre do solo (mm)`. Unidades inválidas, campos ausentes e
  duplicatas conflitantes permanecem indisponíveis, com motivo individual.
- Largura é corporal, não largura com retrovisores. A derivação de área corporal
  usa a fórmula já existente; não há acréscimo arbitrário para espelhos.
- Potência é preservada como especificação geral, com valor/unidade de origem e
  normalização existente para kW. Sem base explícita do combustível, não preenche
  `power_gasoline_cv`. Portas, cilindrada e tanque ficam na proveniência técnica,
  sem ampliar ou alterar os campos do contrato v3.
- Não há admissão de airbags, ABS, ESC ou resultados NCAP nesta rodada. Ausência
  permanece desconhecida, nunca `false`.
- O TCO permanece cenário acadêmico, não observação. O perfil Aplicativo usa o
  `academic_habitability_proxy` já existente, não espaço/conforto interno medido.

## Dois bloqueios preservados

| ID | Evidência | Decisão |
| --- | --- | --- |
| 9 — Corolla GLi | CarPedia diz “Automático”; PBEV especifica CVT | `CARPEDIA_TRANSMISSION_NOT_EXACT`; não converter categoria genérica em CVT nem promover tecnicamente |
| 33 — Ka SE | Ficha agrupa `SE/SE Plus` | `CARPEDIA_SE_SE_PLUS_SCOPE_NOT_INDIVIDUALIZED`; não atribuir especificação agregada ao acabamento SE |

A identidade FIPE/PBEV previamente aprovada desses dois não é apagada. As fichas
são auditáveis como observações da fonte, mas não alimentam seus critérios de
perfil. O Ka recebe somente a atualização FIPE comprovada de setembro/2026:
`003408-8`, `2019-5`, R$ 44.003,00. O cache histórico de julho e a v3 não mudam.

## Resultado material do replay

| Perfil | 19 novos, antes | Legados prontos, depois | União distinta no perfil |
| --- | ---: | ---: | ---: |
| Cidade | 10 | 0 | 10 |
| Aplicativo | 19 | 16 | 35 |
| Trabalho | 10 | 0 | 10 |
| Família | 0 | 0 | 0 |
| Estrada | 0 | 0 | 0 |
| Espaço/capacidade | 10 | 12 | 22 |

Legados testáveis: **2, 3, 4, 5, 8, 10, 14, 15, 16, 20, 22, 29, 30, 31, 32, 34**.
Espaço/capacidade: **2, 3, 4, 5, 8, 10, 16, 20, 22, 31, 32, 34**; esse perfil não
é uma classificação de carroceria SUV. Cidade/Trabalho continuam limitados pela
evidência exigida de largura operacional; largura corporal não a satisfaz.

A união passou de **19 para 35/60**, não para 53 ou 60. Faltam **25 veículos
testáveis**: 18 legados ainda sem prontidão e os sete novos ainda não selecionados.
Não houve seleção de novos candidatos. Família/Estrada ainda precisam de dez
configurações com evidência de segurança admissível; nenhuma proxy foi criada.

Nos três cenários, 37 veículos reconciliados (18 legados + 19 novos) possuem TCO
de cenário completo, zero TCO observado completo, zero ativações e zero
recomendações operacionais. Cadastro, TCO de cenário e cobertura parcial não
contam isoladamente como prontidão. Rankings gerados pelo replay são diagnósticos
acadêmicos externos e não são publicados na interface.

## Coleta limitada e reprodução

Em 22/09/2026, foram verificados 28 recibos/caches anteriores e 19 cópias usadas
pelo normalizador. Nenhuma atendia a estas 18 identidades: **zero cache hits**.
Foram consumidas **36/36 tentativas CarPedia** (18 descobertas + 18 fichas) e
**1/1 FIPE**, apenas para o Ka 33. Todas retornaram HTTP 200; zero retries.
HTTP 200 não implica admissibilidade: dois veículos continuaram bloqueados.
O saldo local é zero para ambas as fontes; não é saldo de conta do provedor.

Reprodução offline: carregar `legacy_matrix_v4(archive)`, chamar
`augment_legacy_technical_v4(vehicles, archive)` e então `replay_legacy_v4`.
Para o replay conjunto, usar somente os 18 legados reconciliados mais os 19 novos,
todos com referência setembro/2026. O relatório externo contém as três rodadas
de cenário, matriz individual, bloqueios, sensibilidade, proveniência e hashes.
O segundo replay deve produzir os mesmos bytes lógicos/fingerprints.

Testes sintéticos são apenas regressões do adaptador. A evidência de admissão real
vem exclusivamente das respostas externas com os hashes do manifesto e do replay
material, nunca dos exemplos de teste.
