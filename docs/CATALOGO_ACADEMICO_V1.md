# Catálogo acadêmico v1 — revisão individual e ativação controlada

## Estado e limite de uso

Esta implementação não declara 100 automóveis ativos. O lote 35–56 possui
19 dossiês aprovados e três bloqueados individualmente. Aprovação do dossiê,
preparação de pipeline, persistência de teste e publicação operacional são
estados diferentes. A ativação está limitada a bancos descartáveis; não há
publicação ou seed no startup, nem alteração de FIPE/PBEV/ANP/Gold já publicados.

`academic-demo-v1` é uma hipótese experimental, não uma avaliação real de
manutenção, segurança, confiabilidade, conforto ou valor de revenda.

## Identidade: catalog-identity-crosswalk-v1

O inventário `data_platform/catalog/batch1_crosswalk_v1.json` registra por ID:
configuração original, configuração revisada, justificativa, observação FIPE
completa, código/ano/combustível estruturado, linha PBEV, página, linha física,
hash da linha, PDF e snapshot parseado, além das linhas mecânicas aplicáveis.

- `exact_trim_powertrain`: vínculo comercial revisado com motor, transmissão,
  combustível e ciclo compatíveis.
- `shared_powertrain_group`: o PBEV comprova o conjunto mecânico, não o preço
  nem o acabamento comercial. Os acabamentos que o documento realmente cita
  são preservados, inclusive quando não informa acabamento. Todas as linhas
  aplicáveis são verificadas para impedir a omissão de consumo conflitante.
- `versioned_commercial_alias`: apenas aliases do inventário versionado
  `crosswalk_aliases_v1.json`; nenhuma aproximação textual ou fuzzy matching.

Aliases registrados: Palio/Novo Palio, Fiesta/New Fiesta Hatch, Sentra/Novo
Sentra e QQ/NEW QQ. Um alias não dispensa equivalência mecânica.

Revisões da seleção:

- 40 Picanto: EX → GT, ano 2018 mantido. A FIPE observada identifica GT; a
  linha PBEV agrupa EX5/LX5 1.0-12V, A-4, flex. O vínculo limita-se ao
  powertrain, sem renomear o acabamento PBEV para GT.
- 41 QQ Look: 2018 → 2017. O campo estruturado FIPE gasolina e a linha PBEV
  2017 a gasolina coincidem. A palavra Flex na descrição FIPE é preservada
  como inconsistência textual da fonte, nunca usada para sobrepor combustível.
- 45 Rio: LX → EX, ano 2021 mantido. A FIPE não oferece LX 2021 no inventário
  consultado; EX 2021 coincide com o PBEV.
- 56 Arrizo 6: Pro → GSX, ano 2021 mantido. GSX não foi associado a Pro.

Bloqueios individuais:

- 48 C4 Lounge: a célula `M-6` está efetivamente no PDF, não apenas no parser;
  a legenda define M como manual, em conflito com a FIPE automática.
- 50 Elantra: linhas mecânicas aplicáveis têm consumos diferentes, sem chave
  inequívoca que selecione a linha correta.
- 53 Optima: o inventário FIPE contém anos 2014–2016; a evidência PBEV desse
  ciclo anterior não foi auditada nesta execução. Não é ausência global do modelo.

## Parâmetros demonstrativos centralizados

Fonte de verdade: `academic_demo_v1.json`. Entradas complementares não usam
marca, modelo nem o grupo de coleta Cidade/Aplicativo/Trabalho/Família/Estrada/SUV.

- Manutenção: preço registrado × 0,025, arredondado a centavos com
  `Decimal` e `ROUND_HALF_UP`; unidade **BRL/ano**.
- Depreciação: 10% ao ano, hipótese declarada, não estimativa de mercado.
- Confiabilidade, peças, conforto, espaço, segurança e os quatro escores de
  uso: 50/100 uniformes, neutros e **sem evidência observacional**.
