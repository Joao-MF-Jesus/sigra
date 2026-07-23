# E2E no Windows

## Pre-requisitos

- Windows com PowerShell;
- Node 24 e npm disponiveis;
- dependencias de `frontend/package-lock.json`;
- Python 3.12 com as dependencias do backend;
- portas `8010` e `4183` livres.

O executor nao instala ferramentas globais, nao altera a politica do
PowerShell e nao usa PostgreSQL nem o SQLite canonico.

## Execucao

Na raiz do projeto:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_e2e_windows.ps1
```

O `Bypass` vale apenas para esse processo. O script usa `npm ci` somente quando
`node_modules` esta ausente ou incompativel e instala apenas Chromium quando o
executavel esperado nao existe.

## Isolamento

- backend: `http://127.0.0.1:8010`;
- frontend: `http://127.0.0.1:4183`;
- banco: `tmp/sigra-e2e-<run-id>.db`;
- FIPE externa: desativada;
- workers: 1;
- SQLite canonico: somente auditado por hash e contagem, nunca usado pelo E2E.

No Windows, o `globalTeardown` identifica e encerra os processos que ainda
escutam as portas `8010` e `4183`, aguarda a liberacao das duas portas e so
entao remove o banco temporario, WAL e SHM. Erros `EPERM` e `EBUSY` recebem
ate 20 tentativas com espera progressiva; `ENOENT` significa que o artefato ja
foi removido. Uma falha persistente encerra o comando com erro e preserva o
arquivo para diagnostico.

O executor Windows confirma a liberacao das portas e a ausencia dos tres
artefatos. Portas ocupadas antes do teste causam falha em vez de reutilizacao
silenciosa.

## Artefatos

Em falha, preserve:

- `frontend/test-results/e2e/`;
- `frontend/playwright-report/`, quando gerado;
- `dist/validation/e2e-windows.log`;
- `dist/validation/e2e-local-report.json`.

Para abrir um trace:

```powershell
cd frontend
npx playwright show-trace .\test-results\e2e\<cenario>\trace.zip
```

## Erro spawn EPERM

`spawn EPERM` indica que o ambiente impediu a criacao do processo do Chromium.
Nao altere asserts, seletores ou timeouts para contornar essa restricao.
Execute o script em um PowerShell comum, fora de terminais sandboxados. Se a
falha persistir, confirme permissao de execucao do caminho mostrado no
relatorio e mantenha traces e logs.
