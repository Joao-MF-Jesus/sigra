# Prontidao para migracao PostgreSQL

O SIGRA mantem SQLite para desenvolvimento e testes rapidos e possui uma
baseline PostgreSQL validada em banco real. A validacao local foi executada em
PostgreSQL 18; a CI usa PostgreSQL 16 efemero.

## Baseline preservada

- automoveis: 34, algoritmo `2.1.2`, pesos `cars-v1`;
- financiamento: modulo `1.0.3`, metodo `price-v1.2`, stateless;
- motocicletas: modulo `0.3.1`, algoritmo/pesos `null`, endpoint HTTP 501;
- SQLite canonico: `backend/sigra.db`;
- schema PostgreSQL: Alembic revision `20260723_0001`;
- schema logico: `1.0.0`;
- export intermediario: `sqlite-export-v1`.

## Evidencia local de 2026-07-23

| Area | Resultado |
|---|---|
| Conectividade | `sigra_dev`, `sigra_integration` e `sigra_migration_test` acessiveis |
| Alembic em desenvolvimento | upgrade aprovado, revision `20260723_0001` |
| Ciclo descartavel | upgrade, downgrade base e segundo upgrade aprovados |
| Schema | 18 tabelas, 79 constraints, 11 indices e 47 colunas `Numeric` validadas |
| Export SQLite | 18 tabelas e 435 registros, sem referencias orfas |
| Importacao | transacao unica, 435 registros e 17 sequences reajustadas |
| Equivalencia | nenhuma diferenca de contagem, valor, relacao ou versao |
| Testes PostgreSQL | 226 executados, 226 aprovados, 0 ignorados |
| Health | engine PostgreSQL acessivel e migration atualizada |

Os relatorios locais ficam em `dist/validation/`, que e ignorado pelo Git.
Eles usam URLs sanitizadas e nao armazenam senha.

## Politicas preservadas

- Alembic e a unica fonte de criacao do schema PostgreSQL.
- O startup PostgreSQL nao chama `create_all` e nao executa seeds.
- Valores monetarios usam `Numeric(14,2)` no schema e `Decimal` na aplicacao.
- `null`, JSON, datas, timestamps e booleanos sao preservados pelo export/import.
- A importacao exige destino controlado, revision atual e confirmacao explicita.
- O comparador normaliza os tipos sem aceitar diferencas monetarias.
- Scripts de bootstrap SQLite permanecem isolados do fluxo PostgreSQL.

## Gates ainda externos

- Os cinco testes Playwright foram descobertos, mas a execucao local no sandbox
  foi bloqueada por `spawn EPERM` e, em nova tentativa, por timeout. A CI
  continua sendo o ambiente reproduzivel para esse gate.
- Supabase e deploy permanecem documentados e fora desta baseline.
- Carga, concorrencia, backup e restauracao de producao ainda exigem ensaio
  especifico antes de publicacao.

Consulte `POSTGRESQL_SETUP.md`, `DATABASE_MIGRATION.md`, `TESTES_E_CI.md`,
`SUPABASE_SETUP.md` e `DEPLOY_READINESS.md`.
