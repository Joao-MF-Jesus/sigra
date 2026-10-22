# Revision6: integração explícita, inativa e restrita à homologação

A proposta anterior foi aplicada como quatro adições exatas. O documento
`ACADEMIC_SAFETY_REVISION6_INTEGRATION.md` registra a etapa histórica de proposta
somente leitura; este guia descreve o importador e a leitura adicionados depois.
Não altera `contracts.validate_replay`, o fingerprint V6 aprovado ou o catálogo.

## Estados e fronteiras

- V6 aprovado: fingerprint
  `d974f86d2deef3903ac052263c7edc406c5b2c21d794721e5220ed5d99acc05d`.
- Revision6: fingerprint
  `55ab70a71119e31d0f2654f14d207daa1ab2481a0b33b568ca7066fd8f1b6a34`.
- ZIP de integração reproduzido: SHA-256
  `975dc4602f1920569615cb509f0d89b8ad327131cc49c6961f400cacc7fce4af`.
- A candidata não está aprovada, ativa ou publicada. Atividade operacional e
  recomendação operacional continuam falsas, inclusive por constraints no banco.
- Meta histórica dez: não atingida. Aceite de nove pelo usuário: decisão de
  escopo, não mudança metodológica, nem autorização para coleta real.
- Cidade 10, Aplicativo 60, Trabalho 10, Espaço 24, Família 9, Estrada 9 em
  baixo/base/alto. IDs de segurança: 31, 34, 44, 55, 62, 76, 80, 108 e 124.
- Tiguan 70 continua desconhecido. Fiesta 44 mantém ESC explicitamente ausente
  e índice inferior. Cruze: 1.807 mm corporal, 2.042 mm entre retrovisores;
  dimensões nominais não comprovam equipamentos LT. Conflitos Rio/Kicks preservados.
- Não incorpora automaticamente o experimento de altura livre ou outra revisão.

O importador existente continua exclusivamente V6. O novo importador reexecuta
o pacote fixado, valida todos os dados antes de conectar, insere outro UUID de
snapshot e verifica os 60 veículos/1.080 avaliações com proveniência completa.
Importações repetidas apenas auditam e retornam `already_materialized`; dados
adulterados bloqueiam, sem corrigir ou sobrescrever o banco silenciosamente.

`SIGRA_REVISION6_HOMOLOGATION_ENABLED` é falso por padrão. Sem a flag, a fábrica
e as leituras continuam no V6 aprovado. Com a flag, somente o fingerprint e a
versão Revision6 são consultados; não existe fallback para o V6 nem mistura por ID.
O motor de recomendação permanece o existente e recalcula pelas preferências
do usuário. A cobertura esperada vem do serviço selecionado, não de um relaxamento
do contrato V6. IDs acadêmicos continuam sem associação a `public.vehicles`.

## Infraestrutura necessária — não substituir por banco existente

O caminho local original continua restrito a **PostgreSQL local novo**, com:

- Banco exato `sigra_revision6_homologation_test`, vazio antes de preparar.
- Owner `sigra_revision6_owner` e runtime `sigra_revision6_runtime`, ambos LOGIN,
  sem superuser, BYPASSRLS, CREATEDB ou CREATEROLE; runtime sem memberships.
- URLs distintas, mesmo host loopback/porta/banco, fornecidas somente no processo
  por mecanismo seguro. Nunca enviar URL autenticada a relatórios ou argumentos.
- `DATABASE_ENV=integration`, confirmação do nome e `fictitious_only` explícitos.
- Recibo externo da preparação com OID do banco; reuso de outro destino/OID bloqueia.

O banco e as roles devem ser provisionados pelo responsável; o script não cria,
apaga ou recria bancos. Não usar `sigra_postgresql_demo`, `sigra_academic_v6_test`,
SQLite legado ou outro banco existente. Um destino remoto exige a confirmação
específica descrita abaixo; não existe liberação genérica de hosts remotos nem
reutilização do guard Supabase antigo.

