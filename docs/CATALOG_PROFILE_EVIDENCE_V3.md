# Piloto metodológico v3 — evidência, não ativação

Contrato: `catalog-profile-evidence-v3`. Escopo: 34 legados e a coorte acadêmica
atual de 19 identidades (nove do primeiro lote e dez do Batch 2). Não há conexão
a banco, endpoint, alteração
de DTO produtivo, nova migration ou ativação neste módulo. A decisão global
continua `BLOCKED_INSUFFICIENT_PROFILE_EVIDENCE`.

## Componentes e reprodução

- `profile_contracts_v3.py`: valores Decimal, unidades e proveniência por campo;
  `null` exige motivo; fontes oficiais não podem ser substituídas por fabricante
  ou CarPedia. Contratos congelados, com propriedades extras proibidas.
- `profile_method_v3.json`: pesos, critérios obrigatórios, escalas absolutas,
  precisão, fórmulas, justificativas e análise de sensibilidade versionadas.
- `profile_sources_v3.json`: revisão explícita por campo de treze PDFs oficiais
  e uma extração textual normalizada de PDF oficial cujo transporte direto foi
  recusado pelo publicador, com URL, SHA-256 do artefato auditado,
  documento, página/linha, data e aplicabilidade por versão.
- `profile_evidence_v3.py`: revalida bytes FIPE/PBEV com os adaptadores existentes;
  aceita enriquecimento técnico somente para ID/código FIPE/ano/descrição exatos.
- `profile_costs_v3.py`: separa custos conhecidos, estimativas e componentes
  ausentes. Não substitui o motor financeiro do backend.
- `profile_scoring_v3.py` e `profile_analysis_v3.py`: previews, decomposição,
  cobertura, prontidão por perfil, Jaccard, Kendall tau-b e estabilidade.
- `test_catalog_profile_v3.py`: fixtures exclusivamente de testes, nunca fatos
  do piloto. Valida unidades, limites, ausência, fontes e não dependência da coorte.

Para reprodução offline, `candidate_matrix(SourceArchive(directories),
technical_directory)` exige os arquivos cacheados com os SHA-256 registrados.
`legacy_matrix(cache_path, expected_sha256)` não recorre ao seed, ao banco ou a
preços estáticos. `analyze_cohort(vehicles, month)` retorna dados estruturados,
com Decimal; a serialização dos relatórios deve preservá-los como strings.
`combined_preview(legacy, candidates, month)` retorna bloqueio e `profiles=null`
até todos os preços estarem comprovados no mesmo mês.

Os documentos integrais, extrações por página, imagens de conferência e relatórios
ficam fora do repositório. Nenhum PDF, cache, banco ou log faz parte destes arquivos.

## Critérios e limites

| Perfil | Pesos originais | Evidência obrigatória |
|---|---|---|
| Cidade | combustível urbano 45%, envelope externo 25%, preço 30% | todos |
| Aplicativo | combustível urbano 35%, espaço traseiro objetivo 25%, porta-malas 20%, preço 20% | combustível, espaço, porta-malas |
| Trabalho | carga 30%, porta-malas 20%, custo operacional comprovado 30%, envelope 20% | custo operacional, envelope e carga ou porta-malas |
| Família | lugares 20%, porta-malas 25%, segurança 35%, preço 20% | lugares, porta-malas, segurança |
| Estrada | consumo rodoviário 45%, segurança 35%, peso/potência 20%, transmissão 0% | consumo e segurança |
| Espaço/capacidade (`suv` por compatibilidade) | porta-malas 30%, lugares 20%, altura livre 25%, proxy dimensional 25% | porta-malas, lugares e altura livre |

Os estados são deliberadamente separados: `identity_resolved` exige identidade
exata; `partial_coverage_candidate` registra alguma evidência relevante;
`profile_scoreable` exige todas as entradas obrigatórias; `profile_eligible`
aplica identidade, tempo, conflitos, aprovações e regras eliminatórias declaradas;
`methodology_ready` soma scoreabilidade, elegibilidade e cobertura ponderada
mínima de **80%**. `recommended` só pode existir após TCO completo e execução
explícita do ranking de recomendação. Assim, a ordem de `preview_score` permanece
diagnóstico e nunca é publicada como recomendação.

