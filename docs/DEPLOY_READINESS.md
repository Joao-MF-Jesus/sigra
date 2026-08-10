# Prontidao para deploy

Nenhum deploy e executado nesta etapa. A branch `deploy/homologation` contem
somente a preparacao; autenticacao, criacao de projetos, configuracao de
secrets, migrations remotas e publicacao sao checkpoints manuais.

| Area | Estado | Condicao antes de publicar |
|---|---|---|
| Frontend Vercel | manifesto preparado, nao publicado | `VITE_API_URL`, `VITE_PUBLIC_DEMO_MODE=true`, build e E2E verdes |
| Backend Vercel Functions | avaliacao pendente | confirmar cold start, timeout, pooler e tarefas de startup |
| Backend persistente | recomendado para primeira publicacao | healthchecks, logs e migrations fora do startup |
| PostgreSQL local | configurado | validar Docker/servidor real |
| Supabase | bootstrap preparado, nao conectado | projeto separado, SSL, Alembic e seed idempotente validados |
| Alembic | estruturado | upgrade/downgrade real verde em PostgreSQL |
| CORS | configuravel por ambiente | listar apenas a origem HTTPS publicada |
| Demo publico | implementado | HTTP 403 em escritas e rotas privadas; calculos stateless disponiveis |
| Segredos | preparados | usar cofre do provedor; nunca `.env` versionado |
| FIPE | fora desta migracao | revisar timeout/cache antes de habilitar em producao |
| Tarefas agendadas | nao implementadas | definir executor externo futuro |
| Arquivos locais | risco conhecido | backend publicado nao deve depender de SQLite ou cache gravavel |
| E2E | local e externo separados | local sem regressao; externo com seis fluxos seguros |
| Rollback | documentado | backup, revision anterior e verificacao de dados |

## Gate de homologacao

1. CI da branch verde;
2. Supabase criado e vazio, sem secrets no Git;
3. Alembic em `head`;
4. bootstrap `homologation-demo-v1` confirmado e validado;
5. Render online e health verde;
6. Vercel online e CORS restrito;
7. smoke e E2E externo verdes;
8. backup e rollback revisados.

Consulte `HOMOLOGATION_DEPLOY.md`, `HOMOLOGATION_SECURITY.md`,
`HOMOLOGATION_BACKUP_RESTORE.md` e `HOMOLOGATION_ROLLBACK.md`.

## Gate de producao

`DATABASE_ENV=production` rejeita SQLite. O override
`ALLOW_SQLITE_IN_PRODUCTION=true` existe apenas para recuperacao emergencial
documentada e nao e uma configuracao normal de deploy.

O startup de PostgreSQL nao chama `create_all` nem seeds; o deploy deve executar
Alembic como etapa separada e falhar se houver migration pendente.
