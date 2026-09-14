# Coorte experimental por perfil — evidência v1

## Decisão

A expansão ampla dos IDs 57–100 permanece congelada. A base defensável é formada pelos 34 veículos legados e pelos 19 candidatos com identidade aprovada já preservados, excluindo os conflitos 48, 50 e 53. O mesmo veículo pode atender a mais de um perfil; os seis grupos não são exclusivos.

Esta camada é somente um gate de prontidão e planejamento offline. Ela não altera os pesos, scores ou custos V3, não ativa ranking, não publica no PostgreSQL e não autoriza chamadas externas.

## Núcleo mínimo por perfil

| Perfil | Evidência obrigatória | Evidência opcional, que não bloqueia |
|---|---|---|
| Cidade | preço FIPE do mês, consumo urbano, combustível, comprimento e largura com espelhos | vão livre |
| Aplicativo | preço FIPE do mês, consumo urbano, combustível, assentos e porta-malas | espaço traseiro e largura interna |
| Trabalho | preço FIPE do mês, consumo urbano, combustível e ao menos um entre carga útil ou porta-malas | comprimento e largura com espelhos |
| Família | preço FIPE do mês, assentos, porta-malas, airbags, ABS e ESC | largura interna |
| Estrada | preço FIPE do mês, consumo rodoviário, combustível, airbags, ABS e ESC | peso, potência a gasolina e câmbio |
| SUV/espaço | preço FIPE do mês, assentos, porta-malas, carroceria documentada e vão livre | entre-eixos, largura e largura interna |

Ausência não vira zero. Airbags, ABS e ESC são inventário explícito de equipamentos, não nota de segurança. Carroceria é descrição documentada por variante e não pode ser inferida por nome, silhueta ou grupo de coleta. Cobertura do núcleo e score continuam conceitos separados.

## Resultado material da matriz 34 + 19

| Perfil | `partial_coverage_candidates` | IDs | Lacuna documental preliminar até 10 |
|---|---:|---|---:|
| Cidade | 1 | 36 | 9 |
| Aplicativo | 2 | 46, 47 | 8 |
| Trabalho | 2 | 46, 47 | 8 |
| Família | 0 | — | 10 |
| Estrada | 0 | — | 10 |
| SUV/espaço | 0 | — | 10 |

As lacunas não devem ser somadas para decidir quantos veículos comprar/coletar: um único dossiê completo pode cobrir os seis perfis. O limite inferior matemático de novos candidatos é zero porque há 14 identidades aprovadas sem conflito ou aprovação humana pendente; porém a completude documental dessas identidades ainda não foi comprovada. Portanto, nenhum ID adicional foi selecionado.

`partial_coverage_candidates` mede somente o núcleo mínimo preliminar e não representa recomendação pronta nem `methodology_ready`. Na metodologia V3, os IDs 46 e 47 permanecem com `methodology_ready=false` em todos os seis perfis; Cidade mantém somente o ID 36 pronto. Nenhum ranking conjunto foi gerado.

Os dez primeiros dossiês existentes para coleta dirigida são 36, 37, 38, 39, 42, 43, 44, 46, 47 e 49. Essa ordem usa apenas quantidade de evidências já observadas e ID como desempate, nunca preço, score desejado ou grupo comercial. A primeira rodada CarPedia consumiu o teto local de dez tentativas: oito descobertas exatas e duas fichas, para os IDs 46 e 47. O ID 44 permaneceu sem identificador de modelo inequívoco e o limite foi atingido antes do ID 49. Uma rodada futura, ainda não executada, pode reutilizar os identificadores já descobertos para seis fichas diretas (36, 37, 38, 39, 42 e 43) e reservar até duas tentativas para descoberta e ficha do ID 49. Os IDs 57–100 ficam apenas no backlog.

## Alinhamento FIPE e identidade

Os 34 legados partiam de julho de 2026; os 19 candidatos já estavam em setembro de 2026. A coleta controlada atualizou 27 legados para setembro usando código FIPE e código de ano exatos, sem descoberta, sem retry e com 27 tentativas do limite autorizado de 34. Uma repetição integral reutilizou 27 respostas do cache e realizou zero chamadas.