O exemplo `backend/revision6.homologation.env.example` não tem segredos nem é
carregado automaticamente. Variáveis de conexão necessárias:
`SIGRA_REVISION6_MIGRATION_URL`, `SIGRA_REVISION6_RUNTIME_URL` e `DATABASE_URL`
(runtime, quando a API for iniciada). Configuração não secreta:
`SIGRA_REVISION6_CONFIRM_DATABASE`, `SIGRA_REVISION6_PARTICIPANTS`, `DATABASE_ENV`,
`SIGRA_REVISION6_BUNDLE`, `SIGRA_REVISION6_DECISION`, `SIGRA_REVISION6_TARGET_PROOF`.
A chave `SIGRA_RESEARCH_PSEUDONYM_KEY` é privada e estável, com ao menos 32 bytes.

## Comandos revisáveis

Executar no checkout real, em **novo terminal**, sem alterar o processo atual:

```powershell
$python = (Resolve-Path -LiteralPath '.venv-validation\Scripts\python.exe').Path
$bundle = 'CAMINHO_ABSOLUTO_DA_EXTRACAO\SIGRA_Seguranca_V6_Revision6'
$decision = 'CAMINHO_ABSOLUTO\user-decision.json'
$proof = 'CAMINHO_ABSOLUTO_FORA_DO_CHECKOUT\revision6-target-proof.json'
& $python -B scripts/homologate_safety_revision6.py validate --bundle $bundle --decision $decision --proof $proof
```

`validate` reexecuta somente o código/evidências, sem abrir banco. Seu sucesso
não significa PostgreSQL homologado; informa separadamente a configuração do alvo.
Depois de provisionar o destino novo e injetar as variáveis de forma privada:

```powershell
$env:DATABASE_ENV='integration'
$env:SIGRA_REVISION6_CONFIRM_DATABASE='sigra_revision6_homologation_test'
$env:SIGRA_REVISION6_PARTICIPANTS='fictitious_only'
$env:SIGRA_TCC_COLLECTION_MODE='homologation'
$env:SIGRA_COOKIE_SECURE='false' # somente HTTP local; não reutilizar em deploy
$env:SIGRA_COOKIE_SAMESITE='lax'
$env:CORS_ALLOWED_ORIGINS='http://127.0.0.1:14185'
& $python -B scripts/homologate_safety_revision6.py prepare-new-database --bundle $bundle --decision $decision --proof $proof
& $python -B scripts/homologate_safety_revision6.py materialize --bundle $bundle --decision $decision --proof $proof
& $python -B scripts/homologate_safety_revision6.py serve --bundle $bundle --decision $decision --proof $proof --port 8011
```

`prepare-new-database` recusa qualquer relação preexistente antes de DDL; aplica
a cadeia Alembic até `20261007_0015`, configura grants/RLS e materializa V6
histórico e Revision6 separadamente. Não é chamado por `validate` ou `serve`.
O schema `20261005_0013` já admite versões isoladas; nenhuma nova migration ou
alteração das migrations anteriores é necessária nesta integração.
Se houver falha parcial da preparação, preservar o destino e diagnosticar;
não apagar/recriar nem repetir migrations por suposição. O recibo não é sobrescrito.

O runtime só lê `academic`. RLS forçada fecha acesso público às dez tabelas
pessoais; a role de serviço permanece confiável e **não identifica um
participante**. Isolamento individual continua sendo validado no FastAPI por
usuário autenticado; RLS de role de serviço não substitui esses testes.

Para frontend, reutilizar o código atual com `VITE_API_URL=http://127.0.0.1:8011`
em outro terminal. Exemplo se a porta 14185 estiver livre:

```powershell
$env:VITE_API_URL='http://127.0.0.1:8011'
npm --prefix frontend run dev -- --host 127.0.0.1 --port 14185 --strictPort
```

