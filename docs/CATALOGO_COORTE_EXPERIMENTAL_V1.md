# Coorte experimental por perfil — evidência v1

## Decisão

Escopo confirmado pelo usuário em 21/09/2026: **60 automóveis no total**,
incluindo os **34 legados preservados e 26 novos**. Os seis perfis compartilham
esse universo; sobreposição entre perfis é permitida e não cria novos veículos.
O objetivo de 26 novos elegíveis e publicados academicamente ainda não foi
atingido: há **19 novos com identidade e TCO acadêmico** (nove do primeiro replay
e dez do segundo), restando selecionar e processar **somente sete**. Quantidade
integrada não comprova prontidão de todos os perfis nem publicação.

A seleção dos sete será posterior à revisão documental de segurança e deverá
priorizar Aplicativo, Família e Estrada. Nesta etapa nenhum novo ID foi escolhido.
Os demais candidatos permanecem versionados e inativos como backlog: não excluir,
renumerar nem reutilizar IDs. As aprovações humanas existentes são preservadas;
o ID 41 segue pendente e os bloqueios 48, 50, 53 e 57 continuam vigentes.

Esta camada é somente um gate de prontidão e planejamento offline. Ela não altera os pesos, scores ou custos V3, não ativa ranking, não publica no PostgreSQL e não autoriza chamadas externas.

## Núcleo mínimo por perfil

| Perfil | Evidência obrigatória | Evidência opcional, que não bloqueia |
|---|---|---|
| Cidade | preço FIPE do mês, consumo urbano, combustível, comprimento e largura com espelhos | vão livre |
| Aplicativo | preço FIPE do mês, consumo urbano, combustível, assentos e porta-malas | espaço traseiro e largura interna |
| Trabalho | preço FIPE do mês, consumo urbano, combustível e ao menos um entre carga útil ou porta-malas | comprimento e largura com espelhos |
| Família | preço FIPE do mês, assentos, porta-malas, airbags, ABS e ESC | largura interna |
| Estrada | preço FIPE do mês, consumo rodoviário, combustível, airbags, ABS e ESC | peso, potência a gasolina e câmbio |
| Espaço/capacidade (`suv`) | preço FIPE do mês, assentos, porta-malas, carroceria documentada e vão livre | entre-eixos, largura e largura interna |

Ausência não vira zero. Airbags, ABS e ESC são inventário explícito de equipamentos, não nota de segurança. Carroceria é descrição documentada por variante e não pode ser inferida por nome, silhueta ou grupo de coleta. Cobertura do núcleo e score continuam conceitos separados.

## Resultado material da matriz 34 + 19

| Perfil | `core_coverage_complete_and_eligible_candidates` | IDs | Lacuna documental preliminar até 10 |
|---|---:|---|---:|
| Cidade | 2 | 36, 37 | 8 |
| Aplicativo | 9 | 36, 37, 38, 39, 42, 43, 46, 47, 49 | 1 |
| Trabalho | 9 | 36, 37, 38, 39, 42, 43, 46, 47, 49 | 1 |
| Família | 0 | — | 10 |
| Estrada | 0 | — | 10 |
| Espaço/capacidade (`suv`) | 3 | 36, 42, 43 | 7 |

As lacunas não devem ser somadas para decidir quantos veículos comprar/coletar: um único dossiê completo pode cobrir os seis perfis. O limite inferior matemático de novos candidatos é zero porque há 14 identidades aprovadas sem conflito ou aprovação humana pendente; porém a completude documental dessas identidades ainda não foi comprovada. Portanto, nenhum ID adicional foi selecionado.

`partial_coverage_candidates` agora significa literalmente que existe alguma evidência relevante do perfil e é contado independentemente da elegibilidade. `core_coverage_complete_candidates` mede apenas completude documental; `profile_eligible` aplica os gates independentes. A tabela acima usa a interseção explícita `core_coverage_complete_and_eligible_candidates`, equivalente ao antigo núcleo preliminar aprovado. Na metodologia V3, Cidade contém os IDs 36 e 37 e Espaço/capacidade contém os IDs 36, 42 e 43 como `methodology_ready`; Aplicativo, Trabalho, Família e Estrada permanecem sem dossiê pronto. Os cinco resultados são calculáveis e elegíveis apenas segundo suas rubricas; nenhum é recomendável porque o TCO operacional continua incompleto. Nenhum ranking de recomendação foi executado.

