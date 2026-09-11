# academic-evidence-v2 — diagnóstico, não ativação

## Decisão e estados independentes

Os 19 dossiês FIPE/PBEV do lote 1 têm somente `identity_approved`. Nenhum é
`methodology_ready`, `source_chain_published`, `postgresql_validated`, `ui_ready`
ou `operationally_active` nesta versão. C4 Lounge, Elantra e Optima conservam
seus bloqueios e evidências. Isso não reclassifica os datasets legados já existentes.

O retorno padrão de `crosswalk.review_batch()` usa `catalog-readiness-v2`.
`approved_for_activation` só aparece com `historical_v1=True`, para reproduzir
o significado histórico do relatório antigo; não é um certificado atual.
`adapter.prepare_batch` aceita identidade revisada para preparação **sem escrita**.
Os defaults de `activation.build_manifest` e `activate_catalog` bloqueiam a
ativação. Mesmo flags de gates forjadas não substituem atestações reais.

## Reprodução histórica

`academic.py`, `academic_demo_v1.json`, seleção, observações, aliases e relatórios
anteriores não foram reescritos. `legacy-demo-v0` e os cálculos v1 conservam seus
valores e fingerprints. Para testes históricos, as funções recebem explicitamente
`historical_v1=True`; a persistência v1 continua limitada a banco descartável.
Esse caminho não é importado pela interface e não é autorização operacional.

Os testes v1 mantêm as mesmas assertions e passam a declarar o modo histórico.
Novos testes verificam a saída atual e a reprodução exata dos dois fingerprints
anteriores: revisão de identidades e seis rankings v1.

## Evidência e ausência

`evidence_v2.EvidenceVehicle` contém `FieldEvidence`, já existente no contrato de
catálogo. Valores desconhecidos são `kind=unavailable, value=null`; não são 50,
zero ou segmento 3. O DTO obrigatório numérico do recomendador operacional não é
preenchido nem alterado.

- Novos 19: preço/mês/identidade FIPE e consumo urbano/rodoviário PBEV validados
  novamente contra os snapshots e hashes. Nenhuma nota da planilha entra na composição.
- Legados 34: somente referência de preço do cache local com metadata `live`,
  código/ano/descrição iguais ao perfil FIPE explícito pode alimentar o diagnóstico.
  Isso não reaudita a identidade comercial/Gold do catálogo. Divergências de texto
  ficam registradas; não se cria alias automaticamente nem se altera o backend.
- Consumo legado `demo_fixture`, notas manuais, manutenção, depreciação e segmento
  antigos não são promovidos a observações. Não há fallback para `SAMPLE_VEHICLES`.
- Não são consultados PostgreSQL, APIs, CarPedia ou Fenabrave por essa análise.

## Rubrica de diagnóstico explícita e ainda não validada

Parâmetros, dimensões, unidades e fórmulas estão em `academic_evidence_v2.json`.
O cenário controlado é 1.000 km/mês, gasolina a R$6/l, limite R$1.750/mês, ciclo
urbano. É idêntico para os seis perfis: não se inventam rotinas de uso individuais.

A composição diagnóstica usa pesos originais iguais, uma **referência de teste**,
não preferências inferidas do usuário. Dimensões: aquisição, consumo, manutenção,
confiabilidade, peças, capacidade de carga em litros, conforto, segurança e
depreciação. Preço e consumo não são somados novamente por um componente TCO.
Litros de porta-malas não viram automaticamente nota de espaço da cabine.

Normalização linear no conjunto fixo é registrada como utilidade analítica,
nunca como medição técnica. Se uma dimensão é constante, não recebe 50: ela
fica sem discriminação e é excluída. Valores ausentes e pesos zero também não
participam. Pesos efetivos são renormalizados somente nos critérios disponíveis
e discriminantes de cada veículo; a soma é 1, ou 0 quando nenhum é utilizável.
A sobra decimal é atribuída de maneira determinística à última dimensão válida.