Configurar CORS com essa origem exata antes de iniciar a API. HTTP/cookie não
secure é exclusivo do teste local. Não reiniciar nem encerrar processos existentes.
Para encerrar, usar Ctrl+C somente nos terminais que iniciaram estes serviços.

## Validação PostgreSQL e navegador ainda necessária

Executar a suíte dedicada somente depois da preparação e confirmação do alvo:

```powershell
$env:SIGRA_REVISION6_POSTGRESQL_TEST_APPROVAL='sigra_revision6_homologation_test'
$env:SIGRA_REVISION6_HOMOLOGATION_ENABLED='true'
$env:SIGRA_REVISION6_BUNDLE=$bundle
$env:SIGRA_REVISION6_DECISION=$decision
$env:SIGRA_REVISION6_TARGET_PROOF=$proof
$env:PYTHONPATH="$PWD\backend;$PWD"
& $python -B -m pytest backend/tests/test_revision6_postgresql.py -q -p no:cacheprovider
```

A suíte não usa SQLite nem migra um alvo desconhecido; requer o recibo, as URLs
dedicadas e a confirmação separada. Deixa contas/registros fictícios auditáveis.
Testes de reconexão de Session/engine não comprovam um reinício real da API.

No navegador: cadastrar conta fictícia `.test`/`.invalid`, login, recomendação
Família/Estrada nos três cenários, respostas, histórico privado, outra conta sem
acesso ao registro, Ctrl+C no terminal da nova API e novo `serve`, verificar
histórico persistido e logout. Exportação requer administrador provisionado pelo
operador e deve permanecer pseudonimizada. Cadastro não permite escolher admin.
Endereços devem usar `.test`/`.invalid`. Essa proteção não identifica pessoas por
si só: usar exclusivamente participantes e nomes fictícios, conforme o aviso de
homologação. Coleta real permanece bloqueada e sem aprovação acadêmica.

## Reversão e deploy

Desabilitar a flag em um processo V6 próprio reverte a seleção; não apagar snapshots
ou registros. O downgrade antigo de `0013` recusa dados históricos, como antes.
Nenhum deploy foi executado. Ainda dependem de homologação real: persistência e
reinício da API, isolamento por participante, grants/RLS efetivos e exportação.
Para publicação: aprovação acadêmica de consentimento/retenção, destinos React/
FastAPI/PostgreSQL, TLS, HTTPS, cookies seguros, CORS, administrador, backup e
restauração, e autorização explícita. A candidata continua inativa até revisão.

## Preparação Supabase das configurações Base/Ampliada — 09/10/2026

Esta seção é aditiva. O guard local, a cadeia Alembic e os fingerprints acima
permanecem. Não usar `prepare_tcc_supabase.py`: seu ciclo histórico de downgrades
não é autorizado nesta homologação Revision6. O novo caminho só faz upgrade até
`20261007_0015`; não cria outra cadeia pelo Supabase, reset ou downgrade.

O projeto precisa corresponder exatamente a `sigra-tcc-homologacao` na organização
`Joao-MF-Jesus's Org` (`tzsztlsmvmxwaypzslzr`) e estar `ACTIVE_HEALTHY`.
Os projetos `zvuludzvdbxedhtrbqmy` e `ibsvxajuyvzszvgluqtx` são sempre rejeitados.
Não existe um Project Ref presumido no código. Sem confirmação real, não conectar.

### Identidade externa e certificado

Depois de confirmar acesso ao projeto pelo `get_project` da integração, preservar
fora do checkout uma resposta **não secreta** contendo id, organization_id, name,
status e database.host reais. Não enviar senhas/chaves/URLs autenticadas ao script.
`confirm_revision6_supabase_target.py` extrai somente esses identificadores,
valida o nome/organização/ref/endpoint e produz um recibo externo com hash da CA.
O comando offline não consulta a API e não substitui a confirmação do operador.

```powershell
# Somente após get_project confirmado; variáveis abaixo não são credenciais.
& $python -B scripts/confirm_revision6_supabase_target.py --project-response $projectResponse --confirm-project $projectRef --ca $ca --output $confirmation
```

