# Backup e recuperacao da homologacao

## Principio

O banco remoto contem somente dados demonstrativos reproduziveis. Mesmo assim,
backup e restauracao devem ser tratados como operacoes controladas. Nunca teste
restauracao sobre o banco ativo.

## Opcao A: recriacao reproduzivel

Para uma homologacao nova e vazia:

1. crie outro banco PostgreSQL;
2. configure a conexao direta somente no terminal seguro;
3. execute `alembic upgrade head`;
4. execute o bootstrap sem `--confirm`;
5. revise banco, revisao e contagens;
6. execute com `--confirm`;
7. valide o relatorio e execute o smoke.

Essa e a recuperacao preferencial enquanto a base continuar integralmente
demonstrativa.

## Opcao B: backup logico

Use a URL nativa fornecida pelo Supabase com `pg_dump`, sem imprimir a senha e
sem salva-la em scripts:

```powershell
$env:PG_BACKUP_URL = "<URL_POSTGRES_NATIVA_DIRETA>"
pg_dump --format=custom --no-owner --no-acl --file "sigra-homologation.dump" "$env:PG_BACKUP_URL"
Get-FileHash "sigra-homologation.dump" -Algorithm SHA256
Remove-Item Env:PG_BACKUP_URL
```

Mantenha o dump fora do repositorio e em armazenamento autorizado. Registre
data, commit, revisao Alembic, tamanho e SHA-256.

## Ensaio de restauracao

Crie um banco separado e vazio. Depois:

```powershell
$env:PG_RESTORE_URL = "<URL_POSTGRES_NATIVA_DO_BANCO_NOVO>"
pg_restore --exit-on-error --no-owner --no-acl --dbname "$env:PG_RESTORE_URL" "sigra-homologation.dump"
Remove-Item Env:PG_RESTORE_URL
```

Valide:

- Alembic em `20260803_0004`;
- todas as tabelas esperadas;
- contagens por tabela comparadas com o relatorio original;
- ausencia de orfaos e duplicidades;
- 34 automoveis;
- quatro motocicletas demonstrativas;
- health, smoke e E2E externo.

Nao use `--clean` no banco ativo. Nao execute downgrade destrutivo automatico.

## Limitacao do provedor

Backups automaticos, retencao e recuperacao point-in-time dependem do plano
vigente do Supabase. Confirme no painel antes de cada marco. A documentacao nao
assume que uma oferta gratuita continuara disponivel nem que ela inclua
recuperacao suficiente.