A nota de preview reconcilia com a soma das contribuições arredondadas. A
pontuação final de recomendação continua `null`. Cobertura ponderada e confiança
são separadas: confiança estatística não calibrada é `null`, não 0,90 inventado.
Baixa cobertura não aumenta nem reduz artificialmente a nota. Comparações entre
subconjuntos diferentes de evidência não constituem recomendação defensável.

## TCO mensal incompleto não é custo zero

As hipóteses v1 de manutenção = 2,5% do preço e depreciação = 10% ao ano não têm
rubrica validada de mercado e foram excluídas da v2. IPVA/seguro fixos também não
foram promovidos a observações. Não se altera `backend/app/tco.py`.

A camada diagnóstica registra por componente: entrada, unidade, fonte, fórmula,
versão, arredondamento e limitação. Combustível é km/mês ÷ consumo observado ×
R$/litro. Manutenção **anual observada**, quando existir, é dividida por 12 uma
única vez. O mesmo rateio é aplicado aos outros componentes anuais documentados.

Se faltar qualquer componente, `monthly_tco_brl=null` e `monthly_viable=null`.
Um gasto parcial de combustível não pode ser chamado de TCO nem comprovar que
o veículo cabe no orçamento. Os valores conhecidos continuam no detalhamento.

## Comparação e sensibilidade

São executados os mesmos algoritmos em três coortes: 34 legados, 19 candidatos
e 53 combinados. Todos os registros aparecem no relatório, inclusive os sem nota.
Os 19 têm preços de setembro/2026; os legados têm cache de julho/2026. A coorte
combinada é bloqueada por referência temporal incompatível, sem atualização implícita.

Para cada perfil/coorte: top 10 diagnóstico, todas as notas e componentes,
ausências, pesos, cobertura e requisitos faltantes. Empates são ordenados por ID
somente para exibição; ID, marca, modelo e grupo de coleta não entram na nota.

- Jaccard: conjunto top 10 expandido para incluir empates na fronteira.
- Kendall tau-b: ordem por score entre IDs comuns, respeitando empates reais.
- Sem ranking ou denominador ordinal zero: resultado `null`, não similaridade zero.
- Sensibilidade: dobra-se isoladamente cada peso original, mantendo dados e coorte.
  Dimensão sem evidência não pode alterar score ou pesos efetivos disponíveis;
  a cobertura pode mudar e isso é mostrado separadamente.

O gate informa colapso e explica sua origem; **não exige seis rankings diferentes**.
Sem atributos específicos e preferências validadas, seis nomes de perfil não
justificam seis recomendações artificiais.

## Substituições pendentes de aprovação humana

`change_control_v2.json`, enriquecido com fontes/hashes pelo relatório, registra:

- Picanto EX 2018 → GT 2018;
- QQ Look 2018 → Look 2017;
- Rio LX 2021 → EX 2021;
- Arrizo 6 Pro 2021 → GSX 2021.

Todos têm `human_approval_required=true`, status `pending`. A descrição FIPE
do QQ contendo Flex é preservada junto ao combustível estruturado gasolina e
PBEV gasolina. A análise técnica não é aprovação humana da troca de seleção.

## Evidência adicional por perfil

- Cidade: dimensões externas, manobrabilidade, segurança e manutenção documentadas.
- Aplicativo: elegibilidade vigente, capacidade de passageiros, manutenção,
  confiabilidade, disponibilidade de peças e conforto documentados.
- Trabalho: carga útil, volume útil e ciclo de trabalho, confiabilidade e manutenção.
- Família: assentos, retenção infantil, bagagem, segurança e conforto documentados.
- Estrada: consumo rodoviário para os legados, frenagem, segurança, conforto e desempenho carregado.
- SUV: altura livre, necessidade de tração, carga útil, espaço e segurança documentados.

Antes de qualquer liberação também faltam TCO completo, rubricas/pesos aprovados,
preços comparáveis temporalmente, decisões humanas de substituição, cadeia de
fontes publicada, PostgreSQL descartável validado e interface ciente de evidência.
O lote 2, Gold operacional e E2E visual não fazem parte desta execução.
