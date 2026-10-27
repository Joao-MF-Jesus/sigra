# Integração externa controlada dos legados v4

Adaptador opt-in `legacy_external_v4`, sem importação por publicação, backend ou
v3. O manifesto `legacy_external_v4_evidence_v1.json` registra os 18 dossiês e
admite exclusivamente o ID 12, condicionado à verificação dos bytes externos.
Não altera cadastro, regras, taxas, critérios, pesos ou evidências anteriores.

## Admissão documental individual

Corolla Cross XR 2022: FIPE 002201-2 / 2022-5, preço de setembro/2026 já
preservado; PBEV 2022, página 2, linha 17, `COROLLA CROSS / XR 20 / 2.0 - 16V /
CVT / flex`. A linha XR é distinta da XRE e das híbridas. O vínculo preenche a
fonte 2022 ausente; não substitui acabamento ou configuração anterior.

A descoberta CarPedia retornou o identificador 22012 com a descrição FIPE
exata e ano 2022. A ficha informa explicitamente `Automático (CVT)`. O booleano
`manual` não é interpretado como câmbio. O PDF oficial é reprocessado a partir
do SHA-256 já auditado no parser; não se confia somente em JSON destacado do PDF.
Combustível, transmissão e consumo continuam exclusivamente PBEV. Consumo
CarPedia não substitui o ciclo oficial. Largura da carroceria não vira largura
com espelhos. Itens ausentes, inclusive airbags/ABS/ESC, permanecem desconhecidos.

## Bloqueios preservados

Os demais 17 IDs não são promovidos. LT não individualiza 1LT/2LT/5LT/8LT;
XL não comprova XL Live; versões PBEV vazias não comprovam MSI; nenhuma escolha
silenciosa de Stop & Start, Logan/Logan-P2 ou Zen/Expression é permitida.
Comfort/Vision, EX/S e Attractive/Drive não são equivalências aceitas.
Corolla automático não comprova CVT; Ka SE/SE Plus continua agregado.
As fichas insuficientes dos IDs 9 e 33 não foram repetidas.

Nenhuma correção material de identidade é aplicada ou proposta como aprovada.
Uma substituição futura requer proposta versionada com antes/depois, fontes e
decisão humana quando cabível. Os indicadores de necessidade de revisão no
manifesto não constituem proposta de substituir um veículo por outro.

## Reprodução e limites

Fornecer `SourceArchive` com os acervos FIPE/PBEV/CarPedia locais e os documentos
da rodada, todos fora do Git. Executar o adaptador após
`augment_legacy_technical_v4` nos 34 IDs canônicos. Reexecutar os três cenários e
o conjunto anterior de 35 testáveis mais o ID 12. Não anexar caches, PDFs,
relatórios ou credenciais ao repositório.

O preview não é recomendação: `operationally_active=0`, `recommended=0`, nenhum
ranking operacional. TCO de cenário não passa a observado. O relatório externo
contém chamadas efetivas, recibos, hashes, campos normalizados, motivos por ID,
resultados individuais e conjuntos, idempotência e comparação de fingerprints v3.
Os testes sintéticos validam rejeições; somente o replay dos bytes reais valida
a admissão desta rodada. Todos os arquivos previamente rastreados são preservados.