Os dez primeiros dossiês existentes para coleta dirigida são 36, 37, 38, 39, 42, 43, 44, 46, 47 e 49. Essa ordem usa apenas quantidade de evidências já observadas e ID como desempate, nunca preço, score desejado ou grupo comercial. A primeira rodada CarPedia consumiu o teto local de dez tentativas: oito descobertas exatas e duas fichas, para os IDs 46 e 47. A segunda rodada reutilizou seis descobertas do cache e consumiu exatamente oito tentativas HTTP: seis fichas diretas para os IDs 36, 37, 38, 39, 42 e 43, mais descoberta e ficha do ID 49. Todas retornaram HTTP 200 e passaram código FIPE, versão, ano, combustível e identidade exatos. O ID 44 permanece sem identificador inequívoco por causa de Fiesta/New Fiesta, sem chamada. A expansão via CarPedia fica temporariamente encerrada e os IDs 57–100 continuam apenas no backlog.

## Alinhamento FIPE e identidade

Os 34 legados partiam de julho de 2026; os 19 candidatos já estavam em setembro de 2026. A coleta controlada atualizou 27 legados para setembro usando código FIPE e código de ano exatos, sem descoberta, sem retry e com 27 tentativas do limite autorizado de 34. Uma repetição integral reutilizou 27 respostas do cache e realizou zero chamadas.

Permanecem fora do alinhamento os IDs 6, 7 e 23, bloqueados por contrato incompatível, e 13, 17, 21 e 33, mantidos em revisão antes de qualquer consulta ou publicação. Assim, a comparação temporal conjunta continua bloqueada e nenhum ranking artificial é emitido. A documentação oficial da API FIPE/Parallelum confirma acesso público sem autenticação e limite anônimo de 500 requisições por dia. O limite operacional desta coleta foi deliberadamente mais estrito: 34 tentativas totais, contando falhas e retries, com retries desabilitados. O cache de julho permaneceu imutável; o cache externo novo é ligado por versão, código, ano, mês e SHA-256.

Quatro diferenças de grafia da reprodução legada foram corrigidas somente no vínculo da referência de preço, por tupla exata e hash do cache: IDs 9, 15, 19 e 21. Isso não aprova identidade de catálogo. Permanecem incompatibilidades explícitas de versão nos IDs 6 (Comfort/Vision), 7 (Comfort/Vision) e 23 (Attractive/Drive), além de revisões específicas nos IDs 13, 17, 21 e 33. Não há fuzzy matching.

Uma nova chamada ao mesmo endpoint de preço não resolve esses sete casos: 6, 7 e 23 precisam de código/identidade exatos para o acabamento do catálogo; 13 e 33 usam descrições FIPE combinadas; 17 omite Trendline; 21 vincula preço Comfortline a um catálogo que informa apenas 200 TSI. Portanto, há **7 veículos pendentes de alinhamento temporal**. No orçamento formal da rodada FIPE, 34 tentativas foram planejadas/autorizadas, 27 foram executadas e 7 ficaram disponíveis; esses três valores são registrados separadamente. Todos os sete veículos permanecem incompatíveis com publicação Silver/Gold até a evidência indicada no manifesto.

## Coleta e CarPedia

Primeiro devem ser reutilizados PBEV, cache FIPE e documentos OEM já preservados. As fichas CarPedia dos IDs 36, 37, 38, 39, 42, 43, 46, 47 e 49 foram reprocessadas exclusivamente do cache consolidado, ligadas a hash, identificador externo, ano, localizador de campo e momento da coleta. Nenhum valor foi estimado e ausência continuou `null/unavailable`.

A documentação e o cliente versionado preservam autenticação Bearer, descoberta de versões em `/api/v1/modelos/{marca}/{modelo}/versoes`, ficha em `/api/v1/ficha/{fipeId}/{ano}` e parada em 401, 403 ou 429. As nove fichas cacheadas possuem identidade exata por código FIPE/identificador externo, ano e descrição versionada. Carroceria, lugares, porta-malas, comprimento, largura da carroceria, entre-eixos, cilindrada, potência, câmbio, combustível e tanque foram reconhecidos nos nove veículos; carga útil permanece indisponível nos IDs 38, 46 e 49. Campos de fabricante já presentes e concordantes são preservados, sem troca de proveniência. O campo CarPedia `manual` não é usado como transmissão. Largura da carroceria não foi promovida a largura com espelhos e potência flex genérica não foi promovida a potência a gasolina. Preço, mês e identidade continuam FIPE; consumo, combustível e câmbio continuam PBEV. CarPedia nunca substitui silenciosamente fonte prioritária.

A auditoria offline posterior recuperou `ground_clearance_mm` explicitamente
nas fichas exatas dos IDs 42 (147 mm) e 43 (125 mm), com hash, localizador,
unidade e instante de coleta. O ID 36 também contém 164 mm na ficha CarPedia,
mas mantém os 162 mm já vinculados ao documento do fabricante; a divergência
não é sobrescrita. Nenhuma das nove fichas contém rótulo inequívoco de airbags,
ABS, ESC, largura com espelhos ou medida interna de passageiros. Campo ausente
permanece desconhecido, nunca `false`. A nota Latin NCAP presente no ID 42 não
é convertida em inventário de airbags, ABS ou ESC.