Permanecem fora do alinhamento os IDs 6, 7 e 23, bloqueados por contrato incompatível, e 13, 17, 21 e 33, mantidos em revisão antes de qualquer consulta ou publicação. Assim, a comparação temporal conjunta continua bloqueada e nenhum ranking artificial é emitido. A documentação oficial da API FIPE/Parallelum confirma acesso público sem autenticação e limite anônimo de 500 requisições por dia. O limite operacional desta coleta foi deliberadamente mais estrito: 34 tentativas totais, contando falhas e retries, com retries desabilitados. O cache de julho permaneceu imutável; o cache externo novo é ligado por versão, código, ano, mês e SHA-256.

Quatro diferenças de grafia da reprodução legada foram corrigidas somente no vínculo da referência de preço, por tupla exata e hash do cache: IDs 9, 15, 19 e 21. Isso não aprova identidade de catálogo. Permanecem incompatibilidades explícitas de versão nos IDs 6 (Comfort/Vision), 7 (Comfort/Vision) e 23 (Attractive/Drive), além de revisões específicas nos IDs 13, 17, 21 e 33. Não há fuzzy matching.

Uma nova chamada ao mesmo endpoint de preço não resolve esses sete casos: 6, 7 e 23 precisam de código/identidade exatos para o acabamento do catálogo; 13 e 33 usam descrições FIPE combinadas; 17 omite Trendline; 21 vincula preço Comfortline a um catálogo que informa apenas 200 TSI. Portanto, há **7 veículos pendentes de alinhamento temporal**. No orçamento formal da rodada FIPE, 34 tentativas foram planejadas/autorizadas, 27 foram executadas e 7 ficaram disponíveis; esses três valores são registrados separadamente. Todos os sete veículos permanecem incompatíveis com publicação Silver/Gold até a evidência indicada no manifesto.

## Coleta e CarPedia

Primeiro devem ser reutilizados PBEV, cache FIPE e documentos OEM já preservados. As fichas CarPedia dos IDs 46 e 47 foram reprocessadas exclusivamente do cache, ligadas a hash, identificador externo, ano, localizador de campo e momento da coleta. Nenhum valor foi estimado e ausência continuou `null/unavailable`.

A documentação e o cliente versionado preservam autenticação Bearer, descoberta de versões em `/api/v1/modelos/{marca}/{modelo}/versoes`, ficha em `/api/v1/ficha/{fipeId}/{ano}` e parada em 401, 403 ou 429. Nesta integração offline nenhuma chamada foi realizada. As fichas cacheadas de Cruze (46) e Fluence (47) possuem identidade exata por código FIPE/identificador externo, ano e descrição versionada. Carroceria, lugares, porta-malas, comprimento, largura da carroceria, entre-eixos, cilindrada, potência, câmbio, combustível e tanque foram reconhecidos; carga útil existe somente para o ID 47. O campo CarPedia `manual` não é usado como transmissão. Largura da carroceria não foi promovida a largura com espelhos e potência flex genérica não foi promovida a potência a gasolina. Preço e mês continuam FIPE; consumo, combustível e câmbio continuam PBEV. CarPedia nunca substitui silenciosamente fonte oficial.

No núcleo experimental, ambos os dossiês passam os requisitos mínimos de aplicativo e trabalho. Isso não os torna `methodology_ready` na V3: aplicativo ainda exige o critério de espaço de passageiros; trabalho ainda exige custo operacional e pegada com largura incluindo espelhos; os demais perfis também mantêm suas lacunas obrigatórias. O TCO permanece incompleto, sem conversão de ausência em zero. Nenhum ranking conjunto foi gerado porque os sete legados acima continuam temporalmente desalinhados.

As aprovações humanas dos IDs 40, 45 e 56 foram registradas de forma versionada e auditável. O ID 41 permanece pendente; os bloqueios 48, 50 e 53 permanecem inalterados.

## Custos e qualidade

Custos conhecidos/observados, estimativas e TCO completo permanecem separados. Componente ausente não vira zero, custo parcial não vira TCO e orçamento mensal não é comparado com manutenção anual. Os 318 checks de estabilidade V3 continuam aprovados; esta camada não modifica o algoritmo V3.

O gate experimental exige dez opções metodologicamente elegíveis em cada perfil e os 318 checks aprovados. O gate está reprovado enquanto as lacunas acima existirem. Isso não autoriza PostgreSQL operacional, publicação, E2E ou ativação do ranking.

Os artefatos completos — matriz com 318 linhas, razões de bloqueio, sobreposição, plano FIPE, estimativas por ficha e plano CarPedia — são gerados fora do repositório para auditoria.
