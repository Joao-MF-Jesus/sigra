# Homologação PostgreSQL do TCC: Supabase como hospedagem

Status: preparação revisável, **não é deploy nem homologação PostgreSQL aprovada**.
Não usar Supabase Auth, não carregar os 34 veículos de demonstração, não publicar
Gold. React/Vite e FastAPI continuam responsáveis pela interface e pelo motor.
V6 aprovada continua a fonte acadêmica, V7 separada e inativa.

## Evidência documental

Monografia consultada: `TCC_SIGRA_Joao_Marcelo_Ferreira_de_Jesus_e_Felipe_Aceti_Araujo.pdf`,
49 páginas, arquivo de Downloads atualizado em 07/10/2026, SHA-256
`8c59530cf1a12fe1ba14146eff2f5ca980fc915404f9deb3db9bf5e43e85497b`.
Não foi editada. A data identifica o arquivo encontrado, não uma aprovação nova.

- Páginas 22–24, seções 4.2–4.6: PostgreSQL canônico, React/Vite, FastAPI,
  schemas Bronze/Silver/Gold/meta e migrations Alembic; SQLite é auxiliar e
  não substitui validação PostgreSQL. Não há exigência de hospedagem apenas local.
- Página 24: o catálogo acadêmico exige contrato explícito; não representa
  publicação operacional pela cadeia Medalhão.
- Página 32, seção 5.11: código pseudônimo de participante, entradas, resultados,
  exclusões e versões necessárias à reprodução.
- Páginas 34–36: congelamento do dataset/método, regressões, piloto e separação
  de validação técnica versus avaliação por participantes.
- Páginas 46–47, apêndices C/D: código pseudônimo, familiaridade, prioridades,
  cenário, quatro avaliações separadas e metadados de execução.

`SIGRA_ARQUITETURA_MEDALHAO.md` preserva o PostgreSQL e a separação das camadas.
`ACADEMIC_COHORT_V6_BACKEND.md` define snapshot 60/1.080 e contrato aprovado.
`HOMOLOGATION_DEPLOY.md` já prevê Supabase como PostgreSQL, mas seu bootstrap
de demo pública **não se aplica** ao experimento privado V6. `SUPABASE_SETUP.md`
e `render.yaml` antigos também não autorizam executar bootstrap nesta etapa.

Logo, hospedagem Supabase é arquiteturalmente compatível; isto não aprova a
prontidão acadêmica de todos os perfis. Família/Estrada têm somente uma opção.

## Projeto exclusivo e conexão

Organização escolhida: Joao-MF-Jesus's Org. Projeto pretendido:
`sigra-tcc-homologacao`. Não reutilizar projetos inativos sem relação com SIGRA.
Consultar e confirmar custo antes de criar. Nenhum projeto foi criado por esta
preparação. Em 07/10/2026 o conector confirmou `plan=free`, `tier=tier_free`
para a organização. A nova consulta `get_cost` continua retornando
`UNAVAILABLE: MCP tool get_cost was not returned by tools/list`; custo específico
do projeto ainda NÃO foi confirmado. `confirm_cost`/criação não executados.
Procedimento mínimo: reconectar a integração para disponibilizar get_cost e
seguir consulta/confirmação/criação, ou abrir o Dashboard na organização
confirmada, revisar New Project com total US$0/mês sem add-ons e criar somente
`sigra-tcc-homologacao`. Não alterar assinatura ou restaurar projetos alheios.
Fornecer depois apenas ref/host/CA; senhas entram localmente, nunca no chat.

Após criar um projeto NOVO exclusivamente para esta homologação:

1. Copiar host, project ref e usuários **reais** do painel Connect. Usar conexão
   direta IPv6 ou Supavisor **session** IPv4, porta 5432. Não usar transaction
   pooler 6543 para migrations/esta preparação.
2. Baixar o CA do projeto, preservar fora do Git; todas as URLs usam
   `sslmode=verify-full` e `sslrootcert` absoluto. Não reduzir para `require`.
3. Provisionar somente nesse projeto o role `sigra_tcc_runtime LOGIN`, sem
   SUPERUSER, BYPASSRLS, CREATEDB, CREATEROLE, memberships ou propriedade de
   tabelas. Definir senha em ferramenta interativa local, sem chat/argumentos.
   Não conceder permissões amplas. O script concede os acessos exatos depois.
