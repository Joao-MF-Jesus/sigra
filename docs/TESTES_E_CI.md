# Testes e integracao continua

## Ambiente reproduzido

A validacao local deste congelamento usou Python `3.12` e Node `24`. A workflow `.github/workflows/quality.yml` fixa as mesmas versoes. Dependencias Python usam `backend/requirements.txt`; dependencias JavaScript e Playwright usam `frontend/package-lock.json`.

## Comandos locais

Execute a partir da raiz:

```powershell
python -m unittest discover -s backend/tests -t backend -v
python -m compileall -q backend/app backend/tests scripts
```

Quando `python` nao estiver no `PATH` no Windows:

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

E2E:

```powershell
cd frontend
npx playwright install chromium
npm run test:e2e
```

Os cinco E2E cobrem navegacao, simulacao direta, resultado stale, comparacao equivalente e supressao do comprometimento entre orcamentos distintos. Backend e frontend usam `8010` e `4183`. O Playwright cria `tmp/` recursivamente e usa um SQLite absoluto `sigra-e2e-<run-id>.db`, diferente por execução; banco, WAL e SHM anteriores do mesmo identificador são removidos antes da suíte. O banco principal nunca é usado.

O backend E2E recebe `CORS_ALLOWED_ORIGINS=http://127.0.0.1:4183` e `FIPE_AUTO_REFRESH=false`. Assim, a origem de teste é liberada sem curinga e o catálogo controlado nasce do seed demonstrativo local, sem consulta obrigatória à internet. O frontend só inicia depois de `/health` responder. O Playwright encerra os web servers ao concluir; capturas, vídeos e traces são retidos apenas em falhas.

As portas podem ser alteradas por `SIGRA_E2E_BACKEND_PORT` e `SIGRA_E2E_FRONTEND_PORT`. `SIGRA_E2E_RUN_ID` permite isolamento explícito entre execuções concorrentes; a suíte continua com um worker.

## GitHub Actions

A workflow `Quality` possui jobs separados:

- `backend-sqlite`: cria uma fonte SQLite descartavel, executa a suite completa,
  valida as fixtures automotiva/financeira, o HTTP 501 de motos e o `compileall`;
- `backend-postgresql`: valida Alembic, importacao, equivalencia e a suite
  completa com a integracao PostgreSQL habilitada;
- `frontend`: `npm ci`, testes, build e auditoria de vulnerabilidades criticas;
- `e2e`: sobe os dois servicos, instala Chromium e executa os smoke tests.
- `package-validation`: gera e valida os dois pacotes sem publicar release;
- `academic-release`: somente manual, gera e publica como artefato a cópia
  acadêmica controlada quando `workflow_dispatch` recebe a opção explícita.

O E2E depende dos jobs unitarios. Diagnosticos do navegador sao publicados por sete dias somente quando a execucao falha. A workflow nao usa segredos e nao realiza deploy.

O arquivo `backend/sigra.db` permanece ignorado e nunca e enviado ao GitHub. Para
que um checkout limpo consiga exercitar exportacao e importacao, os jobs de
backend executam `scripts/bootstrap_ci_sqlite.py` e configuram
`SIGRA_CANONICAL_SQLITE_PATH` para `tmp/sigra-ci-source.db`. Essa fonte contem
somente seeds versionados e uma ficha de contrato ja usada pelos testes. Ela e
descartavel, nao altera o SQLite local e nao substitui a validacao integral da
base canonica realizada no ambiente controlado.

Se a máquina local não possuir o Chromium compatível, `npm run test:e2e` deve informar a ausência do executável. Isso é falha de instalação do navegador, não aprovação nem reprovação dos fluxos. A CI executa `npx playwright install --with-deps chromium` antes dos testes.

## Fixtures congeladas

- `cars_regression_v1.json`: ranking automotivo `2.1.2/cars-v1`;
- `financing_regression_v1.json`: financiamento `1.0.3/price-v1.2`.

Ambas sao locais, imutaveis e independentes de banco vivo ou rede. Uma mudanca intencional de metodologia deve criar nova versao, nunca ajustar silenciosamente o esperado para acomodar regressao.

## Validação do schema de motocicletas 0.3.1

A suíte cobre manutenção ausente/nula/zero/positiva, fontes canônicas, legado
opcional, consistência entre linhas por `record_key`, cobertura piloto de
quatro grupos, grupos complementares, prontidão futura, normalização
demonstrativa, empacotamento, diagnóstico do banco e ausência de dados
fabricados. O frontend verifica o modo técnico, mensagens de ausência,
separação econômica e inexistência de linguagem de ranking.

Ferramentas da coleta piloto:

```powershell
python scripts/validate_motorcycle_pilot_data.py backend/data/templates/motorcycle_pilot_collection_v1.csv
python scripts/import_motorcycle_pilot_data.py backend/data/templates/motorcycle_pilot_collection_v1.csv --dry-run
```

O template vazio é válido e não contém valores inventados. O validador não acessa rede/banco; o dry-run não cria o SQLite. Persistência exige `--confirm-import` e toda a carga é transacional.

