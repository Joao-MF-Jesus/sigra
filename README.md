# SIGRA - Sistema Inteligente de Gestao e Recomendacao Automotiva

## Estado consolidado em 22/10/2026

O [Preview protegido](https://sigra-neon-preview-ficticio-4k3n5kawz.vercel.app)
da release `sigra-be98bd5b78ce6ddd81592d08` está validado no fluxo básico
por HTTP/API, com dados fictícios e coleta real desligada. Não é produção.
Consulte [instalação, build, proveniência e limites](docs/PREVIEW_VALIDATED_20261022.md).
Essa referência atual prevalece sobre os exemplos demonstrativos históricos de
34 veículos abaixo; o catálogo acadêmico do Preview tem 60 veículos.
Não execute seed, migrations ou bootstrap dos exemplos contra o Preview existente.

O SIGRA e um MVP academico para apoiar usuarios leigos na escolha e gestao de veiculos. O sistema recomenda modelos com base em perfil financeiro, objetivo de uso, orcamento, custo mensal estimado, consumo, manutencao, confiabilidade, disponibilidade de pecas e depreciacao. A plataforma pode ser usada em modo visitante para simulacao livre, sem login obrigatorio.

O recomendador consolidado atende automoveis. O modulo de motocicletas esta em fundacao tecnica, com cadastro, persistencia e interface separados, mas ainda sem algoritmo, pesos ou Nota SIGRA. Um modulo transversal e stateless permite simular e comparar financiamentos informados pelo usuario para carros e motos, sem participar dos rankings.

## Problema

A compra de um veiculo costuma ser analisada apenas pelo preco inicial. Na pratica, a decisao tambem envolve custos recorrentes, manutencao, risco de problemas, consumo e adequacao ao uso real do comprador. O SIGRA organiza esses criterios e apresenta uma recomendacao explicavel.

## Objetivo academico

Demonstrar uma arquitetura funcional de sistema web com:

- API backend documentada.
- Interface web para uso e demonstracao.
- Banco de dados local com 34 veiculos demonstrativos.
- Regra de recomendacao multicriterio e explicavel.
- Fluxo completo de recomendacao, comparacao e registro de custos.
- Area "Meu carro" para cadastrar veiculo proprio, relatar problemas, registrar consumo real e ver alertas preventivos.
- Analise demonstrativa de pecas, fornecedores, compatibilidade e variacao de preco.
- Base preparada para evoluir com dados reais.

## Stack utilizada

- Frontend: React + Vite.
- Backend: FastAPI + Pydantic.
- Banco local/testes rapidos: SQLite.
- Banco de integracao/producao: PostgreSQL 16+ com `psycopg` (baseline local validada no PostgreSQL 18).
- ORM e migrations: SQLAlchemy + Alembic.
- Testes: unittest + FastAPI TestClient + Node Test Runner + Playwright.

## Estrutura principal

```text
backend/
  app/
    main.py              Rotas da API
    config.py            Configuracao segura por ambiente
    database.py          Engines e sessoes SQLite/PostgreSQL
    schemas.py           Validacoes Pydantic
    models.py            Modelos SQLAlchemy
    vehicle_domain.py    Tipos, categorias e enums veiculares
    migrations.py        Migracao idempotente da fundacao de motocicletas
    repository.py        Acesso e conversao de dados
    recommender.py       Regra de recomendacao
    vehicle_history.py   Estatisticas, alertas e ajustes por relatos reais
    parts_analysis.py    Analise de pecas, fornecedores e indice de manutencao
    sample_data.py       Base demonstrativa
    financing/           Simulacao Price compartilhada e independente
  tests/
  alembic/               Migrations versionadas
  alembic.ini
frontend/
  src/
    App.jsx
    api/sigraApi.js
    features/recommendations/  Fluxo modular de recomendacao
    features/motorcycles/      Listagem tecnica sem recomendacao
    features/financing/        Simulacao direta, reversa e comparacao
    styles.css
docs/
```

## Variaveis de ambiente

Exemplos disponiveis:

- `.env.example`
- `frontend/.env.example`

Backend:

```text
DATABASE_URL=sqlite:///./sigra.db
DATABASE_ENV=development
DATABASE_ECHO=false
FINANCING_NEAR_LIMIT_PERCENTAGE=85
```

O caminho SQLite relativo e resolvido a partir da pasta `backend`, e nao da
pasta atual do terminal. Assim, iniciar pela raiz ou por `backend/` usa sempre
`backend/sigra.db`. Uma URL absoluta definida em `DATABASE_URL` continua tendo
prioridade. Bancos antigos encontrados em outros locais nao sao apagados
automaticamente.

Em `production`, PostgreSQL e obrigatorio. SQLite e rejeitado, salvo override
emergencial explicito. Pool, timeout e recycle podem ser configurados pelas
variaveis documentadas no `.env.example`; senhas nunca aparecem nos
healthchecks ou scripts de diagnostico.

Frontend:

```text
VITE_API_URL=http://127.0.0.1:8000
```

## Como rodar o backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API:

- `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`
- Health do banco: `http://127.0.0.1:8000/health/database`
- Documentacao: `http://127.0.0.1:8000/docs`

## Como rodar o frontend

```powershell
cd frontend
npm install
npm run dev
```

Interface em desenvolvimento:

- `http://127.0.0.1:5173`

Para gerar e servir uma versao estatica:

```powershell
cd frontend
npm run build
cd dist
..\..\backend\.venv\Scripts\python.exe -m http.server 4173 --bind 127.0.0.1
```

Interface estatica:

- `http://127.0.0.1:4173`

## Como rodar os testes

Comando oficial, executado a partir da raiz do projeto:

```powershell
python -m unittest discover -s backend/tests -t backend -v
```

O marcador `backend/tests/__init__.py` torna a descoberta reproduzivel e o comando inclui toda a suite: testes gerais, financiamento, motocicletas e regressoes imutaveis. Em Windows, sem Python no `PATH`, use opcionalmente:

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t backend -v
```

Frontend:

```powershell
cd frontend
npm ci
npm test
npm run build
```

E2E local, apos instalar as dependencias e o Chromium:

```powershell
cd frontend
npx playwright install chromium
npm run test:e2e
```

Os E2E sobem backend e frontend nas portas isoladas `8010` e `4183`, usam banco temporario e finalizam os processos ao concluir. Python 3.12 e Node 24 reproduzem as versoes usadas na validacao local e na CI. Consulte `docs/TESTES_E_CI.md`.

## Fluxo de recomendacao

1. Selecione `Automovel` e informe orcamento, limite mensal, uso, prioridade, quilometragem e combustivel.
2. Clique em `Calcular recomendacao`. A tela nao consulta a API durante a digitacao nem ao abrir a pagina.
3. A API retorna a Nota SIGRA, TCO, confianca dos dados, viabilidade e justificativas.
4. Se o perfil mudar, o resultado anterior fica marcado como desatualizado ate um novo calculo.
5. Em falha da API, nenhum veiculo, nota ou TCO ficticio e criado; e possivel tentar novamente.

`Motocicleta` aparece apenas como categoria em desenvolvimento. Ela nao chama o recomendador de automoveis e ainda nao possui resultados.

## Modulo de motocicletas

O CRUD auditável `0.3.1` está disponível em `/motorcycles`. A ficha objetiva, as fontes por grupo, as métricas derivadas e as estimativas econômicas usam estruturas separadas. `motorcycle_data_sources` é a rastreabilidade canônica; campos gerais antigos são preservados no banco, mas aparecem somente dentro de `legacy_data` quando `include_legacy=true`. Cada registro persistido é auditado antes do contrato público. A elegibilidade exibida é somente estrutural. O endpoint reservado `/motorcycles/recommendations` retorna HTTP 501 e nunca produz Nota SIGRA, TCO ou ranking.

Endpoints auxiliares permitem manter fontes auditáveis, promover uma fonte principal e cadastrar somente métricas/estimativas demonstrativas ou não validadas: `GET/POST /motorcycles/{id}/sources`, `PATCH/DELETE /motorcycles/{id}/sources/{source_id}`, `POST /motorcycles/{id}/sources/{source_id}/set-primary`, `GET/POST /motorcycles/{id}/derived-metrics` e `GET/POST /motorcycles/{id}/economic-estimates`. Uma motocicleta pode existir sem métricas, manutenção estimada ou depreciação; ausência nunca vira zero. A cobertura piloto exige fontes de `identity`, `market_price`, `technical_specs` e `consumption`. Manutenção é complementar nesta versão.

Os dados demonstrativos ficam no arquivo de seed e são gerenciados manualmente:

```powershell
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py list
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py insert
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py --rebuild-demo --dry-run
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py --rebuild-demo --confirm
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py normalize-demo --dry-run
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py normalize-demo --confirm-normalization
backend\.venv\Scripts\python.exe scripts\seed_motorcycles.py remove --confirm-demonstration-removal
```

A reconstrução usa a identidade lógica `marca + modelo + versão + ano +
condição`, mostra duplicidades e relacionamentos no dry-run, remove somente
registros demonstrativos e cria um backup em
`backend/backups/pre_demo_rebuild_<timestamp>.db` antes da confirmação. O seed
canônico contém Honda CG 160 Fan, Yamaha NMax 160 ABS, Royal Enfield Himalayan
450 e Honda CB 300F Twister. Duas confirmações consecutivas mantêm essas quatro
identidades sem duplicação e não alteram automóveis ou motocicletas reais.

A coleta piloto ainda não foi realizada. O template sem dados fica em `backend/data/templates/motorcycle_pilot_collection_v1.csv`; valide com `python scripts/validate_motorcycle_pilot_data.py <arquivo.csv>` e simule a importação com `python scripts/import_motorcycle_pilot_data.py <arquivo.csv> --dry-run`.

O contrato da futura implementação está em `docs/MOTORCYCLE_RECOMMENDER_SPEC_V1.md`. O schema atual, a coleta e as fontes estão em `docs/SCHEMA_MOTOCICLETAS_V0_3.md`, `docs/PLANO_COLETA_PILOTO_MOTOCICLETAS.md` e `docs/POLITICA_FONTES_MOTOCICLETAS.md`.

Automóveis e motocicletas permanecem isolados. Todos os fluxos automotivos filtram explicitamente `vehicle_type = car`; `vehicles` continua exclusiva para automóveis nesta etapa. Estratégia ou uso explicitamente inválidos retornam HTTP 422, sem fallback silencioso.

A regressão dos automóveis usa `backend/tests/fixtures/cars_regression_v1.json`: base pequena, imutável, sem banco vivo, FIPE ou rede. Ela congela ranking, notas, status e viabilidade do algoritmo `2.1.2` com pesos `cars-v1`.

## Modulo de financiamento

A aba `Financiamento` oferece simulacao direta, simulacao reversa e comparacao de cenarios para automoveis ou motocicletas. O backend usa `Decimal`, sistema Price e taxa explicitamente informada pelo usuario. Nao existe taxa padrao, consulta bancaria, promessa de credito ou persistencia obrigatoria.

O resultado separa entrada, principal do veiculo, custos adicionais, parcela regular, ultima parcela, total pago, acrescimo do financiamento, custo mensal e desembolso total. Precos manuais, de catalogo e negociados possuem contratos exclusivos. O custo mensal pode vir do TCO automotivo ou ser informado, mas o modulo nao altera o TCO nem soma depreciacao e amortizacao como custos independentes.

Versoes: `financing_module_version=1.0.3`, `calculation_method_version=price-v1.2`, moeda `BRL`. O limite usa a maior parcela exibida no cronograma. Custos financiados acima da capacidade recebem estado de insuficiencia, sem financiamento parcial inventado. A comparacao separa equivalencia de veiculo/preco da equivalencia do contexto mensal. Comprometimento so declara vencedor quando orcamento e custo mensal usam as mesmas bases; os percentuais individuais continuam informativos nos demais casos. O frontend marca resultados alterados como desatualizados e limita a comparacao a 10 cenarios. Consulte `docs/MODULO_FINANCIAMENTO.md`, `docs/FORMULAS_FINANCIAMENTO.md`, `docs/INTEGRACAO_FINANCIAMENTO_TCO.md`, `docs/PLANO_INTEGRACAO_FINANCIAMENTO_RECOMENDADOR.md` e `docs/API_FINANCIAMENTO.md`.

## Contrato versionado de recomendacao

O frontend usa `POST /recommendations?envelope=true`. A resposta inclui:

- `algorithm_version` e `weights_version`;
- `vehicle_type` (`car` nesta versao);
- `data_reference`, nulo quando nao existe referencia temporal confiavel;
- `generated_at` em ISO 8601;
- `has_viable_options`;
- `vehicle_processing` com encontrados, avaliados, ignorados e motivos seguros;
- `recommendations` com `is_best_choice` e `is_best_available_reference`.

Sem `envelope=true`, a rota preserva a lista legada por compatibilidade.

## Nota e confianca

A Nota SIGRA mede compatibilidade com o perfil e determina o ranking. A confianca mede cobertura e qualidade dos dados e permanece informativa: ela nao altera a ordenacao. `decision_score`, quando exibido, recebe o nome `Indice complementar de valor` e nao determina isoladamente o ranking.

## Como gerar pacote limpo para entrega

Use o script abaixo para criar um ZIP sem dependencias locais, banco SQLite, builds, logs, cache, `.git`, `work/` ou `outputs/`.

```powershell
.\scripts\create-clean-package.ps1
```

Opcao multiplataforma com Python:

```powershell
python scripts\create_clean_package.py --output SIGRA-entrega-final.zip
```

Para escolher o nome do arquivo:

```powershell
.\scripts\create-clean-package.ps1 -OutputPath SIGRA-entrega-final.zip
```

O pacote limpo deve conter apenas codigo-fonte, documentacao e arquivos necessarios para instalar e rodar o projeto. Nao inclua `node_modules`, `.venv`, `frontend/dist`, bancos locais ou zips antigos.

Para a banca, envie o arquivo `SIGRA-entrega-final.zip`. Nao envie a pasta completa do ambiente local, pois ela pode conter `.venv`, `node_modules`, `work/`, `outputs/`, banco local e caches.

## Diagnóstico e limpeza controlada

O banco oficial de desenvolvimento é `backend/sigra.db`. Audite o caminho
efetivo, contagens e cópias residuais sem expor credenciais:

```powershell
python scripts/check_database_configuration.py
python scripts/clean_workspace.py --dry-run
python scripts/clean_workspace.py --dry-run --include-legacy-databases
```

A limpeza só remove itens selecionados com `--confirm`. Dependências, `dist`,
ZIPs e backups exigem flags separadas; o banco canônico, código, documentação,
`.env` e o backup mais recente permanecem protegidos por padrão.

O banco legado `sigra.db` da raiz possui uma ação separada. Sua remoção exige
`--confirm --include-legacy-databases`, registra tamanho, hash e data e cria
backup antes de excluir arquivos não vazios. `backend/sigra.db` nunca é
selecionado.

As releases controladas são geradas separadamente:

```powershell
python scripts/build_academic_release.py
python scripts/create_clean_package.py --output dist/technical/SIGRA-revisao-tecnica.zip
```

Ambos os pacotes excluem bancos, backups, dependências, caches, segredos,
artefatos E2E e ZIPs anteriores, e incluem manifesto, relatório e SHA-256.

## Imagens demonstrativas

As imagens dos veiculos ficam em `frontend/public/cars/` e sao ilustrativas, usadas apenas para fins academicos/demonstrativos. Elas podem nao representar exatamente cor, versao ou acabamento do modelo.

Dados, precos, links, pecas e imagens nao substituem cotacao real. Em uma evolucao futura, essas imagens podem ser substituidas por fotos licenciadas, imagens oficiais das montadoras ou integracao com uma API automotiva.

## Banco, Alembic e PostgreSQL

O banco de desenvolvimento oficial é `backend/sigra.db`. Execute
`python scripts/check_database_configuration.py` para ver a URL efetiva, o
caminho resolvido, as contagens, a versão do schema e possíveis bancos SQLite
duplicados. Nenhum banco é apagado automaticamente.

A aplicação aceita SQLite e `postgresql+psycopg`. O SQLite permanece como
padrão local; ambientes publicados devem usar PostgreSQL. O schema PostgreSQL
é criado somente por Alembic:

```powershell
docker compose -f docker-compose.postgres.yml up -d
python -m alembic -c backend/alembic.ini upgrade head
python scripts/check_migration_status.py
```

Exportação e migração auditável:

```powershell
python scripts/export_sqlite_data.py --overwrite
python scripts/validate_database_export.py dist/data-migration/sqlite-export-v1
python scripts/import_postgresql_data.py dist/data-migration/sqlite-export-v1
python scripts/import_postgresql_data.py dist/data-migration/sqlite-export-v1 --confirm-import
python scripts/compare_database_contents.py
```

Consulte `docs/POSTGRESQL_SETUP.md`, `docs/DATABASE_MIGRATION.md` e
`docs/POSTGRESQL_MIGRATION_READINESS.md`. Supabase e deploy continuam somente
preparados e documentados, sem conexão ou publicação nesta etapa.

### Baseline PostgreSQL validada

Validacao local concluida em 23/07/2026:

- Alembic `20260723_0001`, incluindo downgrade/upgrade em banco descartavel;
- 18 tabelas, 435 registros importados e 17 sequences reajustadas;
- SQLite e PostgreSQL equivalentes, sem divergencias;
- 226 testes backend executados com PostgreSQL: 226 aprovados e 0 ignorados;
- `/health` e `/health/database` aprovados sem exposicao de credenciais.

Os relatorios ficam em `dist/validation/` e nao fazem parte dos pacotes.

## Fluxo principal do sistema

1. Visitante abre a plataforma sem login.
2. Visitante informa orcamento, limite mensal, uso principal, quilometragem e combustivel.
3. Sistema calcula recomendacoes.
4. Visitante visualiza ranking, nota, custo mensal e justificativas.
5. Visitante abre ficha tecnica e compara veiculos.
6. Visitante consulta links externos demonstrativos.
7. Usuario faz login para registrar despesas e acompanhar historico.
8. Usuario acessa "Meu carro", cadastra o veiculo proprio e registra problema/consumo real.
9. Sistema calcula estatisticas agregadas por modelo e exibe alertas preventivos.
10. Admin faz login para acompanhar resumo dos dados no painel administrativo.

## Credenciais demonstrativas

O login e opcional para simular recomendacoes. Ele e necessario para registrar despesas e acessar o painel administrativo.

Usuario:

- Email: `usuario@sigra.local`
- Senha: `usuario123`

Admin:

- Email: `admin@sigra.local`
- Senha: `admin123`

## Endpoints principais

- `GET /health`
- `POST /auth/login`
- `GET /vehicles`
- `POST /vehicles`
- `GET /vehicles/compare`
- `POST /recommendations`
- `GET /financing/metadata`
- `POST /financing/simulate`
- `POST /financing/reverse-simulate`
- `POST /financing/compare`
- `GET /online-car-search`
- `GET /expenses`
- `POST /expenses`
- `GET /maintenances`
- `POST /maintenances`
- `GET /user-vehicles`
- `POST /user-vehicles`
- `PATCH /user-vehicles/{id}`
- `DELETE /user-vehicles/{id}`
- `GET /user-vehicles/{id}/history`
- `GET /user-vehicles/{id}/alerts`
- `POST /vehicle-reports`
- `GET /vehicle-reports`
- `POST /fuel-consumption-reports`
- `GET /fuel-consumption-reports`
- `GET /vehicle-statistics`
- `GET /parts`
- `GET /suppliers`
- `GET /parts/{part_id}/prices`
- `GET /vehicles/{vehicle_id}/parts`
- `GET /vehicles/{vehicle_id}/parts-analysis`
- `GET /vehicles/{vehicle_id}/maintenance-index`
- `GET /reports/financial-summary`
- `GET /docs`

## Regra de recomendacao

A regra fica em `backend/app/recommender.py`. Ela usa criterios normalizados de 0 a 100:

- Preco.
- Consumo.
- Custo mensal estimado.
- Aderencia ao perfil de uso.
- Manutencao.
- Confiabilidade.
- Disponibilidade de pecas.
- Depreciacao.

Cada perfil altera os pesos dos criterios. Por exemplo, aplicativo prioriza consumo e custo mensal; familia e estrada priorizam confiabilidade e aderencia ao uso.

O retorno inclui:

- Nota de compatibilidade.
- Custo-beneficio.
- Nota de decisao.
- Status da recomendacao.
- Destaques por categoria, como melhor custo-beneficio, mais economico, mais confiavel e menor custo de manutencao.
- Justificativas textuais.
- Penalidades aplicadas.
- Ajuste por dados reais agregados.
- Analise de pecas e Indice SIGRA de Manutencao.

## Pecas, fornecedores e Indice SIGRA de Manutencao

A etapa atual adiciona uma camada demonstrativa para avaliar facilidade de manutencao. O sistema cadastra pecas importantes, fornecedores, precos por veiculo e compatibilidade de pecas entre modelos.

Tabelas adicionadas:

- `parts`: pecas automotivas.
- `suppliers`: fornecedores demonstrativos.
- `part_prices`: precos por peca, fornecedor e veiculo.
- `vehicle_part_compatibility`: compatibilidade de pecas entre veiculos.

O modulo `backend/app/parts_analysis.py` calcula:

- Menor preco, maior preco e preco medio por peca.
- Variacao percentual entre fornecedores.
- Quantidade de fornecedores.
- Alertas de possivel preco abusivo.
- Score de disponibilidade de fornecedores.
- Score de compatibilidade de pecas.
- Risco de variacao de preco.
- Indice SIGRA de Manutencao, de 0 a 100.

Regra conceitual:

```text
indice_manutencao =
bonus por fornecedores variados
+ bonus por pecas compartilhadas
+ bonus por preco medio baixo
- penalidade por alta variacao de preco
- penalidade por poucos fornecedores
- penalidade por pecas caras
```

Os dados sao demonstrativos. Nao ha scraping real nesta etapa. A finalidade e mostrar como o SIGRA pode proteger usuarios leigos contra manutencao dificil e precos muito acima da media.

## Area Meu carro e dados reais

A area "Meu carro" permite que o usuario cadastrado registre um veiculo proprio e alimente a base com dados reais de uso:

- Km atual e km de compra.
- Uso principal.
- Problemas/ocorrencias por categoria, gravidade, km e custo de reparo.
- Consumo real por tipo de uso e combustivel.

Esses dados sao agregados por modelo em `backend/app/vehicle_history.py` para calcular:

- Quantidade de relatos.
- Categorias mais comuns.
- Km medio dos problemas.
- Custo medio de reparo.
- Consumo real medio.
- Indice de risco.
- Pontos de atencao.

O algoritmo continua baseado em regras, mas agora aplica ajustes simples:

```text
nota_final =
nota_base
- penalidade_por_problemas_recorrentes
- penalidade_por_consumo_real_ruim
- penalidade_por_custo_medio_alto
+ bonus_por_baixa_recorrencia
+ bonus_por_consumo_real_bom
```

Tambem ha alertas preventivos: se o carro do usuario estiver perto da quilometragem em que outros relatos do mesmo modelo ocorreram, o sistema mostra uma recomendacao de revisao preventiva.

## Dados fake adicionados

A carga demonstrativa inclui relatos para testar a defesa sem depender de usuarios reais:

- Honda Fit com relatos de suspensao perto de 100.000 km.
- Chevrolet Onix com relatos de consumo urbano abaixo do esperado e atencao em manutencao.
- Toyota Corolla com baixa frequencia de problemas, mas manutencao mais cara.
- Fiat Mobi com baixo custo e menor conforto/acabamento.
- Toyota Etios com boa confiabilidade e acabamento simples.

Dados demonstrativos de pecas cobrem Chevrolet Onix, Hyundai HB20, Toyota Etios, Honda Fit, Toyota Corolla, Fiat Mobi, Nissan March, Volkswagen Gol, Renault Sandero e Ford Ka.

Para testar rapidamente:

1. Entre com `usuario@sigra.local` / `usuario123`.
2. Abra a aba `Meu carro`.
3. Selecione um veiculo cadastrado.
4. Veja os alertas e estatisticas do modelo.
5. Registre um problema ou consumo real.
6. Volte para `Recomendacao` e recalcule para ver o ajuste por dados reais.

## Homologacao publica

A branch `deploy/homologation` prepara uma demonstracao publica com:

- frontend Vite na Vercel;
- API FastAPI persistente no Render;
- PostgreSQL separado no Supabase;
- `PUBLIC_DEMO_MODE=true`;
- login, dados pessoais e escritas persistentes bloqueados;
- recomendacao e financiamento mantidos como calculos sem estado;
- CORS e hosts configurados explicitamente por ambiente;
- schema criado somente por Alembic;
- seed demonstrativo remoto idempotente e versionado;
- smoke e Playwright externo sem SQLite ou teardown destrutivo.

Os arquivos `render.yaml`, `frontend/vercel.json` e
`.env.homologation.example` nao possuem credenciais reais. Autenticacao nas
plataformas, criacao dos projetos, cadastro de secrets e deploy permanecem
checkpoints manuais.

Runbooks:

- `docs/HOMOLOGATION_DEPLOY.md`
- `docs/HOMOLOGATION_SECURITY.md`
- `docs/HOMOLOGATION_BACKUP_RESTORE.md`
- `docs/HOMOLOGATION_ROLLBACK.md`

O bootstrap remoto deve ser ensaiado sem escrita antes da confirmacao:

```powershell
$env:DATABASE_ENV = "homologation"
$env:DATABASE_URL = "<URL_SQLALCHEMY_DE_RUNTIME>"
& ".\.venv-validation\Scripts\python.exe" scripts/bootstrap_homologation_data.py --dry-run
```

Nenhuma URL real com senha deve ser salva no repositorio ou enviada na conversa.

## Limitacoes conhecidas

- A base de veiculos e demonstrativa.
- A base possui 34 modelos demonstrativos para simular diferentes perfis.
- Os precos e custos nao substituem cotacao real.
- Imagens e links externos sao demonstrativos.
- Os relatos reais ainda usam uma base demonstrativa local.
- Precos de pecas, fornecedores e compatibilidades sao demonstrativos.
- Nao ha scraping real nem cotacao automatica de fornecedores nesta etapa.
- O ajuste por dados reais usa regras simples, nao machine learning.
- Login e simplificado para a defesa/MVP.
- Nao ha senha criptografada nem token real ainda.
- Nao ha integracao oficial com FIPE, seguradoras, oficinas ou marketplaces.
- A simulacao de financiamento nao consulta bancos, nao oferece credito e nao garante aprovacao.
- Apenas o sistema Price esta implementado; SAC e persistencia de propostas sao evolucoes futuras.
- PostgreSQL foi validado localmente; carga, backup/restauração e operação de
  produção ainda exigem ensaios próprios.
- Supabase e deploy público não foram executados.

## Proximos passos

- Integrar dados reais de preco e manutencao.
- Integrar fornecedores reais, APIs ou scraping controlado para precos de pecas.
- Validar compatibilidade de pecas por versao, motor e chassi.
- Criar cadastro completo de usuario.
- Implementar autenticacao real com hash de senha e tokens.
- Salvar multiplos perfis por usuario.
- Melhorar filtros de busca.
- Criar relatorios historicos.
- Evoluir o financiamento com SAC e persistencia opcional de propostas, mantendo rastreabilidade.
- Manter o job PostgreSQL remoto verde e adicionar ensaios de carga e restauração.
- Configurar Supabase manualmente e validar SSL/pooler antes do deploy.
- Publicar somente após o gate de `docs/DEPLOY_READINESS.md`.

## Documentacao de defesa

Arquivos de apoio:

- `docs/ROTEIRO_DEFESA.md`
- `docs/CRITERIOS_RECOMENDACAO.md`
- `docs/LIMITACOES_E_EVOLUCOES.md`
- `docs/CHECKLIST_ENTREGA.md`
