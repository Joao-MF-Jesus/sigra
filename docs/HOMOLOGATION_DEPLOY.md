# Homologacao do SIGRA

Este documento prepara a homologacao academica. Ele nao declara que Vercel,
Render ou Supabase ja foram criados, configurados ou validados.

## Arquitetura

```text
Navegador
  -> Vercel: React/Vite em modo demonstrativo
  -> Render: FastAPI persistente e somente leitura
  -> Supabase: PostgreSQL exclusivo da homologacao
```

O frontend usa `VITE_API_URL`. O backend usa `DATABASE_URL` no runtime e pode
usar `MIGRATION_DATABASE_URL` somente nos comandos Alembic. Nenhum secret deve
ser salvo no Git, no `render.yaml`, no `vercel.json` ou nesta documentacao.

## Gate zero

Antes de criar recursos remotos:

1. confirme a branch `deploy/homologation`;
2. confirme working tree limpa e CI verde;
3. revise `.env.homologation.example`;
4. confirme que nenhum banco, `.env` real, token ou relatorio local esta
   rastreado;
5. registre o commit que sera homologado.

## Checkpoint 1: Supabase

Esta etapa exige acao manual no painel:

1. autentique-se no Supabase;
2. crie um projeto exclusivo de homologacao;
3. guarde a senha no gerenciador de secrets, sem cola-la na conversa;
4. obtenha a conexao direta para Alembic e a conexao persistente/pooler para o
   Render;
5. habilite a exigencia de SSL quando disponivel;
6. confirme que o banco esta vazio.

Nao copie o SQLite local para o Supabase. O schema deve nascer exclusivamente
do Alembic:

```powershell
$env:DATABASE_ENV = "homologation"
$env:MIGRATION_DATABASE_URL = "<SQLALCHEMY_URL_DIRETA>"
& ".\.venv-validation\Scripts\python.exe" -m alembic -c backend/alembic.ini upgrade head
& ".\.venv-validation\Scripts\python.exe" -m alembic -c backend/alembic.ini current
```

Primeiro valide o bootstrap sem escrita:

```powershell
$env:DATABASE_URL = "<SQLALCHEMY_URL_RUNTIME>"
& ".\.venv-validation\Scripts\python.exe" scripts/bootstrap_homologation_data.py --dry-run
```

Somente apos revisar o relatorio e confirmar o banco vazio:

```powershell
& ".\.venv-validation\Scripts\python.exe" scripts/bootstrap_homologation_data.py --confirm
```

O bootstrap e versionado como `homologation-demo-v1`. Ele recusa schema fora do
Alembic head, banco nao vazio sem marcador e conteudo divergente em nova
execucao. O relatorio fica em
`dist/validation/homologation-bootstrap-report.json`.

## Checkpoint 2: Render

Esta etapa exige autenticacao e autorizacao manual ao repositorio privado:

1. crie um Blueprint usando o `render.yaml` da raiz;
2. confirme o servico `sigra-api-homolog`;
3. mantenha `autoDeployTrigger: off`;
4. cadastre `DATABASE_URL` no cofre do Render;
5. cadastre `CORS_ALLOWED_ORIGINS` quando a URL final da Vercel existir;
6. revise todas as variaveis nao secretas do Blueprint;
7. nao inicie o deploy sem confirmar o banco migrado e o bootstrap validado.

O Render executa apenas o servidor. Migration e bootstrap sao checkpoints
separados; o startup nunca chama `create_all` nem seed. O plano escolhido deve
ser revisado no painel, pois limites e precos dos provedores podem mudar.

Apos o deploy autorizado, valide:

```text
GET https://<backend>/health
GET https://<backend>/health/database
```

O health nao deve expor URL, usuario ou senha do banco.

## Checkpoint 3: Vercel

Esta etapa exige autenticacao e autorizacao manual ao repositorio privado:

1. importe o mesmo repositorio na Vercel;
2. selecione `frontend` como Root Directory;
3. confirme framework Vite, `npm ci`, `npm run build` e saida `dist`;
4. configure `VITE_API_URL=https://<backend-render>`;
5. configure `VITE_PUBLIC_DEMO_MODE=true`;
6. nao publique ate o backend estar saudavel e o CORS conter a URL final.

O `frontend/vercel.json` mantem o fallback de SPA e cabecalhos basicos. Variaveis
`VITE_*` sao publicas no bundle; portanto nunca devem conter segredo.

## Validacao online

Smoke:

```powershell
$env:SIGRA_BACKEND_URL = "https://<backend-render>"
$env:SIGRA_FRONTEND_URL = "https://<frontend-vercel>"
& ".\.venv-validation\Scripts\python.exe" scripts/smoke_test_homologation.py
```

E2E externo:

```powershell
$env:E2E_EXTERNAL_ENVIRONMENT = "true"
$env:E2E_API_URL = "https://<backend-render>"
$env:PLAYWRIGHT_BASE_URL = "https://<frontend-vercel>"
Set-Location frontend
& "C:\Program Files\nodejs\npm.cmd" run test:e2e
```

Nesse modo o Playwright nao inicia servidor local, nao cria SQLite, nao executa
teardown destrutivo e nao usa credenciais administrativas.

## Evidencias a registrar

- commit e branch;
- URLs publicas sem credenciais;
- revisao Alembic;
- versao `homologation-demo-v1`;
- contagens do bootstrap;
- relatorio do smoke;
- execucao E2E externa;
- deployment IDs de Vercel e Render;
- data, responsavel e plano utilizado.

Somente depois de CI, smoke, E2E e revisao manual verdes a tag
`v0.2.0-homologation` podera ser considerada. Este procedimento nao cria a tag
nem promove a homologacao para producao.
