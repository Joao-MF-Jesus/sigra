# Participantes e registros de teste do TCC

## Escopo e separação

A conta existente `users` recebe credenciais opcionais. Cadastros novos são
sempre `participant`; contas legadas sem senha continuam preservadas e inativas
para autenticação. Não existe senha inicial nem seleção de administrador no
cadastro. A sessão opaca fica em cookie HttpOnly/SameSite=Lax; somente o digest
é persistido. Senhas usam PBKDF2-HMAC-SHA256, salt aleatório e 600.000 iterações.

As fórmulas e os motores existentes são chamados sem alterações. Visitantes
continuam simulando sem registro. Participantes usam os endpoints de execução
que calculam no servidor e salvam a resposta efetiva antes de devolver o recibo.
Resultados enviados pelo cliente e IDs de proprietários não são aceitos.

V6 permanece o snapshot padrão aprovado. V7 continua candidata separada e
inativa. Estimativas de cenário, evidências derivadas e critérios indisponíveis
permanecem identificados; o registro não cria notas nem promove dados na Gold.

## API

- `POST /auth/register`: nome, e-mail normalizado e senha (12–256 caracteres).
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- `GET /auth/session`: sessão atual ou `user: null`; sem erro esperado no console
  de visitantes. Respostas pessoais não são cacheáveis.
- `POST /api/v1/test-runs/recommendation`, `/financing`, `/reverse-financing`,
  `/financing-comparison`, `/fuel-simulation`: contratos originais de cálculo.
- `GET /api/v1/test-runs?limit=20&offset=0`: histórico do próprio participante.
- `GET /api/v1/test-runs/{id}`: parâmetros e resposta daquela execução.
- `PATCH /api/v1/test-runs/{id}/feedback`: `rating` inteiro 1–5 e comentário
  opcional até 4.000 caracteres. Não altera parâmetros ou resultado.
- `GET /api/v1/admin/test-runs.csv`: exportação administrativa UTF-8 com BOM,
  escapando fórmulas CSV. Usa `participant_code` HMAC, sem nome/e-mail/ID do
  participante. Requer `SIGRA_RESEARCH_PSEUDONYM_KEY` estável e privada. Texto
  livre pode conter PII: revisar antes de compartilhar; não é anonimização.

Operações mutáveis exigem cookie (exceto cadastro/login) e `X-SIGRA-CSRF: 1`,
com origem autorizada. Nunca envie tokens por query string. Registros de outros
participantes retornam 404; permissão administrativa é verificada no servidor.
Os demais recursos pessoais (`Meu carro`, despesas, manutenção, relatórios)
também são limitados ao proprietário. IDs acadêmicos não viram IDs operacionais.

Cada registro guarda UTC, versão do sistema, método, snapshot quando aplicável,
inputs validados, resultado completo retornado pela API e fingerprints de ambos.
`SIGRA_SYSTEM_VERSION` pode identificar uma entrega; sem ela é calculado um
fingerprint do código backend/frontend carregado. O histórico exibe o resultado
guardado: não recalcula retroativamente. A exportação legada de catálogo exclui
senhas, sessões e registros privados; ela não substitui um backup seguro completo.

## Migration e reversão

Nova revisão: `20261007_0014`, pai `20261005_0013`. Acrescenta três colunas de
autenticação a `users`, `auth_sessions` e `participant_test_runs`, com FKs,
unicidade de e-mail normalizado, índices por proprietário e constraint da nota.
Não toca em veículos, contratos de evidência, academic snapshots ou Gold.

Não houve aplicação ao banco atual nesta implementação. Primeiro provisionar
um banco local NOVO, vazio, chamado `sigra_tcc_<identificador>_test`. Transmitir
sua URL somente por ambiente seguro em `SIGRA_TCC_TEST_DATABASE_URL`. O teste
recusa qualquer outro alvo e qualquer banco já contendo tabelas.

Em um terminal PowerShell exclusivo para testes, na raiz do projeto. A
configuração abaixo isola também as importações da API do banco atual:

