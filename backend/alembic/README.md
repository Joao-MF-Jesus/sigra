# Alembic

O schema publicado do SIGRA e criado e evoluido por migrations.

Comandos oficiais, executados na raiz:

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini downgrade base
```

`DATABASE_URL` deve estar configurada. Nenhuma credencial e mantida neste
diretorio. A migration inicial cria somente o schema vazio e nao executa seeds.