No núcleo experimental, os nove dossiês completam os requisitos preliminares de Aplicativo e Trabalho; Cidade contém 36 e 37 e Espaço/capacidade contém 36, 42 e 43. A chave interna `suv` é mantida somente por compatibilidade: não existe requisito categórico de carroceria SUV e os hatches não são reclassificados. Isso não equivale a recomendação pronta: Aplicativo ainda exige espaço de passageiros; Trabalho ainda exige custo operacional e pegada com largura incluindo espelhos; Família e Estrada exigem inventário de segurança. O TCO operacional permanece incompleto, sem conversão de ausência em zero. Nenhum ranking de recomendação foi gerado porque os sete legados acima continuam temporalmente desalinhados, o gate mínimo de dez opções por perfil continua reprovado e nenhum dos nove tem os cinco componentes observacionais de TCO.

Na camada acadêmica separada, o TCO de cenário em `BRL/month` pode preencher
somente o `operating_cost` acadêmico de Trabalho. Com a largura com espelhos já
documentada, isso torna 36 e 37 `academic_test_ready` para Trabalho, sem mudar
`profile_scoreable`, `methodology_ready` ou ativação operacional. A derivação
`body_footprint_m2` é calculada para os nove a partir de comprimento e largura
da carroceria, mas não satisfaz o `footprint` v3 de Cidade/Trabalho, que continua
exigindo largura com espelhos. Nenhuma dessas classificações é recomendação ou
publicação.

A contabilidade da segunda rodada é: **seis cache hits de descoberta** e **oito novas tentativas HTTP** (seis fichas diretas, mais descoberta e ficha do ID 49). O manifesto registra **nove hashes de ficha**: sete respostas da segunda rodada e as duas fichas preservadas da primeira rodada, IDs 46 e 47. Hash de descoberta não foi contado como ficha nem como décimo dossiê.

As aprovações humanas dos IDs 40, 45 e 56 foram registradas de forma versionada e auditável. O ID 41 permanece pendente; os bloqueios 48, 50 e 53 permanecem inalterados.

## Segundo lote controlado dos IDs 57–100

Antes de qualquer HTTP, os 44 IDs foram ordenados integralmente e a seleção foi
congelada em `57, 58, 59, 68, 69, 70, 79, 80, 91, 92, 93`. O conjunto cobre os
alvos de coleta de Aplicativo e Trabalho com 11 dossiês cada, Família com 8,
Estrada com 6 e Espaço/capacidade com 8. Esses grupos orientam coleta; não são
elegibilidade, prontidão ou recomendação.

A rodada consumiu 11/11 tentativas FIPE e 10/22 tentativas CarPedia. No acumulado
controlado, isso representa 38/38 FIPE e 28/40 CarPedia. Não houve descoberta
CarPedia: os dez identificadores externos foram derivados exclusivamente do
código FIPE canônico já confirmado. O ID 57 recebeu HTTP 404 no alvo FIPE exato
de setembro/2026 e foi bloqueado antes de qualquer chamada CarPedia. Os demais
dez passaram código FIPE, ano, versão, combustível e conjunto mecânico sem fuzzy
matching. Nenhuma fonte retornou 401, 403 ou 429.

| ID | Identidade | Preço FIPE (set/2026) | CarPedia | Espaço/capacidade acadêmico |
|---:|---|---:|---|---|
| 57 | bloqueada: FIPE exata retornou 404 | indisponível | não consultada | não |
| 58 | SpaceFox Trendline 1.6 manual | R$ 50.516 | exata | bloqueado: vão livre ausente |
| 59 | Aircross Live 1.6 manual | R$ 55.942 | exata | pronto para teste acadêmico |
| 68 | Doblò Essence 1.8 manual | R$ 55.217 | exata | pronto para teste acadêmico |
| 69 | C4 Picasso Intensive 1.6 turbo automático | R$ 84.584 | exata | bloqueado: vão livre ausente |
| 70 | Tiguan Allspace Comfortline 1.4 TSI automática | R$ 116.704 | exata | pronto para teste acadêmico |
| 79 | Jetta Comfortline 1.4 TSI automático | R$ 110.110 | exata | pronto para teste acadêmico |
| 80 | Focus Fastback SE/SE Plus 2.0 automático | R$ 57.921 | exata | bloqueado: vão livre ausente |
| 91 | Captur Zen 1.6 CVT | R$ 72.930 | exata | pronto para teste acadêmico |
| 92 | 2008 Allure 1.6 automático | R$ 61.825 | exata | pronto para teste acadêmico |
| 93 | C4 Cactus Feel 1.6 automático | R$ 67.229 | exata | pronto para teste acadêmico |

