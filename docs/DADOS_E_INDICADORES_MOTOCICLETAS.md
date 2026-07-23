# Dados objetivos e indicadores derivados de motocicletas

## Separação física e semântica

O cadastro técnico não equivale a uma recomendação. A versão `0.3.0` separa quatro responsabilidades:

- `motorcycles`: identidade, mercado, consumo, manutenção agregada e metadados legados;
- `motorcycle_objective_specifications`: especificações técnicas observáveis, com unidades explícitas;
- `motorcycle_derived_metrics`: indicadores calculados ou demonstrativos, sempre acompanhados por status e versão de método.
- `motorcycle_economic_estimates`: estimativas temporais versionadas, como depreciação anual.

`motorcycle_specifications` permanece temporariamente para compatibilidade com bancos `0.1.x`. Em leitura, a ficha objetiva nova tem precedência. Scores legados não definem completude e não são utilizados em decisão.

## Grupos de fontes

`motorcycle_data_sources` registra a evidência por grupo: `identity`, `market_price`, `technical_specs`, `consumption`, `maintenance`, `reliability`, `parts_availability`, `safety_equipment`, `ergonomics`, `taxes`, `insurance` e `derived_metrics`.

Cada grupo aceita fontes complementares e no máximo uma principal. Confiança da fonte mede qualidade da evidência, não qualidade da motocicleta. Campos de origem em `motorcycles` são compatibilidade legada; a fonte de verdade é a coleção agrupada.

## Contrato das métricas derivadas

Uma motocicleta pode existir sem nenhuma métrica. O registro de métrica contém nome controlado, valor numérico ou categórico, status, versão do método, data, confiança, fonte opcional e observações.

Ausência de linha significa indicador não calculado. A criação pública aceita apenas `demonstration` e `unvalidated`. `uncalculated` permanece apenas como enum legado e não deve ser persistido; `calculated` é reservado a serviço interno versionado; `deprecated` é somente leitura. Métricas numéricas usam escala de 0 a 100 e valores finitos.

Dados demonstrativos exigem `method_version` iniciado por `demonstration-` e confiança máxima 50. Dados não validados exigem notas metodológicas ou uma fonte vinculada. Nenhum desses estados entra em decisão nesta etapa.

## Depreciação

`depreciation_rate_annual_percent` pertence a `motorcycle_economic_estimates`, com método, referência temporal, confiança e fonte. Não é especificação técnica, não é calculada automaticamente e não entra no TCO. O campo legado `depreciation_rate` permanece apenas em `legacy_data` quando solicitado.

## Rubricas candidatas

Nenhuma fórmula abaixo está implementada ou aprovada. A escala candidata é 0 a 100, maior é mais favorável, e toda saída futura deverá declarar confiança e versão de método.

| Métrica | Objetivo | Entradas objetivas candidatas | Ausência e método candidato | Validação, subjetividade e versão futura |
|---|---|---|---|---|
| `urban_score` | representar adequação operacional urbana | peso, transmissão, consumo urbano, dimensões futuras, calor e resposta em baixa | não calcular sem cobertura; rubrica por faixas observáveis | especialista e teste de cenários; risco médio; `urban-v1` |
| `road_score` | representar aptidão para estrada leve | potência, torque, autonomia, peso, ABS, ergonomia e proteção futura | separar estrada ocasional de viagem; rubrica técnica | especialista; risco alto por vento/carga; `road-v1` |
| `passenger_comfort_score` | descrever recursos para garupa | carga útil, assento/pedaleiras futuros, suspensão e alças | não inferir conforto só pela categoria; checklist verificável | usuário e especialista; subjetividade alta; `passenger-v1` |
| `luggage_score` | descrever transporte de bagagem | carga útil, compartimento, pontos e acessórios homologados | desconhecido não vira zero; evidências por capacidade | validação de catálogo; risco médio; `luggage-v1` |
| `ergonomics_score` | comparar características ergonômicas gerais | peso, assento, posição futura, largura e alcance futuros | perfil do usuário deve modular explicação, não fabricar encaixe | especialista; subjetividade alta; `ergonomics-v1` |
| `beginner_friendliness_score` | apoiar guardrails para primeira moto | peso/potência derivada, torque, transmissão, assento, ABS, categoria | nunca usar só cilindrada; modelo de regras auditável | instrutor e especialista; risco alto; `beginner-v1` |
| `safety_score` | resumir equipamentos objetivos | ABS/canais, CBS, controle de tração, freios futuros | presença de equipamento não certifica segurança; rubrica de equipamento | especialista; risco de falsa garantia; `safety-equipment-v1` |
| `maintenance_score` | representar previsibilidade/facilidade de manutenção | plano, intervalos, custos, transmissão final e rede futura | separar custo, disponibilidade e confiabilidade | oficina/especialista; risco de sobreposição; `maintenance-v1` |
| `parts_availability_score` | representar disponibilidade de peças | fornecedores, prazo, cobertura regional e compatibilidade | preço de peça não é disponibilidade; índice por cobertura | dados de mercado; alta variação regional; `parts-v1` |
| `reliability_score` | resumir evidência de falhas | relatos suficientes, severidade, recorrência, km e reparo | ausência de relatos é neutra; método estatístico auditável | base ampla/especialista; viés amostral alto; `reliability-v1` |

## Experiência indicada

`recommended_experience` é uma métrica categórica legada (`beginner`, `intermediate`, `experienced`). No futuro, deverá combinar uma faixa derivada explicativa com o resultado de guardrails. Não será um dado objetivo, uma opinião obrigatória nem uma garantia de segurança.

## Regras para dados ausentes e demonstrativos

- ausência permanece `null`, nunca zero;
- ausência de métricas não torna a ficha objetiva incompleta;
- valor demonstrativo usa `metric_status = demonstration` e `method_version = demonstration-v0`;
- dado demonstrativo nunca participa de Nota, ranking ou recomendação;
- nenhuma métrica será oficial sem método versionado, evidência e validação;
- nenhuma métrica real recebe valor nesta fase.