A chave histórica `suv` não classifica carroceria. O perfil aceita qualquer
carroceria documentada e mede exclusivamente espaço/capacidade pelos critérios
versionados. Por isso o rótulo correto é **Espaço/capacidade**; um hatch pode ser
calculável nesse perfil sem ser apresentado como SUV. Nenhuma regra foi mudada
para incluir ou excluir o ID 36.

Os limites absolutos estão integralmente no JSON: para preferência crescente,
`100 * clamp((x-L)/(U-L), 0, 1)`; decrescente,
`100 * clamp((U-x)/(U-L), 0, 1)`. São hipóteses declaradas do piloto, não estatísticas
da amostra. Sensibilidade: cada peso ×0,5/×2 e ambos os limites ×0,9/×1,1, uma
perturbação por vez. Não se ajustam pesos para obter determinado vencedor.

Segurança exige conjuntamente número total de airbags, ABS e ESC comprovados;
não é nota de crash test. Transmissão só recebe peso positivo após preferência
explícita, sem considerar automático universalmente melhor. Envelope usa largura
com espelhos. Proxy de Espaço/capacidade usa entre-eixos × largura da carroceria, sem
espelhos, explicitamente fraco; **não é medida de cabine ou conforto**. Espaço
para aplicativo exige medidas internas, não lugares ou dimensões externas.

Pesos positivos são renormalizados somente entre os critérios disponíveis.
Ausência conserva valor, utilidade e contribuição `null`, nunca 0/50 inventado.
Cobertura não multiplica a nota; confiança estatística permanece `null` por falta
de calibração. Notas parciais com máscaras de evidência distintas **não são
adequações equivalentes**. Os top 10 mistos são diagnósticos, acompanhados dos
grupos de evidência e do subconjunto pronto. Empates usam ID só para exibição;
Jaccard inclui todos os empatados no limite do décimo; Kendall usa tau-b nos IDs
comuns e respeita empates. Ranking vazio dá similaridade indisponível, não zero.

## Resultado da coleta limitada

19/19 candidatos têm preço/identidade FIPE setembro/2026, consumo urbano e
rodoviário a gasolina PBEV e conjunto mecânico rastreável. Foram reutilizadas
os snapshots necessários, dentro de um inventário de 72 respostas FIPE e cinco
PDFs PBEV, sem nova chamada a essas APIs. A coleta
inicial foi limitada a seis downloads públicos de fabricantes (dois índices
e quatro PDFs), após inventário e orçamento. A rodada documental de largura
acrescentou oito manuais oficiais para oito identidades já integradas; não houve
chamada FIPE ou CarPedia, seleção de veículo novo ou acesso ANP.
Cota restante FIPE/CarPedia desconhecida, não presumida ilimitada.

Revisão visual das páginas oficiais acrescentou atributos individualmente
comprovados para Kwid Zen 2021, up! Move 2019 e Fox Connect 2019:

- Kwid: ficha da coluna Zen informa massa de 779 kg; 758 kg no manual é a versão
  básica sem opcionais e não foi atribuído ao Zen. O comprimento diverge:
  3.679 mm no manual versus 3.680 mm no catálogo. O campo permanece `null` e o
  conflito bloqueia prontidão. ESC não mencionado não se converte em `false`.
- up!: geometria nominal do MPI/MQ200 e cinco lugares comprovados. Não se atribui
  ao Move a massa da versão básica. Dois airbags **frontais** mencionados não
  comprovam o total por versão. ABS/ESC não são inferidos da descrição genérica.
- Fox: intervalos de comprimento, largura, altura livre e massa não foram
  convertidos em médias inventadas. Células comuns do motor/manual são vinculadas
  explicitamente; medidas internas e porta-malas continuam indisponíveis.

