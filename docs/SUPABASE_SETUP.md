# Preparacao para Supabase

O SIGRA nao cria projeto Supabase nem armazena credenciais automaticamente.
Para homologacao, use um projeto separado e siga tambem
`HOMOLOGATION_DEPLOY.md`.

## Configuracao manual

1. Crie um projeto no painel Supabase.
2. Copie a URL de conexao direta para `MIGRATION_DATABASE_URL`.
3. Configure SSL conforme a URL fornecida pelo painel.
4. Use em `DATABASE_URL` uma URL persistente/pooler compativel com o Render.
5. Guarde senha e URLs somente nas variaveis secretas do ambiente.

Exemplo conceitual:

```env
DATABASE_ENV=homologation
DATABASE_URL=postgresql+psycopg://usuario@host:5432/postgres?sslmode=require
MIGRATION_DATABASE_URL=postgresql+psycopg://usuario@host:5432/postgres?sslmode=require
```

Nao registre senha, project ref privado, token ou `service_role` no repositorio.

## Ordem de ativacao

1. Teste conectividade sem imprimir a URL.
2. Use conexao direta para
   `python -m alembic -c backend/alembic.ini upgrade head`.
3. Confirme que o banco esta vazio.
4. Execute `bootstrap_homologation_data.py` sem confirmacao.
5. Revise o relatorio e execute novamente com `--confirm`.
6. Rode `/health/database`, smoke e regressões.
7. Mantenha a aplicacao na URL de runtime/pooler.

## Rollback

Antes da carga, crie backup pelo mecanismo do Supabase. Em falha, interrompa a
aplicacao, preserve o banco ativo e restaure somente em um banco separado. A
base demonstrativa pode ser recriada com Alembic e o bootstrap versionado.

Sem credenciais fornecidas, conectividade e migrations remotas permanecem
pendentes. Este documento nao declara Supabase validado.
