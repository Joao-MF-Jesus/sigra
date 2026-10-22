# API acadêmica da coorte v6

Integração aditiva, com modo explícito `ACADEMIC_COHORT_ENABLED=false` por
padrão. Não habilita Gold, recomendação operacional ou ingestão externa. A
validação complementar SQLite/ASGI não comprova PostgreSQL: os quatro testes
reais precisam executar sem skips em um alvo local dedicado.

## Persistência e contrato

A migration `20261005_0013`, filha de `20260811_0012`, cria apenas:

- `academic.cohort_snapshot`: UUID, versão, fingerprint aprovado, hashes dos
  contratos/módulos, seleção e metadados dos 21 registros fora da seleção;
- `academic.cohort_vehicle`: chave composta `(snapshot_id, catalog_id)`, código
  FIPE único por snapshot, mês individual e evidências canônicas completas;
- `academic.cohort_evaluation`: chave por veículo/perfil/cenário, avaliação
  canônica completa, bloqueios, componentes, natureza, cobertura e proveniência.

Os IDs do catálogo não são chaves estrangeiras de `public.vehicles`. Não há
upsert, aproximação textual ou atualização do cadastro operacional. Os 17
holdouts e os demais quatro excluídos permanecem identificáveis, mas não são
inseridos como selecionados. São 60 veículos e 1.080 avaliações (6 perfis × 3
cenários × 60). Checks impedem `operationally_active` ou `recommended` verdadeiros.

A importação verifica o fingerprint do replay inteiro, unidades/identidades,
60 códigos FIPE distintos e avaliações antes da transação. Um lock transacional
PostgreSQL serializa a mesma coorte. Uma segunda importação audita os registros
e retorna o mesmo snapshot sem escrita. Erros revertem toda a transação. O
downgrade recusa apagar snapshots históricos.

O encoder do JSON de transporte é o mesmo do fingerprint acadêmico: Decimal
como string e modelos Pydantic como objetos JSON. Não usar `default=str` para
exportar modelos; isso transforma evidências em representações textuais e é
rejeitado pelo fingerprint.

## Avaliação, filtros e limites

Rotas em `/api/v1/academic-cohort`:

- `GET /metadata`: versão/fingerprint, cobertura, holdouts e excluídos;
- `GET /vehicles`: `limit` 1–60, `offset` >= 0, filtros opcionais `profile`,
  `scenario`, `fipe_code`, `reference_month`, `max_purchase_price_brl` e
  `max_monthly_tco_brl`; o total continua correto em página vazia;
- `GET /vehicles/{catalog_id}`: identidade, evidências e 18 avaliações;
- `POST /evaluate`: perfil, cenário, snapshot opcional, limites independentes de
  compra e TCO mensal, `limit` 1–60 por grupo comparável.

Perfis: `cidade`, `app`, `trabalho`, `suv` (Espaço/capacidade), `familia`,
`estrada`. Cenários: `low`, `base`, `high`. O avaliador/ranking v4 existente é
reutilizado sobre avaliações congeladas do replay v6. Não há nova fórmula nem
ordenação entre grupos de protocolos/evidências incompatíveis. `eligible_ids`
inclui todos os elegíveis, mesmo quando a resposta apresenta apenas top N por
grupo. Sem filtros: 10/60/10/24/1/1, respectivamente. Resultado sem opções é
vazio e explicado; não há fallback inelegível.

Não são aceitos novos pesos, taxas, quilometragem ou preço de combustível pela
API desta versão: os três cenários aprovados permanecem congelados. Preços de
setembro/outubro de 2026 são individuais. `academic_habitability_proxy` é
explicitamente derivado, nunca espaço interno medido. TCO é estimativa de
cenário, nunca custo observado. Todos os retornos mantêm modo `academic_only`,
`operationally_active=false` e `recommended=false`.

Sem feature flag, rotas retornam 404. Sem PostgreSQL/snapshot compatível,
retornam 503 sanitizado; snapshot/veículo fora da seleção retorna 404. A API não
cria schema nem materializa automaticamente e não oferece fallback SQLite.

## Reproduzir com PostgreSQL local dedicado

Executar na raiz do repositório. Requer PostgreSQL normalmente configurado pelo
projeto, banco local novo terminado em `_test` e credenciais somente no ambiente
do processo. Não usar `sigra_postgresql_demo`, suas credenciais ou seu volume.
Não copiar connection strings para comandos, logs ou arquivos. O script recusa
alvos remotos ou nomes que não terminem em `_test`.

Se a instalação local/role normalmente configurada permitir criação:

```powershell
# PGSERVICE/PGUSER/PGPORT previamente configurados para a instalação local de teste.
# Não forneça senha em argumentos. Confirme que o serviço aponta para localhost.
createdb -h 127.0.0.1 sigra_academic_v6_test
```

Disponibilize `DATA_PLATFORM_TEST_POSTGRESQL_URL` pelo mecanismo seguro habitual
e aponte `SIGRA_ACADEMIC_V6_REPLAY_PATH` para o JSON canônico externo aprovado.
O replay precisa ter fingerprint
`d974f86d2deef3903ac052263c7edc406c5b2c21d794721e5220ed5d99acc05d`.
Não há necessidade de FIPE ou CarPedia para replay/importação.

### Prova real automatizada — banco novo

Execute antes de uma materialização manual. Os testes aplicam `0012 → 0013`,
inserem um sentinel apenas no banco dedicado, executam duas importações, API dos
seis perfis/três cenários, rollback e downgrade defensivo. Preservam todas as
linhas preexistentes em schemas não acadêmicos. O alvo fica disponível para
auditoria; não é apagado automaticamente. Se já houver snapshot, use outro
banco novo dedicado em vez de apagar histórico.