Cobertura técnica dos 19 após o replay CarPedia offline e as revisões documentais
de largura com espelhos e segurança: lugares 19; porta-malas 19; comprimento 19;
largura sem espelhos 19; largura com espelhos 10; entre-eixos 19; altura livre 10;
massa 0; potência a gasolina 2; carga 16; airbags 0; ABS 1; ESC 1; espaço interno 0.
ABS e ESC admitidos pertencem ao ID 80. Nenhum inventário completo foi aprovado:
os fatos preliminares do Cruze e a contagem de airbags do Focus são mantidos em
`pending_fields`, fora de `fields`. Ausência de prova continua `null/unavailable`,
nunca `false`.

**IDs 36, 37, 46, 47, 69, 70, 79, 91, 92 e 93 passam Cidade**, com 100% dos
três critérios e geometria nominal expressamente qualificada. Os oito vínculos
novos usam manuais oficiais de Chevrolet, Renault, Citroën, Volkswagen e
Peugeot, por modelo/geração/ano exatos. No C4 Picasso, a mudança oficial de nome
para C4 SpaceTourer em maio de 2018 é registrada explicitamente; não há associação
por semelhança textual. No Peugeot 2008, 1.828 mm é a largura com retrovisores
recolhidos e foi rejeitada; o valor aberto é 2.004 mm. No C4 Picasso, 1.971 mm é
a largura recolhida e foi rejeitada; o valor aberto é 2.117 mm. Largura de
carroceria nunca substitui largura com espelhos.

Espaço/capacidade permanece com 36, 42, 43, 59, 68, 70, 79, 91, 92 e 93.
Trabalho tem os mesmos dez IDs de Cidade apenas no gate acadêmico, porque o TCO
de cenário não satisfaz o custo operacional observado. Família e Estrada
permanecem sem inventário completo após a revisão de aplicabilidade; Aplicativo permanece sem dossiê
pronto. QQ
conserva o conflito entre descrição FIPE Flex e combustível estruturado
gasolina. A aprovação de identidade existente não é revogada nem tomada como
aprovação metodológica. Diferenças entre previews não comprovam eficácia.

O laudo Cruze identifica a configuração Latin NCAP pelo VIN `8AGBB69S0LR100117`
e pela data de produção, sem nomear LT. O ano FIPE não comprova sozinho esse
vínculo: airbags, ABS e ESC permanecem pendentes para o ID 46. A ficha Ford MY2018
mostra ABS/EBD e ESC/TCS em todas as configurações; esses dois campos são
admitidos para o ID 80. A contagem de airbags exige conferir a coluna SE Plus,
pois a extração contém cinco células e quatro títulos sem preservar as mesclagens.
Estrelas de crash test não entram no método.
No caso Ford, o servidor recusou o download direto do PDF com HTTP 403;
o hash registrado vincula uma extração textual normalizada do documento oficial,
não os bytes do PDF. Nenhum dos outros 17 veículos foi promovido
por manual genérico, ano próximo, mercado diferente, item opcional ou semelhança
textual.

## Custos e tempo

Cenário explícito: 1.000 km/mês, gasolina manual R$ 6/l; não é observação ANP.
O combustível calculado é uma estimativa separada, identificada como
`scenario_estimate`, e não entra no total conhecido. Uma derivação de combustível
admissível no TCO requer consumo PBEV e preço ANP com semana, geografia e tipo de
combustível. Nenhum candidato tem essa observação ANP. Nenhum candidato tem custo
observado de manutenção, IPVA, seguro ou depreciação; nenhum tem TCO completo.
Taxas anuais configuráveis, se fornecidas, são projeções, não observações. A
divisão anual/12 ocorre apenas ao derivar o componente mensal, sem alterar o
contrato ou os valores de manutenção existentes. Nenhuma decisão de orçamento
é tomada pelo piloto. Financiamento, estacionamento e pedágio são despesas de
contexto fora do escopo declarado de cinco componentes.

