# Prontidao para deploy

Nenhum deploy e executado nesta etapa.

| Area | Estado | Condicao antes de publicar |
|---|---|---|
| Frontend Vercel | preparado, nao validado | `VITE_API_URL`, build limpo e E2E verdes |
| Backend Vercel Functions | avaliacao pendente | confirmar cold start, timeout, pooler e tarefas de startup |
| Backend persistente | recomendado para primeira publicacao | healthchecks, logs e migrations fora do startup |
| PostgreSQL local | configurado | validar Docker/servidor real |
| Supabase | documentado, nao conectado | credenciais, SSL, migration e importacao validadas |
| Alembic | estruturado | upgrade/downgrade real verde em PostgreSQL |
| CORS | configuravel | listar apenas origens publicadas |
| Segredos | preparados | usar cofre do provedor; nunca `.env` versionado |
| FIPE | fora desta migracao | revisar timeout/cache antes de habilitar em producao |
| Tarefas agendadas | nao implementadas | definir executor externo futuro |
| Arquivos locais | risco conhecido | backend publicado nao deve depender de SQLite ou cache gravavel |
| E2E | configurado | Chromium e cinco fluxos verdes |
| Rollback | documentado | backup, revision anterior e verificacao de dados |

## Gate de producao

`DATABASE_ENV=production` rejeita SQLite. O override
`ALLOW_SQLITE_IN_PRODUCTION=true` existe apenas para recuperacao emergencial
documentada e nao e uma configuracao normal de deploy.

O startup de PostgreSQL nao chama `create_all` nem seeds; o deploy deve executar
Alembic como etapa separada e falhar se houver migration pendente.
