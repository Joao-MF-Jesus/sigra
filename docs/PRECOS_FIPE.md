# Referencia de precos FIPE

O SIGRA diferencia tres estados de preco:

- `fipe`: a versao foi mapeada e o valor foi retornado e validado pela API; ele pode ser usado no TCO e no ranking.
- `fipe_mapping`: codigo e versao estao cadastrados, mas a sincronizacao ainda nao ocorreu; o sistema mantem temporariamente o valor demonstrativo.
- `demonstrative`: nao existe mapeamento FIPE para o veiculo.

Essa separacao evita apresentar um valor antigo ou demonstrativo como FIPE vigente quando o provedor externo estiver indisponivel.

## Pareamento das 34 fichas

| ID | Veiculo SIGRA | Codigo FIPE | Versao usada no pareamento |
| ---: | --- | --- | --- |
| 1 | Chevrolet Onix LT 2021 | 004517-9 | ONIX HATCH LT 1.0 12V Flex 5p Mec. |
| 2 | Chevrolet Prisma LT 2018 | 004436-9 | PRISMA Sed. LT 1.4 8V FlexPower 4p Aut. |
| 3 | Chevrolet Cobalt LTZ 2018 | 004421-0 | COBALT LTZ 1.8 8V Econo.Flex 4p Aut. |
| 4 | Chevrolet Spin LT 2019 | 004415-6 | SPIN LT 1.8 8V Econo.Flex 5p Aut. |
| 5 | Chevrolet Tracker LT 2021 | 004522-5 | TRACKER LT 1.0 Turbo 12V Flex Aut. |
| 6 | Hyundai HB20 Comfort 2020 | 015168-8 | HB20 Vision 1.0 Flex 12V Mec. (equivalente disponivel no ano) |
| 7 | Hyundai HB20S Comfort 2020 | 015174-2 | HB20S Vision 1.0 Flex 12V Mec. (equivalente disponivel no ano) |
| 8 | Hyundai Creta Attitude 2019 | 015157-2 | Creta Attitude 1.6 16V Flex Aut. |
| 9 | Toyota Corolla GLi 2018 | 002109-1 | Corolla GLi 1.8 Flex 16V Aut. |
| 10 | Toyota Etios XLS 2018 | 002150-4 | ETIOS XLS 1.5 Flex 5p Aut. |
| 11 | Toyota Yaris XL 2020 | 002172-5 | YARIS XL 1.3 Flex 16V 5p Aut. |
| 12 | Toyota Corolla Cross XR 2022 | 002201-2 | Corolla Cross XR 2.0 16V Flex Aut. |
| 13 | Honda Fit EX 2017 | 014045-7 | Fit EX/S 1.5 Flex 16V 5p Aut. |
| 14 | Honda City LX 2018 | 014059-7 | CITY Sedan LX 1.5 Flex 16V 4p Aut. |
| 15 | Honda Civic EX 2017 | 014091-0 | Civic Sedan EX 2.0 Flex 16V Aut. |
| 16 | Honda HR-V LX 2018 | 014086-4 | HR-V LX 1.8 Flexone 16V 5p Aut. |
| 17 | Volkswagen Gol Trendline 2019 | 005490-9 | Gol 1.0 Flex 12V 5p (equivalente disponivel no ano) |
| 18 | Volkswagen Polo MSI 2019 | 005478-0 | Polo 1.6 MSI Flex 16V 5p |
| 19 | Volkswagen Virtus MSI 2019 | 005486-0 | Virtus 1.6 MSI Flex 16V 5p Mec. |
| 20 | Volkswagen Voyage Comfortline 2018 | 005458-5 | VOYAGE Comfortline 1.0 T.Flex 12V 4p |
| 21 | Volkswagen T-Cross 200 TSI 2020 | 005509-3 | T-Cross Comfortline 200 TSI 1.0 Flex Aut. |
| 22 | Fiat Mobi Like 2021 | 001461-3 | MOBI LIKE 1.0 Fire Flex 5p |
| 23 | Fiat Uno Attractive 2018 | 001486-9 | UNO DRIVE 1.0 Flex 6V 5p (equivalente disponivel no ano) |
| 24 | Fiat Argo Drive 2020 | 001494-0 | ARGO DRIVE 1.0 6V Flex |
| 25 | Fiat Cronos Drive 2020 | 001505-9 | CRONOS DRIVE 1.3 8V Flex |
| 26 | Renault Sandero Zen 2020 | 025288-3 | SANDERO Zen Flex 1.0 12V 5p Mec. |
| 27 | Renault Logan Zen 2020 | 025290-5 | LOGAN Zen Flex 1.0 12V 4p Mec. |
| 28 | Renault Duster Zen 2020 | 025302-2 | DUSTER Zen 1.6 16V Flex Aut. |
| 29 | Nissan March SV 2018 | 023143-6 | MARCH SV 1.6 16V FlexStart 5p Aut. |
| 30 | Nissan Versa SV 2019 | 023144-4 | VERSA SV 1.6 16V FlexStart 4p Aut. |
| 31 | Nissan Kicks S 2020 | 023156-8 | KICKS S 1.6 16V Flex 5p Aut. |
| 32 | Jeep Renegade Sport 2019 | 017034-8 | Renegade Sport 1.8 4x2 Flex 16V Aut. |
| 33 | Ford Ka SE 2019 | 003408-8 | Ka 1.0 SE/SE Plus TiVCT Flex 5p |
| 34 | Ford EcoSport SE 2018 | 003440-1 | EcoSport SE 1.5 12V Flex 5p Aut. |

## Uso na API

- `GET /vehicles` inclui `price_reference` em cada veiculo.
- `GET /vehicles/{id}/price-reference` detalha a origem do preco.
- `GET /health` separa cobertura de mapeamento e quantidade sincronizada.

O valor FIPE e uma referencia media nacional para negociacao. Precos reais variam por regiao, conservacao, quilometragem, cor e opcionais.

## Atualizacao automatica

O backend verifica o cache ao listar veiculos, comparar ou gerar recomendacoes. Quando o cache ultrapassa `FIPE_CACHE_TTL_HOURS`, consulta a API Parallelum pelo codigo FIPE, resolve o identificador exato de ano e combustivel, confere a resposta e salva o ultimo valor valido em `backend/data/fipe_cache.json`.

Se a consulta externa falhar, a demonstracao continua usando o ultimo valor validado. A falha e registrada em `GET /prices/fipe/status`.

- `GET /prices/fipe/status`: mostra mes, origem, atualidade do cache e ultimo erro.
- `POST /prices/fipe/refresh`: forca uma nova consulta, util para administracao.

A FIPE e atualizada mensalmente; portanto, "tempo real" significa sincronizar automaticamente a referencia mensal vigente, e nao acompanhar precos de anuncios a cada minuto.