Definir no processo `SIGRA_REVISION6_TARGET_KIND=supabase`,
`SIGRA_REVISION6_CONFIRM_PROJECT` (ref real),
`SIGRA_REVISION6_PROJECT_CONFIRMATION` (caminho absoluto externo) e
`SIGRA_REVISION6_PROJECT_CONFIRMATION_SHA256` (SHA-256 emitido).
O recibo não pode ser sobrescrito. Mudança de projeto, banco, roles, CA ou hash
exige nova confirmação explícita; não aceitar um recibo de outro destino/OID.

As duas URLs privadas continuam nas variáveis migration/runtime existentes;
a terceira variável preserva a chave de pseudonimização. Migration/runtime usam
o mesmo endpoint pinado (direto, ou sessão explicitamente confirmada abaixo), banco exato
`sigra_revision6_homologation_test` e usuários exatos `sigra_revision6_owner` /
`sigra_revision6_runtime`. Ambas exigem `sslmode=verify-full` e `sslrootcert`
absoluto fora do checkout. O parser verifica o CA e seu período de validade;
psycopg/libpq verifica CA e hostname no handshake real. O preflight confere TLS
efetivo no driver. No modo direto exige também TLS em `pg_stat_ssl`; no modo
sessão pinado registra separadamente o trecho pooler→PostgreSQL, que não é o
handshake cliente→pooler. Um teste offline de CA não comprova handshake.

Na preparação inicial o pooler era rejeitado: ainda não havia endpoint de Connect confirmado.
A documentação oficial descreve conexão direta no Free por IPv6, session pooler
por IPv4 e username de role customizada com ref. Se a rede não alcançar IPv6,
isso é uma pendência de infraestrutura; não comprar add-on nem liberar poolers
genericamente. O suporte de sessão agora exige o recibo específico descrito abaixo.

