# SIGRA — setpoint de apresentação do TCC

Data de congelamento: 2026-09-02
Referência oficial: tag anotada `tcc-apresentacao-v1.0.0`
Branch de consolidação: `feature/data-platform-postgresql-demo-gold`
Alembic: único head `20260811_0012`

## Escopo congelado

Este setpoint consolida a experiência de recomendação do SIGRA, a simulação
configurável de custo veicular e a plataforma medalhão local de demonstração.
O ranking histórico permanece a linha de base quando o perfil multifator não é
solicitado. Quando habilitado, o perfil aplica pesos explícitos e um único
cenário do usuário a todos os veículos comparáveis, mantendo a decomposição da
pontuação e os cálculos financeiros no backend com `Decimal`.

A plataforma de dados preserva as responsabilidades das fontes:

- FIPE fornece preço e identidade comercial;
- PBEV fornece consumo e eficiência no contrato oficial; no bootstrap local, a
  ausência dos PDFs oficiais é declarada por `demo_fixture` e
  `official_evidence=false`;
- ANP fornece preços de combustíveis por produto, geografia e semana; no
  bootstrap local, os registros também são explicitamente sintéticos;
- Carpedia é enriquecimento técnico shadow opcional e não substitui
  silenciosamente FIPE, PBEV ou ANP.

A Gold integrada permanece somente leitura para os consumidores e seleciona
apenas um dataset ativo, publicado, aprovado, não invalidado e sem revisão
manual. O conjunto congelado contém 18 veículos e 54 cenários publicados na
view `gold.integrated_vehicle_cost_consumption_v1`. O dataset ativo é
`integrated-cost-v1-5f90dc69df1da4bf8b0b-b8bad176`, com fingerprint
`5f90dc69df1da4bf8b0bc5f790d36512fddc49c26b360b486e873dac5ae6598a`.

## Contratos preservados

- A simulação é stateless e não persiste preferências nem resultados.
- `mixed_1000_v1` é somente baseline analítico, nunca perfil imposto.
- Identidade Gold ausente ou ambígua é indisponível, sem associação automática
  ou nota zero inventada.
- O frontend não duplica fórmulas financeiras e não recebe segredos.
- CarPedia real depende de `CARPEDIA_API_KEY`, lida apenas pelo backend. O TCC
  e o bootstrap demonstrativo funcionam sem acesso à API externa da Carpedia.
- Nenhum token, senha ou URL autenticada operacional integra este setpoint.
- Frontend V2 não integra este setpoint e não foi iniciado nesta consolidação.

## Estado da arquitetura e do banco

A migration PostgreSQL-only `20260811_0012`, filha de `20260811_0011`, reforça
a linhagem CarPedia entre mapping, Silver e Gold. Ela mantém histórico por
decisão de mapeamento, adiciona constraint e trigger de coerência, valida a
linhagem antes da publicação e preserva downgrade defensivo. SQLite permanece
no-op. Nenhuma migration anterior foi reescrita.

O database gate aprovado verificou:

- PostgreSQL saudável e Alembic `20260811_0012` antes e depois do gate;
- catálogo com 34 veículos e 34 IDs distintos;
- exatamente um dataset ativo e válido para FIPE, PBEV, ANP e Gold integrada;
- FIPE Bronze/Gold com 34 registros, PBEV Silver/Gold com 18, ANP Silver com 3
  produtos e Gold com 6 snapshots;
- 29 hard gates aprovados e 7 controles estatísticos não calibrados;
- endpoints de saúde, catálogo e Gold integrada retornando HTTP 200;
- paginação separando `total_count` dos itens Pydantic estritos, inclusive em
  página vazia;
- 20 testes PostgreSQL CarPedia aprovados, sem falhas, erros ou skips;
- container, banco, volume e dados demonstrativos preservados.

Evidência primária: `tcc-database-gate-20260902T145750557Z.json`, SHA-256
`FCA5FFB92173BCF1D8C1EF8D861C023E7F25FAC7AB17BB7CCFD2B7FD9DB42EF1`.

## Validações do código congelado

| Validação | Resultado |
|---|---:|
| Focais de linhagem, bootstrap e paginação | 49 passed |
| Plataforma de dados | 335 passed, 17 skips condicionais |
| Backend | 278 passed, 8 skips condicionais |
| Frontend | 95 passed, 0 failed, 0 skipped |
| Build Vite | aprovado, 48 módulos |
| Python compileall | aprovado |
| Alembic heads | `20260811_0012` único |
| `git diff --check` | aprovado |

Os skips locais são condicionais a integrações ambientais; a validação
PostgreSQL dedicada executou sem skips. A execução inicial das suítes locais foi
repetida com diretórios temporários e SQLite isolados para eliminar interferência
do sandbox, sem alteração funcional.

## Artefatos externos e recuperação

Os dumps e relatórios ficam fora do repositório em
`SIGRA-setpoints/TCC-2026-09-02`. O dump anterior à 0012 tem SHA-256
`50A52442EC0306A625F5328CAED2440743873E89C670282B19D5E48535822338`; o
dump final tem SHA-256
`D345614B5C7C32DAA5A5DEFF079D4EA270E7A65D1EB492C8C59F56ADBDD86E58`.
Ambos foram validados pelo database gate com `pg_restore --list`.

O pacote fonte deve ser obtido exclusivamente da tag anotada
`tcc-apresentacao-v1.0.0`. O ZIP de `git archive`, o bundle Git, o manifesto e
`SHA256SUMS.txt` são artefatos externos derivados dessa referência. Para
recuperação sem remoto, valide primeiro o bundle e então clone/restaure a tag;
para recuperação de dados, valide o hash do dump escolhido antes de usar
`pg_restore` em infraestrutura descartável ou expressamente autorizada.

## Roteiro operacional da demonstração

1. Manter Docker/PostgreSQL local previamente validado e as credenciais apenas
   no ambiente seguro da sessão.
2. Confirmar Alembic `20260811_0012` e executar o bootstrap somente com
   `--acknowledge-synthetic-demo` quando uma rematerialização for autorizada.
3. Executar `scripts/bootstrap_postgresql_demo_gold.py --validate-only` para
   confirmar catálogo, fontes, gates e view sem escrita.
4. Iniciar o backend local na porta 8010 e o frontend Vite na porta 5173 apenas
   depois da validação da Gold integrada.
5. Demonstrar a jornada perfil → ranking → detalhes → simulação, deixando
   visíveis origem, limitações e casos indisponíveis.

## Limites assumidos e evolução futura

PBEV e ANP demonstrativos não são evidência oficial; CarPedia externa não é
consultada sem configuração explícita e autorização compatível com seus termos.
Os sete controles estatísticos permanecem `not_calibrated`. Financiamento, BI,
persistência de preferências, promoção operacional da Gold, ingestão massiva
CarPedia e Frontend V2 permanecem fora do setpoint. Qualquer evolução deve partir
da tag oficial e preservar o baseline, os gates e a proveniência já congelados.
