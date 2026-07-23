# Primeiro push do SIGRA

## 1. Criar o repositorio vazio

Crie manualmente um repositorio vazio no provedor Git. Nao adicione README,
licenca ou `.gitignore` remoto se esses arquivos ja existem localmente.

## 2. Adicionar o remote

```powershell
git remote add origin <URL_DO_REPOSITORIO>
```

## 3. Conferir o remote

```powershell
git remote -v
```

Confirme que a URL aponta para o repositorio correto e nao contem token,
usuario, senha ou outro segredo.

## 4. Realizar o primeiro push

Somente depois de conferir o commit e a arvore limpa:

```powershell
git push -u origin main
```

## 5. Observar a CI

Abra a aba Actions do repositorio e acompanhe os jobs:

- backend-sqlite;
- backend-postgresql;
- frontend;
- e2e;
- package-validation.

Uma workflow presente no arquivo local nao equivale a CI remota aprovada.

## 6. Nao subir segredos

Antes do push, execute:

```powershell
git status --short
git diff --cached --stat
git grep -n -I -E "DATABASE_URL=.*:.*@|PGPASSWORD=.+|BEGIN .*PRIVATE KEY|gh[pousr]_|sk-"
```

Revise falsos positivos. `.env`, bancos, ambientes virtuais, caches, traces e
relatorios locais devem continuar ignorados.

## 7. Reverter um push incorreto

Interrompa novos pushes e remova imediatamente qualquer credencial exposta no
provedor original. Para desfazer codigo sem reescrever historico compartilhado,
prefira:

```powershell
git revert <HASH_DO_COMMIT>
git push
```

Se houve segredo, apenas apagar o arquivo nao e suficiente: revogue ou troque a
credencial e siga o procedimento de remocao de historico do provedor.

## 8. Arquivos que devem estar ausentes

- `.env` e credenciais;
- `*.db`, `*.sqlite` e backups;
- `.venv/`, `.venv-validation/` e `node_modules/`;
- `dist/`, builds e relatorios locais;
- `tmp/`, caches, logs, screenshots, videos e traces;
- ZIPs e outros arquivos compactados.

Este documento nao adiciona remote, nao executa push e nao utiliza token.
