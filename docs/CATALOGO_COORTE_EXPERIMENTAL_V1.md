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

| Perfil | Elegíveis agora | IDs | Lacuna até 10 |
|---|---:|---|---:|
| Cidade | 1 | 36 | 9 |
| Aplicativo | 0 | — | 10 |
| Trabalho | 0 | — | 10 |
| Família | 0 | — | 10 |
| Estrada | 0 | — | 10 |
| SUV/espaço | 0 | — | 10 |

As lacunas não devem ser somadas para decidir quantos veículos comprar/coletar: um único dossiê completo pode cobrir os seis perfis. O limite inferior matemático de novos candidatos é zero porque há 14 identidades aprovadas sem conflito ou aprovação humana pendente; porém a completude documental dessas identidades ainda não foi comprovada. Portanto, nenhum ID adicional foi selecionado.

Os dez primeiros dossiês existentes para coleta dirigida são 36, 37, 38, 39, 42, 43, 44, 46, 47 e 49. Essa ordem usa apenas quantidade de evidências já observadas e ID como desempate, nunca preço, score desejado ou grupo comercial. Os IDs 57–100 ficam apenas no backlog.

## Alinhamento FIPE e identidade

Os 34 legados têm referência de julho de 2026; os 19 candidatos, setembro de 2026. Por isso não existe ranking conjunto válido. O inventário exato para alinhar os legados contém 34 requisições por código FIPE e código de ano já conhecidos, sem chamadas de descoberta. Isso corresponde a 3,4% do teto mensal de 1.000 informado pelo usuário.

Nenhuma chamada foi executada: a integração atual não comprova contrato autenticado, saldo de cota, pinagem do mês de referência nem revisão de todos os alvos. O saldo restante permanece desconhecido. Repetições devem usar recibo imutável por versão da API, código, ano e mês, com SHA-256; cada tentativa HTTP, inclusive falha, consome o orçamento registrado.

Quatro diferenças de grafia da reprodução legada foram corrigidas somente no vínculo da referência de preço, por tupla exata e hash do cache: IDs 9, 15, 19 e 21. Isso não aprova identidade de catálogo. Permanecem incompatibilidades explícitas de versão nos IDs 6 (Comfort/Vision), 7 (Comfort/Vision) e 23 (Attractive/Drive), além de revisões específicas nos IDs 13, 17, 21 e 33. Não há fuzzy matching.

## Coleta e CarPedia

Primeiro devem ser reutilizados PBEV, cache FIPE e documentos OEM já preservados. Dos dez dossiês prioritários, dois já possuem documento OEM e oito demandam provisoriamente um documento individual; o rendimento por documento é desconhecido e um único documento pode cobrir vários campos ou nenhum.

A CarPedia fica apenas planejada, sem chamadas: no máximo uma resposta em cache por identidade, endpoint versionado por identificador externo oficial e ano, e dez chamadas provisórias (10% do limite mensal de 100 informado). Antes de qualquer chamada são necessários autorização humana adicional, saldo comprovado, identificador externo exato e contrato atual confirmado. Marca/modelo/versão/ano/motor/combustível/câmbio devem coincidir; preço e mês continuam FIPE, consumo e powertrain continuam PBEV e qualquer divergência técnica exige confirmação OEM. CarPedia nunca substitui silenciosamente fonte oficial.

## Custos e qualidade

Custos conhecidos/observados, estimativas e TCO completo permanecem separados. Componente ausente não vira zero, custo parcial não vira TCO e orçamento mensal não é comparado com manutenção anual. Os 318 checks de estabilidade V3 continuam aprovados; esta camada não modifica o algoritmo V3.

O gate experimental exige dez opções metodologicamente elegíveis em cada perfil e os 318 checks aprovados. O gate está reprovado enquanto as lacunas acima existirem. Isso não autoriza PostgreSQL operacional, publicação, E2E ou ativação do ranking.

Os artefatos completos — matriz com 318 linhas, razões de bloqueio, sobreposição, plano FIPE, estimativas por ficha e plano CarPedia — são gerados fora do repositório para auditoria.