Fontes oficiais consultadas:
- [Conexões PostgreSQL](https://supabase.com/docs/guides/database/connecting-to-postgres).
- [TLS/CA/verify-full](https://supabase.com/docs/guides/platform/ssl-enforcement).
- [Banco customizado e limites do Dashboard](https://supabase.com/docs/guides/troubleshooting/manually-created-databases-are-not-visible-in-the-supabase-dashboard-4415aa).
- [Changelog](https://supabase.com/changelog); nenhum SDK Supabase/Auth é introduzido.

O banco customizado não é o `postgres` gerenciado do painel. React/FastAPI usam
PostgreSQL diretamente, não Supabase Auth/Data API. Não interpretar a ausência
do banco customizado no Dashboard como ausência dos dados; auditar pelo SQL.

### Provisionamento revisável e sem segredos

Somente um operador autorizado no **projeto novo confirmado**, após comprovar
que os nomes ainda não existem, poderá executar os comandos abaixo. Eles NÃO
são idempotentes por design: um nome existente exige diagnóstico, não reutilização.
Nada disso foi executado na preparação offline.

```sql
CREATE ROLE sigra_revision6_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE sigra_revision6_runtime LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE DATABASE sigra_revision6_homologation_test OWNER sigra_revision6_owner;
```

Definir senhas localmente por interação oculta (por exemplo `\password <role>`
no psql), sem argumentos, mensagens ou arquivos versionados. CREATE DATABASE
fica fora de transação. Privilégios administrativos do operador não são copiados
às duas roles. Não usar a credencial de operador como URL de migration/runtime.
Se o serviço não permitir esse provisionamento, registrar a permissão concreta
faltante e parar; não alterar banco/role esperados para contornar o contrato.

### Ordem dos comandos de homologação

Injetar as variáveis privadas no novo terminal pelo mecanismo local seguro.
Preservar a mesma `SIGRA_RESEARCH_PSEUDONYM_KEY` entre reinícios; os helpers não
geram nem rotacionam essa chave. Configurar as variáveis não secretas do exemplo.
O `validate` é offline; `preflight` abre apenas transações read-only.

```powershell
$env:SIGRA_REVISION6_TARGET_KIND='supabase'
& $python -B scripts/homologate_safety_revision6.py validate --bundle $bundle --decision $decision --proof $proof
& $python -B scripts/homologate_safety_revision6.py preflight --bundle $bundle --decision $decision --proof $proof
# Somente após preflight aprovado, destino novo/vazio e ambas as roles verificadas:
& $python -B scripts/homologate_safety_revision6.py prepare-new-database --bundle $bundle --decision $decision --proof $proof
& $python -B scripts/homologate_safety_revision6.py audit --bundle $bundle --decision $decision --proof $proof
& $python -B scripts/homologate_safety_revision6.py materialize --bundle $bundle --decision $decision --proof $proof
```

Verificar `$LASTEXITCODE` depois de cada comando; não continuar se diferente de
zero. A repetição de materialização deve auditar `already_materialized`, não
duplicar ou reparar dados silenciosamente. O recibo agora vincula ref, endpoint,
CA, hash da confirmação e OID do banco. Nunca repetir preparação em falha parcial.
O engine da API é ligado explicitamente ao runtime validado antes do FastAPI;
alterar somente o ambiente não retargeta um engine criado durante imports.

O rótulo histórico `homologation_write_scope=new_dedicated_local_test_only`
permanece nos metadados pinados para preservar sua reprodução. Não é o guard de
conexão: a autorização remota agora depende separadamente da confirmação explícita
e do recibo vinculado ao destino/OID; esse rótulo não libera nenhum endpoint.

Grants/RLS protegem as dez tabelas pessoais e revogam PUBLIC/anon/authenticated
somente nos schemas SIGRA. Runtime lê academic, não escreve academic/Gold, não
possui tabelas, memberships, replicação, CREATE de schema/banco nem objetos
temporários. CONNECT é concedido explicitamente no banco dedicado; nenhum outro
banco é alterado. Views também entram na auditoria
de grants. RLS é de role de serviço; isolamento individual continua no FastAPI.

Executar os quatro testes existentes e os dois novos testes da matriz configurada:

```powershell
$env:SIGRA_REVISION6_POSTGRESQL_TEST_APPROVAL='sigra_revision6_homologation_test'
$env:SIGRA_REVISION6_HOMOLOGATION_ENABLED='true'
$env:SIGRA_REVISION6_BUNDLE=$bundle
$env:SIGRA_REVISION6_DECISION=$decision
$env:SIGRA_REVISION6_TARGET_PROOF=$proof
# DATABASE_URL recebe privadamente a URL runtime, nunca o owner.
$env:PYTHONPATH="$PWD\backend;$PWD"
& $python -B -m pytest backend/tests/test_revision6_postgresql.py backend/tests/test_revision6_derived_postgresql.py -q -p no:cacheprovider
```

Skips são pendências, não homologação. A matriz testa Base/Ampliada, seis perfis,
baixo/base/alto e proveniência usando Session PostgreSQL real. Os quatro testes
existentes verificam coexistência, idempotência, rollback transacional e contas/
registro/questionário/isolamento/exportação. TestClient com PostgreSQL NÃO
comprova processo real/navegador nem reinício da API.

Administrador fictício: usar o provisionador existente, com senha interativa,
somente no terminal do alvo confirmado e após auditoria aprovada. Não promover
um participante, reutilizar administrador antigo ou colocar senha em argumentos.

```powershell
& $python -B scripts/homologate_safety_revision6.py audit --bundle $bundle --decision $decision --proof $proof
if ($LASTEXITCODE -ne 0) { throw 'Auditoria do alvo dedicado reprovada; administrador não criado' }
if ([string]::IsNullOrWhiteSpace($env:SIGRA_REVISION6_RUNTIME_URL)) { throw 'Runtime privado não configurado' }
$env:DATABASE_URL=$env:SIGRA_REVISION6_RUNTIME_URL # sem imprimir o valor
$env:SIGRA_REVISION6_HOMOLOGATION_ENABLED='true'
$env:PYTHONPATH="$PWD\backend;$PWD"
& $python -B -m app.provision_admin --email 'admin-homologacao@example.test' --name 'Administrador fictício' --confirm-admin
```

```powershell
# Terminal exclusivo da API; habilitação só nesta homologação fictícia:
& $python -B scripts/homologate_safety_revision6.py serve --bundle $bundle --decision $decision --proof $proof --port 8011 --derived-configurations
# Outro terminal exclusivo, CORS exato http://127.0.0.1:14185:
$env:VITE_API_URL='http://127.0.0.1:8011'
& 'C:\Program Files\nodejs\npm.cmd' --prefix frontend run dev -- --host 127.0.0.1 --port 14185 --strictPort
```

Antes de iniciar, verificar portas livres; nunca encerrar listeners preexistentes.
Com dois participantes fictícios, executar cadastro/login, seleção explícita,
recomendação nas duas configurações, questionário, histórico privado, IDOR,
CSV pseudonimizado com administrador fictício provisionado pelo operador e logout.
Reiniciar realmente SOMENTE a nova API por Ctrl+C e mesmo comando; verificar
histórico, pesos/zeros/cenário/lote/método e comportamento das sessões persistidas.
Não anunciar esse fluxo aprovado por mocks ou replay. Coleta real permanece
bloqueada. Protocolos de consentimento/retenção e deploy continuam pendentes.

## Supavisor de sessão confirmado — 09/10/2026

O usuário autorizou a alternativa IPv4 sem adicionais. O endpoint foi observado em
**Connect → Direct/Connection string → Session pooler** do projeto confirmado,
não deduzido da região: `aws-1-sa-east-1.pooler.supabase.com:5432`, com
`postgres.tqlufobzzaabakflyxha` como seletor do operador. Transaction/6543 não é
permitido. Esse fato não autoriza conectar a outros poolers ou projetos.

A confirmação direta histórica `revision6-supabase-target-v1` permanece válida
somente para seu endpoint direto; não é sobrescrita. A confirmação de sessão
`revision6-supabase-session-target-v2` exige adicionalmente uma observação não
secreta completa: project_ref, host, port, mode=session, operator_username,
operator_database, source_url do painel Connect/session e observed_at com timezone.
O host é copiado dessa observação e fixado no hash do recibo externo. O padrão
de hostname sozinho nunca libera uma URL: o guard exige igualdade com o endpoint
confirmado e com o tenant do projeto em ambos os usuários de roteamento.

```powershell
& $python -B scripts/confirm_revision6_supabase_target.py --project-response $projectResponse --confirm-project $projectRef --ca $ca --session-connection $sessionObservation --output $newSessionConfirmation
```

Usar o caminho/hash desse novo recibo nas mesmas variáveis privadas e de
confirmação. Banco permanece `sigra_revision6_homologation_test`. Na URL de
sessão, os usernames são `sigra_revision6_owner.tqlufobzzaabakflyxha` e
`sigra_revision6_runtime.tqlufobzzaabakflyxha`; no SQL, `current_user` e privilégios
continuam sendo as roles simples owner/runtime, não os seletores com sufixo.
Não criar roles com o Project Ref no nome.

Ambas as URLs continuam exigindo `sslmode=verify-full` e o CA absoluto pinado.
A negociação PostgreSQL SSLRequest/TLS feita sem senha confirmou IPv4,
TLS 1.3 e certificado com SAN `*.pooler.supabase.com`, validado pelo CA oficial.
Isso comprova transporte e hostname, não autenticação, banco ou grants. O
preflight autenticado ainda exige os dois usuários, identidade SQL, TLS no
driver, observação válida de pg_stat_ssl, destino novo/vazio e privilégios mínimos.

Entrada privada preparada fora do checkout em
`.sigra-demo-agent-temp/revision6-session-homologation-20261009/configure-revision6-private.ps1`.
O responsável executa no PowerShell local: a senha original do operador é pedida
por Read-Host -AsSecureString. O helper não provisiona nem migra; autentica e
consulta somente em transação read-only. Reutiliza URLs/chave já fornecidas no
processo; senão gera senhas aleatórias para as roles ainda não criadas e uma
chave estável de pseudonimização. Armazena SecureStrings com DPAPI do usuário
Windows em `private-settings.clixml`, fora do Git, com ACL privada. Nunca imprime
URLs/chaves/senhas. Uma configuração existente é preservada; chave divergente
bloqueia, sem rotação. Manter esse arquivo entre reinícios e não incluí-lo em ZIP.

`-ValidateOnly` valida somente o recibo/CA e não solicita senha, não cria o cofre
e não conecta. Após validação local das URLs, o runner preserva a entrada em
`private-settings.pending.clixml`, por DPAPI/ACL, antes do teste de conexão.
Esse cofre pendente não comprova autenticação nem autoriza provisionamento;
é reutilizado sem regenerar a chave ou pedir novamente a senha. Somente depois
dos gates read-only aprovados é promovido, sem alterar seus bytes privados,
a `private-settings.clixml`. Uma falha preserva o pendente e não escreve no banco.
O comportamento anterior, que descartava a entrada em falhas de conexão, é
histórico. Nunca incluir nenhum desses cofres em relatórios, ZIPs ou Git.

O diagnóstico de conexão identifica etapa/código e localização estrutural
(arquivo, função e linha), sem mensagens brutas, argumentos ou variáveis locais.
Registra separadamente TLS do driver e o observado em `pg_stat_ssl`: através
do pooler essas observações se referem a conexões distintas. Em 09/10/2026 a
conexão autenticada confirmou TLS no cliente e `pg_stat_ssl=(false,null,null)`
no backend. Essa observação bloqueia a homologação, inclusive no endpoint
sessão confirmado: TLS no cliente não substitui TLS no upstream. A exceção
mode-aware anterior foi retirada; seus relatórios permanecem históricos e não
aprovam o contrato TLS vigente. Conexão direta sem TLS, cliente sem TLS,
linha ausente, erro de consulta e observação inconsistente continuam bloqueados. Não altera
recibo, CA, hostname, banco ou roles. Um `ValueError` genérico não comprova senha incorreta.
Referências: [duas conexões do pooler](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits),
[upstream_ssl independente](https://supabase.github.io/supavisor/configuration/tenants/) e
[pg_stat_ssl por backend](https://www.postgresql.org/docs/17/monitoring-stats.html).
Relatórios sanitizados são persistidos em `connection-diagnostics`, fora do Git.

A verificação do operador consulta identidade, `pg_backend_pid()` e a linha
correspondente de `pg_stat_ssl` em um único SELECT read-only, sem COALESCE.
PID retornado, presença da linha, SSL, versão e presença de cipher são registrados
separadamente. Linha ausente mantém SSL desconhecido; erro/permissão mantém
o resultado desconhecido e registra código/SQLSTATE, nunca `ssl=false` sintético.
Os parâmetros efetivos libpq `sslmode`/`sslrootcert`/host são conferidos contra
o recibo e o CA. Nenhum segredo aparece no relatório. SSL enforcement de
entrada e `upstream_ssl` são configurações distintas do Supavisor; não presumir
que alterar a primeira resolve a segunda. Consultar o estado sem modificá-lo.

Somente depois de receber esse input e comprovar o destino: provisionamento
exclusivo do banco/roles já documentados, preflight, prepare-new-database, audit,
materialize idempotente, os seis testes PostgreSQL e fluxo real/reinício. Não
alterar banco, schema, roles ou guard por conveniência se o serviço rejeitar a
conexão; registrar a causa real. Nenhum reset/downgrade, segunda cadeia Alembic,
Supabase Auth/Data API, ativação operacional ou coleta real é introduzido.
