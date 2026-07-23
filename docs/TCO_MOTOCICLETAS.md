# TCO conceitual de motocicletas V1

> Proposta metodológica. Não existe cálculo de TCO de motocicletas implementado.

## Fronteiras do custo

```text
TCO mensal desembolsável =
  combustível
  manutenção preventiva mensalizada
  manutenção corretiva estimada
  pneus mensalizados
  transmissão final mensalizada
  seguro mensalizado
  IPVA e licenciamento mensalizados
  outros consumíveis previstos

Custo econômico mensal =
  TCO mensal desembolsável
  + depreciação mensal estimada
```

- **Aquisição:** preço de compra e despesas de transferência; exibida separadamente.
- **Financiamento:** entrada, juros, tarifas e prazo; simulação separada.
- **Equipamentos pessoais:** capacete, vestuário e proteção; bloco opcional, fora do núcleo inicial.
- **Despesas opcionais:** estacionamento, acessórios, pedágios, multas e custo de oportunidade; não entram sem declaração explícita.

## Componentes candidatos

| Componente | Fórmula candidata e unidade | Periodicidade e campos | Fonte e ausência | Confiança/MVP | Dupla contagem |
|---|---|---|---|---|---|
| combustível | `(km_mês / km_l) * R$/litro` em R$/mês | consumo por contexto, km mensal, combustível | ensaio/metodologia e preço datado; sem consumo não calcular | indispensável ao MVP; confiança por fonte | consumo não recebe bônus paralelo na estratégia |
| preventiva | soma do plano no horizonte / meses em R$/mês | itens, intervalos em km/tempo, preços | manual + preços auditáveis; agregado só com metodologia | MVP se houver cobertura | não somar óleo/pneus já incluídos no agregado |
| corretiva | custo esperado por exposição em R$/mês | falha, frequência, km, severidade e reparo | base histórica suficiente; ausência fica indisponível | futura; confiança crítica | confiabilidade pode alimentar a reserva, não pontuar de novo |
| pneus | `(custo do par / vida_km) * km_mês` | medidas, custo, durabilidade | catálogo/mercado; sem vida útil, omitir e reduzir cobertura | candidata ao MVP ampliado | não incluir também em manutenção agregada |
| transmissão final | `(custo / intervalo_km) * km_mês` | corrente/correia/cardã, kit e intervalo | manual + mercado; desconhecido reduz cobertura | candidata ao MVP | evitar duplicação na preventiva |
| seguro | prêmio anual / 12 em R$/mês | cotação, perfil e região declarados | cotação datada; sem dado, exibir indisponível | futura/regional | não usar proxy genérico como custo real |
| IPVA/licenciamento | obrigação anual / 12 em R$/mês | UF declarada, alíquota, preço e calendário | fonte oficial; sem UF, indisponível | futura/regional | aquisição não inclui tributo recorrente |
| consumíveis | custo por intervalo mensalizado | óleo, filtros e outros itens não cobertos | manual + mercado; lista explícita | decisão pendente | excluir itens já presentes na preventiva |
| depreciação | diferença de preço comparável / meses em R$/mês | série histórica por versão/ano/condição | fonte de mercado datada; sem série, indisponível | custo econômico, não desembolso | preço aparece como base, não como bônus repetido |

## Política de ausência

Não haverá valor padrão inventado. Cada resposta futura deverá informar componentes calculados, indisponíveis, fontes, datas e percentual de cobertura. Um subtotal parcial não poderá ser chamado de TCO completo.

## Decisões pendentes

- horizonte de análise e critérios de comparabilidade de preços;
- separação entre manutenção agregada e itens individualizados;
- fontes regionais de seguro, impostos e peças;
- limiar mínimo de cobertura para comparar TCO;
- tratamento de motos elétricas e custos de energia/bateria;
- inclusão de equipamentos pessoais e custos de aquisição.