```powershell
$repo = (Get-Location).Path
$env:PYTHONPATH = (Join-Path $repo 'backend') + ';' + $repo
$env:DATABASE_ENV = 'test'
$testFile = Join-Path $env:TEMP ('sigra_tcc_' + [guid]::NewGuid().ToString('N') + '_test.sqlite')
$env:DATABASE_URL = 'sqlite:///' + $testFile.Replace('\', '/')
$env:FIPE_AUTO_REFRESH = 'false'
$env:PUBLIC_DEMO_MODE = 'false'
$env:SIGRA_COOKIE_SECURE = 'false'
& '.\backend\.venv\Scripts\python.exe' -m pytest backend/tests/test_participant_trials.py -q -p no:cacheprovider
# Somente após configurar a URL do banco exclusivo no ambiente:
& '.\backend\.venv\Scripts\python.exe' -m pytest backend/tests/test_participant_trials_postgresql.py -q -rs
```

O teste PostgreSQL faz upgrade até 0013, preserva um usuário e um sentinel,
aplica 0014, reverte enquanto não há participantes, reaplica, testa login e
registro, e exige que o downgrade com dados seja bloqueado. O banco de teste é
mantido para auditoria; o operador o remove depois. Skip não comprova PostgreSQL.

Somente numa futura aplicação explicitamente autorizada, com backup seguro,
`MIGRATION_DATABASE_URL` apontando ao alvo escolhido e preflight validado:

```powershell
& '.\backend\.venv\Scripts\python.exe' -m alembic -c backend/alembic.ini current
& '.\backend\.venv\Scripts\python.exe' -m alembic -c backend/alembic.ini upgrade 20261007_0014
# Reversão: somente se a camada estiver vazia; dados de participantes bloqueiam:
& '.\backend\.venv\Scripts\python.exe' -m alembic -c backend/alembic.ini downgrade 20261005_0013
```

Não contorne o downgrade defensivo. Se já houver dados, preservar backup e
planejar uma migration corretiva; não apagar credenciais/histórico para reverter.

## Execução local depois da validação e autorização do alvo

Configuração de exemplo sem segredos: `backend/tcc.env.example`. O exemplo não
é carregado automaticamente. `DATABASE_ENV=integration` evita bootstrap/seed;
`FIPE_AUTO_REFRESH=false` evita atualização externa. `PUBLIC_DEMO_MODE=false`
é necessário para cadastro privado. Em produção usar HTTPS e cookie Secure.
Em HTTP localhost apenas, definir `SIGRA_COOKIE_SECURE=false` no processo.

Backend (URL configurada apenas no ambiente, schema já autorizado em 0014):

```powershell
& '.\backend\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

Frontend, em outro terminal na raiz:

```powershell
$env:VITE_API_URL='http://127.0.0.1:8010'
& 'C:\Program Files\nodejs\npm.cmd' --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Provisionamento opcional de administrador pelo operador, nunca pelo navegador:

```powershell
Push-Location backend
try { & '.\.venv\Scripts\python.exe' -m app.provision_admin --email 'responsavel@example.org' --name 'Responsável' --confirm-admin }
finally { Pop-Location }
```

Executar com backend no PYTHONPATH (por exemplo a partir de `backend`). O comando
confere a migration, exige confirmação explícita e pede senha oculta; nunca
aceita senha por argumento. Não foi executado no banco atual.

## Fluxo e limitações para deploy

Abrir "Acessar recursos pessoais", cadastrar, entrar, calcular recomendação ou
simulação, avaliar o recibo e abrir "Meus testes". Após logout o histórico fica
indisponível. Reiniciar a API não apaga sessões/registros persistidos.

Antes do deploy ainda faltam: prova PostgreSQL de 0014 no alvo descartável,
aplicação autorizada/backup, HTTPS/configuração de CORS/cookies, administrador
provisionado e política de consentimento/retenção/acesso à exportação do TCC.
O limitador de cadastro/login é em memória por worker; para múltiplos workers
usar rate limit compartilhado. Recuperação de senha e verificação de e-mail
não foram incluídas no cadastro simples desta etapa.

Para homologação exclusiva Supabase, consultar `TCC_SUPABASE_HOMOLOGATION.md`.
SameSite é configurável (`SIGRA_COOKIE_SAMESITE`); o padrão continua Lax.
None só é permitido com Secure. A nota geral antiga permanece separada das
quatro questões do instrumento C/D. `TCC_STUDY_PROTOCOL_REVIEW.md` documenta
a migration aditiva 0015, homologação fictícia e decisões acadêmicas pendentes.
O head do código atual é 0015; comandos acima sobre 0014 descrevem a camada
anterior. Não iniciar esta versão com schema antigo nem migrar o banco original.