- Nível de segmento: 3/5 uniforme, não classificação de qualidade de mercado.
- Afinidade de uso: os mesmos seis usos para antigos e novos no preview;
  nenhum grupo da planilha é convertido em nota ou vantagem de uso.
- Confiança metodológica demonstrativa: 0,25, inferior à referência 0,90 das
  observações. Esses parâmetros não são probabilidades calibradas.

O cálculo de TCO já existente recebe manutenção anual e divide por 12 uma
única vez. O método não altera essa fórmula. A passagem de Decimal para o DTO
numérico legado ocorre somente na fronteira do recomendador existente.

Preço e consumo dos novos candidatos conservam a proveniência FIPE/PBEV.
O preview usa consumo urbano a gasolina explicitamente, sem média flex
inventada. Categoria da seleção é taxonomia informada pelo usuário; não é
um indicador observado. Preço/consumo antigos conservam a proveniência
`legacy-demo-v0`, sem serem promovidos a observações reais por este método.

## Baseline e comparação

`legacy-demo-v0` conserva todos os campos dos 34 registros. O manifesto externo
contém o snapshot original e a projeção dos indicadores complementares para
`catalog-100-academic-demo-v1`. Nenhum UPDATE dos 34 registros é executado.

Os seis rankings de preview são comparados sob R$ 100.000 de orçamento de
aquisição, R$ 1.750/mês, 1.000 km/mês e R$ 6/litro:

1. Legado 34 → acadêmico 34: somente mudança da metodologia complementar.
2. Acadêmico 34 → acadêmico 53: adição dos 19 candidatos e mudança do universo
   usado pela normalização do recomendador.

As posições e deltas são registrados por veículo; 53 no preview não significa
53 ativos no PostgreSQL. A confiança legada retornada pelo recomendador não
substitui o aviso e a confiança da metodologia acadêmica.

## Adapter e persistência

`adapter.prepare_batch` valida as decisões novamente contra o inventário
versionado e os arquivos imutáveis em cache. A resposta v1 da FIPE permanece
original na entrada Bronze. Uma tradução explícita dos nomes dos campos
alimenta o transformador Silver existente; não se fabrica uma resposta v2 HTTP.

`activation.activate_catalog` aceita somente bancos locais terminados em
`_test` (SQLite externo `_test.db` ou memória). Exige manifesto externo
imutável, reconhecimento explícito do caráter demonstrativo e recibos
**já publicados** nas tabelas oficiais Bronze/Silver/Gold. Confere código FIPE,
ano, preço, mês, identidade, veículo Gold, combustível, consumo e hashes PBEV.
Sem esses recibos, falha antes de inserir qualquer veículo.

As únicas escritas são INSERTs dos IDs novos em `vehicles` e um recibo em
`meta.pipeline_run`. A transação PostgreSQL usa advisory lock e protege o
catálogo contra gravação concorrente. Timestamps vêm do banco. O recibo aponta
para o SHA-256 canônico do manifesto, que inclui versão, parâmetros, decisões
e snapshot legado. Repetição exige manifesto e registros idênticos; colisão
de ID/código/ano não é resolvida por sobrescrita. Erro desfaz também o recibo.

Não são criadas tabelas paralelas. As tabelas simplificadas das regressões
SQLite existem exclusivamente em fixtures dos testes e não validam constraints
PostgreSQL nem comprovam publicação dos pipelines.

## Pendências que impedem ativação operacional

- Encadear e comprovar os publishers oficiais com os novos inputs, sem
  apresentar preparação em memória como Bronze/Silver/Gold materializados.
- Executar PostgreSQL descartável com todos os guards, idempotência e rollback.
- Conectar o leitor da versão acadêmica e seu aviso visível à interface antes
  de disponibilizar novos registros. A interface atual não foi modificada;
  ela não pode misturar valores manuais antigos com notas acadêmicas novas.
- Revalidar a projeção e os seis rankings contra o dataset realmente publicado.

O lote 2 e a ativação no banco demo continuam condicionados a essas etapas.
Nenhuma ausência de conexão autoriza fallback para o SQLite operacional.