```powershell
if (-not $env:DATA_PLATFORM_TEST_POSTGRESQL_URL) { throw 'Configure o alvo PostgreSQL local _test' }
if (-not $env:SIGRA_ACADEMIC_V6_REPLAY_PATH) { throw 'Informe o replay canônico externo' }
& '.\backend\.venv\Scripts\python.exe' -B -m pytest backend/tests/test_academic_cohort_postgresql.py -q -ra
```

Resultado exigido: **4 passed, zero skips**. Skips não significam aprovação.

### Migration e materialização manual explícita

Para um banco dedicado sem a materialização automática acima:

```powershell
if (-not $env:DATA_PLATFORM_TEST_POSTGRESQL_URL) { throw 'Configure o alvo PostgreSQL local _test' }
if (-not $env:SIGRA_ACADEMIC_V6_REPLAY_PATH) { throw 'Informe o replay canônico externo' }
& '.\backend\.venv\Scripts\python.exe' -B scripts/materialize_academic_cohort_v6.py --allow-local-test --validate-only --replay $env:SIGRA_ACADEMIC_V6_REPLAY_PATH
if ($LASTEXITCODE -ne 0) { throw 'Alvo local/replay rejeitado; não executar migration' }
$previousMigrationUrl = $env:MIGRATION_DATABASE_URL
try {
    $env:MIGRATION_DATABASE_URL = $env:DATA_PLATFORM_TEST_POSTGRESQL_URL
    & '.\backend\.venv\Scripts\python.exe' -B -m alembic -c backend/alembic.ini upgrade 20261005_0013
    if ($LASTEXITCODE -ne 0) { throw 'Migration falhou' }
    & '.\backend\.venv\Scripts\python.exe' -B scripts/materialize_academic_cohort_v6.py --allow-local-test --replay $env:SIGRA_ACADEMIC_V6_REPLAY_PATH
    if ($LASTEXITCODE -ne 0) { throw 'Primeira materialização falhou' }
    & '.\backend\.venv\Scripts\python.exe' -B scripts/materialize_academic_cohort_v6.py --allow-local-test --replay $env:SIGRA_ACADEMIC_V6_REPLAY_PATH
    if ($LASTEXITCODE -ne 0) { throw 'Segunda materialização falhou' }
} finally {
    if ($null -eq $previousMigrationUrl) { Remove-Item Env:MIGRATION_DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:MIGRATION_DATABASE_URL = $previousMigrationUrl }
    $previousMigrationUrl = $null
}
```

### Backend, sem frontend ou ingestão

Depois da migration/materialização, em um terminal dedicado com alvo local de
teste já conferido. Variáveis são apenas deste processo, não persistidas:

```powershell
if (-not $env:DATA_PLATFORM_TEST_POSTGRESQL_URL) { throw 'Configure o alvo PostgreSQL local _test' }
if (-not $env:SIGRA_ACADEMIC_V6_REPLAY_PATH) { throw 'Informe o replay canônico externo' }
& '.\backend\.venv\Scripts\python.exe' -B scripts/materialize_academic_cohort_v6.py --allow-local-test --validate-only --replay $env:SIGRA_ACADEMIC_V6_REPLAY_PATH
if ($LASTEXITCODE -ne 0) { throw 'Alvo local/replay rejeitado; não iniciar backend' }
$previousDatabaseUrl = $env:DATABASE_URL
$previousDatabaseEnv = $env:DATABASE_ENV
$previousAcademicFlag = $env:ACADEMIC_COHORT_ENABLED
$previousFipeFlag = $env:FIPE_AUTO_REFRESH
try {
    $env:DATABASE_URL = $env:DATA_PLATFORM_TEST_POSTGRESQL_URL
    $env:DATABASE_ENV = 'test'
    $env:ACADEMIC_COHORT_ENABLED = 'true'
    $env:FIPE_AUTO_REFRESH = 'false'
    & '.\backend\.venv\Scripts\python.exe' -B -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
} finally {
    foreach ($pair in @(
        @('DATABASE_URL', $previousDatabaseUrl), @('DATABASE_ENV', $previousDatabaseEnv),
        @('ACADEMIC_COHORT_ENABLED', $previousAcademicFlag), @('FIPE_AUTO_REFRESH', $previousFipeFlag)
    )) {
        if ($null -eq $pair[1]) { Remove-Item ('Env:' + $pair[0]) -ErrorAction SilentlyContinue }
        else { Set-Item ('Env:' + $pair[0]) $pair[1] }
    }
    $previousDatabaseUrl = $null
}
```

Outro terminal, consultas read-only e avaliação stateless:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8010/api/v1/academic-cohort/metadata'
Invoke-RestMethod 'http://127.0.0.1:8010/api/v1/academic-cohort/vehicles?limit=20&offset=0'
Invoke-RestMethod 'http://127.0.0.1:8010/api/v1/academic-cohort/vehicles/122'
$request = @{ profile='app'; scenario='base'; limit=10 } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8010/api/v1/academic-cohort/evaluate' -Method Post -ContentType 'application/json' -Body $request
```

Exigir `eligible_count=60` para Aplicativo sem filtros, não 60 itens em top 10.
Consultar os demais perfis com a cobertura real, não promover bloqueados. Não
executar os bootstraps demonstrativos; esta extensão não migrou o banco demo.
