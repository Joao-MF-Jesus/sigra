# Preparacao para Supabase

O SIGRA nao cria projeto Supabase nem armazena credenciais automaticamente.

## Configuracao manual

1. Crie um projeto no painel Supabase.
2. Copie a URL de conexao direta para migrations.
3. Configure SSL conforme a URL fornecida pelo painel.
4. Use uma URL de pooler apropriada para a aplicacao se o ambiente for
   serverless.
5. Guarde senha e URLs somente nas variaveis secretas do ambiente.

Exemplo conceitual:

```env
DATABASE_ENV=production
DATABASE_URL=postgresql+psycopg://usuario@host:5432/postgres?sslmode=require
PGPASSWORD=<configurar-no-gerenciador-de-segredos>
```

Nao registre senha, project ref privado, token ou `service_role` no repositorio.

## Ordem de ativacao

1. Teste conectividade sem imprimir a URL.
2. Use conexao direta para
   `python -m alembic -c backend/alembic.ini upgrade head`.
3. Execute o export e o validador local.
4. Execute o importador em dry-run.
5. Confirme a importacao.
6. Rode `check_migration_status.py`, `/health/database` e as regressões.
7. Troque a aplicacao para a URL de runtime/pooler.

## Rollback

Antes da carga, crie backup pelo mecanismo do Supabase. Em falha, interrompa a
aplicacao, restaure o backup ou recrie um banco vazio, aplique Alembic e repita
o export validado. O SQLite permanece como fonte local ate a equivalencia ser
confirmada.

Sem credenciais fornecidas, conectividade e migrations remotas permanecem
pendentes. Este documento nao declara Supabase validado.