`footprint` é a derivação determinística e versionada
`length_mm × width_with_mirrors_mm ÷ 1.000.000`, em m². Largura de carroceria não
substitui largura com espelhos. `passenger_space` continua indisponível sem
entrepernas traseiro e largura interna medidos; lugares, entre-eixos e dimensões
externas não são usados como aproximação.

A camada acadêmica expõe separadamente `body_footprint_m2`, calculado por
`length_mm × body_width_mm ÷ 1.000.000` e acompanhado pelos hashes das duas
evidências. Esse diagnóstico não é o critério `footprint` v3. O perfil Trabalho
também conserva `operating_cost` em `BRL/month`: apenas seu gate acadêmico pode
usar o TCO do cenário na mesma unidade; o método operacional continua exigindo
combustível e manutenção com evidência aceita.

Os 34 legados têm cache FIPE julho/2026. Somente 30 referências passam a
comparação estrita existente; IDs 9, 15, 19 e 21 permanecem sem preço aceito.
As vinculações de preço antigas não foram revalidadas como identidade de versão.
Nenhum consumo do seed ou `demo_fixture` entra como observação PBEV. Portanto,
o preview legado tem informação de preço apenas e nenhuma prontidão v3.

Plano de alinhamento: reutilizar os 19 preços setembro/2026; preparar até 34
consultas individuais pelos códigos/anos já cacheados, **sem descoberta de
famílias/anos**, após registrar saldo/limites de cota e contrato de mês fixo.
Rejeitar resposta de outro mês, resolver as quatro descrições divergentes por
evidência e preservar os snapshots antigos. Antes disso, nenhuma nova chamada
FIPE foi autorizada pelo gate do piloto e nenhum ranking conjunto é gerado.

## Bloqueios preservados e próximos requisitos

C4 Lounge (48): transmissão; Elantra (50): consumo; Optima (53): sem PBEV
compatível. Permanecem fora dos 19. As substituições Picanto GT (40), Rio EX (45)
e Arrizo 6 GSX (56) têm aprovação humana registrada em `change_control_v2.json`,
sem ativação operacional. QQ 2017 (41) continua com aprovação pendente.
No segundo lote controlado, foram selecionados 11 dos IDs 57–100 depois de uma
fila completa registrada antes do HTTP. O ID 57 foi bloqueado por resposta FIPE
404 no alvo exato e não gerou chamada CarPedia. Os IDs 58, 59, 68, 69, 70, 79,
80, 91, 92 e 93 foram ligados por código FIPE, ano, versão, combustível e
conjunto mecânico exatos, sem similaridade textual. O restante dos IDs 57–100
continua congelado e não preparado.

As dez fichas CarPedia cacheadas acrescentam carroceria, lugares, porta-malas,
carga útil, comprimento, largura da carroceria, entre-eixos, cilindrada,
potência, transmissão, combustível e tanque. Sete também comprovam vão livre.
Nenhuma comprova largura com espelhos, medidas internas de passageiros ou o
inventário completo de segurança. A largura com espelhos dos IDs 46, 47, 69,
70, 79, 91, 92 e 93 vem exclusivamente da revisão documental oficial posterior,
não das fichas CarPedia. A
matriz v3 padrão conserva o lote original, e o segundo lote só entra mediante o
parâmetro explícito `include_batch2=True`. Esse replay não publica, não ativa e
não autoriza ranking operacional.

Próximos insumos necessários: recibo de cota/mês FIPE, identidade legada revisada,
medidas e equipamentos por versão de fontes oficiais, rubrica reproduzível de
custos e aprovação das substituições. CarPedia só poderá complementar dados com
ID externo inequívoco, cota conhecida e no máximo uma consulta cacheada por
identidade; não substitui fonte prioritária nem resolve conflito por similaridade.
Frontend, recomendador, Gold, PostgreSQL, HEAD, tag, stage e stashes não mudam.