Diagnóstico e releases:

```powershell
python scripts/check_database_configuration.py
python scripts/create_clean_package.py
python scripts/build_academic_release.py
```

Os geradores fazem varredura bloqueadora de ambiente real, chaves, tokens e
URLs de banco com credenciais; excluem bancos, dependências, caches, logs,
backups e ZIPs anteriores; e geram manifesto, relatório e SHA-256 reais.

## Estabilização anterior ao PostgreSQL

O comando oficial não depende de `PYTHONPATH`. A baseline deste patch contém
194 testes de backend e 67 testes de frontend. Os 181/66 testes anteriores
permanecem presentes; os novos casos cobrem portabilidade do seed, identidade
lógica, reconstrução transacional, rollback, preservação de registros reais,
diagnóstico de bancos, limpeza controlada e quatro motos demonstrativas
distintas.

Validações operacionais:

```powershell
python scripts/seed_motorcycles.py --rebuild-demo --dry-run
python scripts/check_database_configuration.py
python scripts/clean_workspace.py --dry-run
```

O seed confirmado sempre cria backup antes da escrita. O dry-run da limpeza é
o padrão e não remove dependências, builds, ZIPs ou backups sem flags
específicas.

### Resultado histórico anterior à baseline PostgreSQL

- Node `24.14.1` e npm `11.11.0`;
- backend: 217 testes executados, 213 aprovados e 4 integrações PostgreSQL
  ignoradas por ausência de `TEST_POSTGRESQL_URL`;
- `compileall`: aprovado para `backend/app`, `backend/tests` e `scripts`;
- `npm ci --cache .npm-cache`: o registry foi bloqueado com `EACCES` e o npm
  encerrou com `Exit handler never called`;
- testes Node: 67 aprovados;
- build: não aprovado neste ambiente; `vite` não ficou disponível após o
  `npm ci` incompleto;
- instalação do Chromium: o comando retornou sucesso, mas avisou que as
  dependências do projeto não estavam instaladas;
- E2E: não executado; o script encerrou com `MODULE_NOT_FOUND` para
  `node_modules/playwright/cli.js`;
- PostgreSQL/Alembic local: não executados; não há Docker, `psql` ou Alembic
  instalado no ambiente virtual atual;
- CI remota: workflow revisado, mas não disparado nesta execução local.

A CI continua usando instalação limpa, build e Chromium. O job PostgreSQL usa
um serviço efêmero e é o gate oficial para migrations, importação e regressão
entre bancos.

## Migração de banco

O job `postgresql` usa PostgreSQL 16 efêmero e executa
`test_postgresql_integration.py`. A suíte aplica `downgrade base`, `upgrade
head`, repete o ciclo, importa o export SQLite em transação, compara 18 tabelas
e valida `Numeric/Decimal`, JSON, timezone, CRUD, ranking automotivo e o HTTP
501 das motocicletas.

Comando local:

```powershell
$env:DATABASE_ENV="integration"
$env:DATABASE_URL="postgresql+psycopg:///sigra_test"
$env:PGHOST="127.0.0.1"
$env:PGPORT="5432"
$env:PGUSER="sigra"
$env:PGPASSWORD="<senha-local>"
$env:TEST_POSTGRESQL_URL=$env:DATABASE_URL
python -m unittest discover -s backend/tests -t backend -p "test_postgresql_integration.py" -v
```

Sem `TEST_POSTGRESQL_URL`, os casos aparecem como `skipped`; isso não equivale
a PostgreSQL aprovado. Os testes locais de `test_database_migration.py` cobrem
configuração, rejeição de SQLite em produção, URL sanitizada, foreign keys,
rollback/close de sessão, dinheiro como `Decimal`, manifesto, checksums,
dry-run, alvo não vazio, rollback integral e equivalência do pipeline.

## Baseline PostgreSQL real de 2026-07-23

Ambiente:

- PostgreSQL local 18;
- Python 3.12.13, SQLAlchemy 2.0.36, Alembic 1.14.0 e psycopg 3.2.3;
- Node 24.14.1, npm 11.11.0 e Vite 6.4.3.

Resultados:

- SQLite: 226 executados, 218 aprovados e 8 integrações PostgreSQL ignoradas;
- PostgreSQL habilitado: 226 executados, 226 aprovados e 0 ignorados;
- sentinela PostgreSQL, equivalência de dados e regressão automotiva aprovadas;
- frontend: 67 executados e 67 aprovados;
- build: 42 módulos, JS 240.13 kB e CSS 27.66 kB;
- `compileall`: aprovado;
- Playwright: cinco testes descobertos; execução bloqueada no sandbox por
  `spawn EPERM` e timeout, portanto E2E local não foi declarado aprovado.

A workflow possui jobs separados para SQLite, PostgreSQL, frontend, E2E e
validação dos pacotes. O job PostgreSQL executa Alembic, exportação, dry-run,
importação, comparação, sentinela e suíte completa sem permitir que os testes
de integração sejam ocultados por `skip`.
