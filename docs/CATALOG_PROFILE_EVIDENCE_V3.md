# Piloto metodológico v3 — evidência, não ativação

Contrato: `catalog-profile-evidence-v3`. Escopo: 34 legados, 19 identidades
aprovadas do lote 1. Não há chamada de rede, conexão a banco, endpoint, alteração
de DTO produtivo, nova migration ou ativação neste módulo. A decisão global
continua `BLOCKED_INSUFFICIENT_PROFILE_EVIDENCE`.

## Componentes e reprodução

- `profile_contracts_v3.py`: valores Decimal, unidades e proveniência por campo;
  `null` exige motivo; fontes oficiais não podem ser substituídas por fabricante
  ou CarPedia. Contratos congelados, com propriedades extras proibidas.
- `profile_method_v3.json`: pesos, critérios obrigatórios, escalas absolutas,
  precisão, fórmulas, justificativas e análise de sensibilidade versionadas.
- `profile_sources_v3.json`: revisão explícita por campo de quatro PDFs oficiais,
  com URL, SHA-256, documento, página/linha, data e aplicabilidade por versão.
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
| SUV/espaço | porta-malas 30%, lugares 20%, altura livre 25%, proxy dimensional 25% | porta-malas, lugares e altura livre |

Cobertura ponderada mínima: **80%**, além dos critérios obrigatórios, identidade
aprovada, mês alinhado, rastreabilidade, ausência de conflito e aprovação humana
quando a versão/ano foi substituída. `methodology_ready` é calculado por perfil;
não altera o estado persistente de revisão, não significa eficácia validada,
recomendação defensável, elegibilidade financeira ou autorização de publicação.

Os limites absolutos estão integralmente no JSON: para preferência crescente,
`100 * clamp((x-L)/(U-L), 0, 1)`; decrescente,
`100 * clamp((U-x)/(U-L), 0, 1)`. São hipóteses declaradas do piloto, não estatísticas
da amostra. Sensibilidade: cada peso ×0,5/×2 e ambos os limites ×0,9/×1,1, uma
perturbação por vez. Não se ajustam pesos para obter determinado vencedor.

Segurança exige conjuntamente número total de airbags, ABS e ESC comprovados;
não é nota de crash test. Transmissão só recebe peso positivo após preferência
explícita, sem considerar automático universalmente melhor. Envelope usa largura
com espelhos. Proxy de espaço SUV usa entre-eixos × largura da carroceria, sem
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
adicional foi limitada a seis downloads públicos de fabricantes (dois índices
e quatro PDFs), após inventário e orçamento. Nenhuma consulta ANP ou CarPedia.
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

Cobertura técnica dos 19: lugares 3; porta-malas 1; comprimento 1; largura sem
espelhos 2; largura com espelhos 3; entre-eixos 3; altura livre 2; massa 1;
potência 3; carga 1; airbags 1; ABS 1; ESC 0; espaço interno 0. O relatório
externo registra cobertura e motivos de ausência de todos os campos por veículo.

**Somente ID 36 (up! Move) passa Cidade**, com 100% dos três critérios e geometria
nominal expressamente qualificada. Nenhum candidato passa os outros cinco
perfis. QQ conserva o conflito entre descrição FIPE Flex e combustível estruturado
gasolina. A aprovação de identidade existente não é revogada nem tomada como
aprovação metodológica. Diferenças entre previews não comprovam eficácia.

## Custos e tempo

Cenário explícito: 1.000 km/mês, gasolina manual R$ 6/l; não é observação ANP.
O combustível calculado é uma estimativa separada. Nenhum candidato tem custo
observado de manutenção, IPVA, seguro ou depreciação; nenhum tem TCO completo.
Taxas anuais configuráveis, se fornecidas, são projeções, não observações. A
divisão anual/12 ocorre apenas ao derivar o componente mensal, sem alterar o
contrato ou os valores de manutenção existentes. Nenhuma decisão de orçamento
é tomada pelo piloto. Financiamento, estacionamento e pedágio são despesas de
contexto fora do escopo declarado de cinco componentes.

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
compatível. Permanecem fora dos 19. Picanto GT (40), QQ 2017 (41), Rio EX (45)
e Arrizo 6 GSX (56) continuam substituições com aprovação humana pendente.
IDs 57–100 não foram pesquisados nem preparados.

Próximos insumos necessários: recibo de cota/mês FIPE, identidade legada revisada,
medidas e equipamentos por versão de fontes oficiais, rubrica reproduzível de
custos e aprovação das substituições. CarPedia só poderá complementar dados com
ID externo inequívoco, cota conhecida e no máximo uma consulta cacheada por
identidade; não substitui fonte prioritária nem resolve conflito por similaridade.
Frontend, recomendador, Gold, PostgreSQL, HEAD, tag, stage e stashes não mudam.
