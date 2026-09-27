# Batch 3: admissão documental parcial, somente acadêmica

O contrato `batch3_collection_v1.json` preserva os 34 legados e os 19 novos
anteriores, reconcilia os 47 IDs restantes e admite **somente o ID 55** neste
incremento. São 54 identidades integradas, não 60. Seis vagas novas permanecem
abertas; candidatos não selecionados não foram excluídos nem renumerados.

## Sentra SV 2.0 CVT, ano-modelo 2020

O vínculo `sentra-novo-sentra-v1` já existente em `batch1_crosswalk_v1.json`
comprova FIPE `023123-1 / 2020-5`, setembro/2026, R$ 74.933,00, e a linha PBEV
2020 da página 9, linha 10: `Novo Sentra / SV / 2.0-16V / CVT / flex`.
O replay verifica os bytes FIPE/PBEV; não usa preço demonstrativo ou consumo
publicitário. O PBEV informa 9,9 km/l urbano e 12,7 km/l rodoviário a gasolina.

O catálogo oficial Nissan Sentra 2020 brasileiro, congelado por SHA-256 no
manifesto `batch3_evidence_v1.json`, foi conferido visualmente nas páginas
11 e 12. A coluna SV comprova dois airbags frontais, ABS e VDC de série.
Os airbags laterais/cortina da SL não foram transferidos para a SV.
O arquivo está hospedado em diretório 2021, mas a capa e o conteúdo identificam
ano-modelo 2020; a data editorial é abril/2019. Não se deduziu ano-modelo pela URL.

Foram admitidos lugares, porta-malas, comprimento, largura corporal, entre-eixos,
vão livre, massa da coluna SV e potência explicitamente válida para gasolina.
A largura não comprova retrovisores abertos. Medidas internas permanecem
indisponíveis; a habitabilidade continua identificada como proxy acadêmico v4.

## Integração opt-in

`batch3_academic_v4.batch3_matrix` recebe candidatos já revalidados e arquivo
local de fontes. Retorna apenas as admissões novas; não altera o carregador v3,
o catálogo operacional nem os 36 veículos anteriormente testáveis.
O manifesto referencia o crosswalk existente, sem duplicar ou substituir
identidade. Cache adulterado, versão/ano divergente, unidades incorretas,
equipamento opcional e identidade canônica duplicada são rejeitados.

O resultado é preview offline: 37 veículos distintos testáveis; Cidade 10,
Aplicativo 37, Trabalho 10, Espaço/capacidade 24, Família 1 e Estrada 1.
Os cenários baixo/base/alto reutilizam parâmetros e fórmulas versionados, sem
modificações. `observed_tco_complete=false`, `operationally_active=0`,
`recommended=0`. A calculabilidade não constitui recomendação ao consumidor.

## Lacunas e limites

A seleção não atingiu sete admissões. O release brasileiro XV 2018 recuperado
não explicita ABS; distribuição eletrônica de frenagem não o substitui.
As referências de CR-V 2018/WR-V 2021 não comprovam os alvos 2019/2020.
Materiais estrangeiros e versões diferentes não foram admitidos.
Downloads anteriormente bloqueados por 403 não foram repetidos.
As buscas sem resultado exato não provam ausência de equipamentos.

Respostas, documentos, páginas renderizadas, orçamento e relatório de execução
permanecem fora do Git. Nenhuma chamada FIPE/CarPedia foi necessária para o ID 55.
Os tetos remanescentes não foram renovados e esta admissão não autoriza
publicação, Gold, PostgreSQL, frontend ou novo checkpoint.