As dez fichas comprovam carroceria, lugares, porta-malas, carga útil,
comprimento, largura da carroceria, entre-eixos, cilindrada, potência,
transmissão, combustível e tanque. Vão livre foi admitido em sete fichas: 59,
68, 70, 79, 91, 92 e 93. Nenhuma ficha comprovou largura com espelhos, espaço
interno de passageiros ou o inventário completo de airbags/ABS/ESC. Ausência
permanece `null/unavailable`; largura da carroceria não substitui largura com
espelhos. FIPE mantém preço e identidade; PBEV mantém consumo, combustível e
transmissão. O booleano `manual` da CarPedia não é usado como câmbio.

O replay acadêmico combina os nove dossiês anteriores com os dez novos, sem
duplicidade. Todos os 19 têm identidade exata, cobertura parcial, elegibilidade
categórica e TCO acadêmico completo nos cenários baixo/base/alto. A revisão
documental oficial de largura aberta entre retrovisores eleva a prontidão
acadêmica de Cidade e Trabalho de 2 para 10: IDs 36, 37, 46, 47, 69, 70, 79, 91,
92 e 93. Após a revisão de aplicabilidade das fontes, Família e Estrada
permanecem em 0; os dois inventários antes contados provisoriamente ainda não
satisfazem a prova de configuração exata. Aplicativo permanece em 0. Espaço/capacidade
permanece em 10 (36, 42, 43, 59, 68, 70, 79, 91, 92 e 93).
`operationally_active=0`,
`recommended=0` e nenhum ranking operacional foi executado.

Os oito fatos novos são dimensões nominais de manuais oficiais, com URL, página,
localizador, data e SHA-256 no contrato `profile_sources_v3.json`. Não há proxy:
largura de carroceria e largura com retrovisores recolhidos são mantidas distintas
da largura aberta. O gate acadêmico de Trabalho pode usar apenas o TCO de cenário
versionado como `operating_cost`; isso não torna seu gate operacional completo.

## Inventário acadêmico de segurança

A busca documental priorizou os 19 veículos já integrados e não criou Batch 3.
Os dois resultados preliminares foram reavaliados em 21/09/2026. O laudo Latin
NCAP do Cruze documenta um sedã com seis airbags, ABS e ESC a partir de uma
data/VIN, mas não identifica a versão LT. Falta a ponte documental entre essa
configuração e o ID 46 MY2020. Os três valores foram conservados em
`pending_fields`, com origem e hash, e não alimentam a prontidão.

No Focus Fastback MY2018 (ID 80), a extração mostra cinco células de equipamentos
e quatro títulos de versão, sem preservar as colunas mescladas. O total de airbags
permanece pendente até comprovar a coluna SE Plus. ABS/EBD e ESC/TCS são positivos
em todas as cinco células e permanecem admitidos. O download direto do PDF
retornou HTTP 403; o SHA-256 existente identifica a extração normalizada, não os
bytes originais do PDF. A classificação em estrelas não foi importada.

Os outros 17 veículos continuam com segurança desconhecida. Documentos de outro
ano ou mercado, manuais que dizem “se equipado”, catálogos sem coluna inequívoca
da versão e testes Latin NCAP que abrangem configuração diferente foram
rejeitados. Equipamento opcional não virou padrão; ausência de campo não virou
`false`. Nenhum dos 19 possui inventário completo aprovado nesta revisão;
Família e Estrada permanecem em 0, com lacuna de dez inventários exatos.
Cruze e Focus seguem prioritários para fechar a aplicabilidade documental.
Cidade, Trabalho e Espaço/capacidade permanecem com 10;
Aplicativo permanece com 0. `operationally_active=0`, `recommended=0` e nenhum
ranking operacional foi criado.

## Custos e qualidade

Custos conhecidos/observados, estimativas e TCO completo permanecem separados. Componente ausente não vira zero, custo parcial não vira TCO e orçamento mensal não é comparado com manutenção anual. Os 318 checks de estabilidade V3 continuam aprovados; esta camada não modifica o algoritmo V3.

O gate experimental exige dez opções metodologicamente elegíveis em cada perfil e os 318 checks aprovados. O gate está reprovado enquanto as lacunas acima existirem. Isso não autoriza PostgreSQL operacional, publicação, E2E ou ativação do ranking.

Os artefatos completos — matriz com 318 linhas, razões de bloqueio, sobreposição, plano FIPE, estimativas por ficha e plano CarPedia — são gerados fora do repositório para auditoria.