4. Desabilitar a Data API no painel se não utilizada. Ainda assim aplicar e
   auditar revogações/RLS. Não enviar chaves anon/service_role ao frontend.
5. Obter o replay V6 aprovado já existente; referências locais não o substituem.
   Nunca gerar outro resultado para passar na validação.

O guard `app.tcc_supabase` fixa projeto/host/usuários/banco/porta/CA. No modo
apply exige confirmação do ref e ausência de relações em todos os schemas
SIGRA. Schemas administrados auth/storage/realtime não são modificados.
Se falhar parcialmente, NÃO apagar/recriar: inspecionar a revisão e relatório
primeiro; o guard não contorna um alvo agora não vazio.

## Comandos reais (raiz do repositório, variáveis sem segredos)

O exemplo `backend/tcc.supabase.env.example` não é carregado automaticamente.
Substituir `$projectRef`, `$hostReal`, `$ca`, `$replay` pelos identificadores e
arquivos reais. Eles não contêm senha. Para session pooler, adicionar
`--session-pooler` a cada comando abaixo. O helper pede senhas ocultas localmente,
constrói URLs com SQLAlchemy e transmite-as somente no ambiente do filho.

```powershell
$python = '.\backend\.venv\Scripts\python.exe'
& $python scripts/tcc_supabase_session.py validate --project-ref $projectRef --host $hostReal --ca $ca --replay $replay
# Apenas no projeto novo/exclusivo, após revisar custo e criar o role:
& $python scripts/tcc_supabase_session.py prepare --project-ref $projectRef --host $hostReal --ca $ca --replay $replay --confirm-project $projectRef
& $python scripts/tcc_supabase_session.py test --project-ref $projectRef --host $hostReal --ca $ca --replay $replay --confirm-project $projectRef
```

Prepare usa a cadeia Alembic EXISTENTE incluindo `20261007_0014` e a migration
aditiva do instrumento `20261007_0015`. Não cria uma cadeia Supabase nem altera
0014. Exercita `0013 -> 0014 -> 0013 -> 0014 -> 0015 -> 0014 -> 0015` antes de dados de participantes,
importa V6 duas vezes com o materializador existente e audita 60/1.080 e
idempotência. Isso não constitui o fluxo HTTP ou o deploy aprovado.

O downgrade 0014 é defensivo: com credenciais/sessões/testes, deve bloquear.
Nunca apagar registros para fazê-lo passar. A reversão documentada continua
`alembic -c backend/alembic.ini downgrade 20261005_0013` SOMENTE na camada vazia,
com URL de migration do destino exclusivo e backup revisado. Após coleta usar
uma migration corretiva, não reversão destrutiva.

## Permissões, autenticação e privacidade

Operador de migration distinto do runtime. O runtime lê o snapshot acadêmico
e recebe DML apenas nas dez tabelas pessoais (users/auth_sessions/test runs,
study sessions/questionnaires/expenses/maintenances/user vehicles/vehicle reports/fuel consumption reports).
Isso preserva o relatório financeiro privado após login sem grants amplos. Não recebe
escrita em academic/Gold, DDL ou propriedade de tabelas. Revogam-se permissões
de PUBLIC/anon/authenticated nos schemas SIGRA e defaults do operador.

RLS ENABLE/FORCE protege as dez tabelas privadas. A policy é apenas para o
role de serviço `sigra_tcc_runtime`. Não usa `auth.uid()`: todos os participantes
entram por FastAPI, que valida sessão opaca, papel e proprietário. Uma credencial
do serviço comprometida continua sendo risco; RLS não autentica cada participante
numa conexão de serviço compartilhada. Nunca expor a conexão no navegador.

CSV administrativo requer `SIGRA_RESEARCH_PSEUDONYM_KEY` estável/privada, pelo
menos 32 bytes aleatórios preservados em secret manager. Sem chave, 503 antes de
streaming. HMAC com separação de domínio substitui nome/e-mail/ID de usuário por
`participant_code`. Não rotacionar a chave entre sessões da mesma rodada. Ainda
é dado pseudonimizado, não anonimizado: revisar texto livre para PII antes de
distribuir CSV. Conta nome/e-mail permanece privada para autenticação.

## Backend, frontend e administrador

Configurar `PUBLIC_DEMO_MODE=false`, `ACADEMIC_COHORT_ENABLED=true`,
`FIPE_AUTO_REFRESH=false`, `DATABASE_ENV=homologation`, origem CORS EXATA e
ALLOWED_HOSTS explícito. Não permitir wildcard com cookies.

Preferir domínios HTTPS do frontend/API no mesmo site (domínio controlado) com
SameSite=Lax e Secure=true. Vercel.app/onrender.com são sites diferentes:
Lax não funciona para fetch autenticado entre eles. SameSite=None exige Secure
e pode ser bloqueado por políticas de cookies de terceiros; validar no navegador
alvo ou usar proxy/domínios same-site. Não chamar esse fluxo de aprovado antes disso.

Template separado, sem auto deploy: `deploy/tcc-participants.render.yaml`.
Raiz é o repositório completo, pois o backend usa também `data_platform`.
Build/start NÃO executam migrations/import/bootstrap. Instalar CA como arquivo
privado e configurar URL runtime; não fornecer URL de operador ao processo web.
O plano/custo do host e as URLs reais ainda precisam ser escolhidos.

Teste HTTP local contra PostgreSQL remoto, em terminais exclusivos:

```powershell
$env:SIGRA_COOKIE_SECURE='false' # EXCLUSIVAMENTE localhost HTTP, nunca deploy.
$env:SIGRA_COOKIE_SAMESITE='lax'
$env:CORS_ALLOWED_ORIGINS='http://127.0.0.1:5173'
& $python scripts/tcc_supabase_session.py serve --project-ref $projectRef --host $hostReal --ca $ca --replay $replay
# Outro terminal; sem credenciais:
$env:VITE_API_URL='http://127.0.0.1:8010'
$env:VITE_PUBLIC_DEMO_MODE='false'
& 'C:\Program Files\nodejs\npm.cmd' --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Provisionar administrador com confirmação do projeto, senha oculta e nova conta:

```powershell
& $python scripts/tcc_supabase_session.py admin --project-ref $projectRef --host $hostReal --ca $ca --replay $replay --confirm-project $projectRef --admin-email $emailResponsavel --admin-name $nomeResponsavel
```

Testar cadastro, duplicidade, login incorreto, escalada rejeitada, recomendação
real com 60 candidatos (sem filtros restritivos), feedback, histórico, dois
participantes/IDOR, CSV admin, reinício REAL do processo API e logout. Registrar
contagens/fingerprints antes/depois. O teste automatizado Supabase recria cliente
API/pool de conexões; isso NÃO substitui reinício OS-process/browser.
Não usar o teste local `SIGRA_TCC_TEST_DATABASE_URL` com um host remoto: seu
guard local continua intacto. Skips por ausência de destino não são aprovação.

## Pendências acadêmicas e aceite

A monografia prevê voluntariedade e minimização de identificação, mas não foi
encontrado prazo de retenção nem um TCLE final aprovado. Decidir com orientação
acadêmica: texto/registro de consentimento, prazo, responsáveis/acesso, retirada,
descarte e separação de contas versus dados analíticos. Não inventar prazos.

O instrumento novo implementa cenário A–E, familiaridade, prioridades antes do
ranking, quatro perguntas distintas e índice técnico C/D. A nota geral antiga
permanece separada, sem conversão artificial. Ver `TCC_STUDY_PROTOCOL_REVIEW.md`
para correspondência, testes e proposta de consentimento/retenção pendente.
Modo homologation somente fictício; coleta real continua bloqueada. Tarefas e
opções específicas A–E também precisam de revisão. Metadados ausentes não são
inventados: `analysis_ready=false` quando faltam versões necessárias.

Auditoria posterior sem materialização/migration (destino já preparado):

```powershell
& $python scripts/tcc_supabase_session.py audit --project-ref $projectRef --host $hostReal --ca $ca --replay $replay --confirm-project $projectRef
```

Ela usa transação read-only e o role runtime para verificar payloads/fingerprints
60/1.080, revisão, grants/RLS e tamanho completo da base. No momento o tamanho
PostgreSQL é **não medido**, pois o projeto não existe. Conferir quota real do
Dashboard/organização; 100 testes não substituem medição de banco/egress.

Não anunciar testes com participantes/deploy aprovados antes de: destino/custo
confirmados; migration+V6+permissões reais; fluxo/browser/reinício real; protocolo
acadêmico aprovado; congelamento das versões; plano seguro de backup/retensão.
