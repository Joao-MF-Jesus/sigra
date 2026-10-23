# CI e build público reproduzível — PR #3

## Causa das falhas anteriores

No HEAD `024518404884a7ec5b33bf12ec12b85df33e7d8e`, as execuções push
`39870819789` e pull_request `39872017431` falharam no backend, antes das
asserções Revision6: `test_academic_safety_revision6.py:setUpClass` exigia
`SIGRA_REVISION6_BUNDLE`; também faltava `SIGRA_REVISION6_DECISION`.
O workflow não provisionava nenhum dos dois insumos. Os jobs dependentes não
executaram; isso não prova falha própria de E2E ou empacotamento.

O diretório documental original contém 295 arquivos (~1,05 GB), inclusive PDFs,
artefatos de auditoria e caminhos do operador. Não é uma fixture pública adequada.
O plano já aprovado e comprimido **sem perdas** contém os registros congelados,
a decisão de cobertura, proveniência e as duas versões de replay necessárias.
Está agora em `build_inputs/revision6/`, junto do contrato e da decisão original.
Não contém contas, sessões, históricos, URLs autenticadas ou recibos privados.

| Insumo | SHA-256 |
| --- | --- |
| plan.json.gz (10.499.497 bytes) | 77bde60efdb96e4bfd540055555824319d668991e9020425a9295340e91b620f |
| plan.json restaurado (192.101.420 bytes) | cb70ff5298ffc4c52fc74e44588b2e34a39584b4cacfa6146981670737f3be97 |
| coverage-decision.json | 8b5266c06bee83fb6e96422092c62f988defe9b6c3854aff465fd918aa5a4f55 |

O modo explícito de fixture `pinned-runtime-plan-v1` restaura esses bytes,
valida o plano inteiro, compara a decisão e recalcula as 1.080 avaliações com
o motor existente. Mantém 60 veículos e os fingerprints aprovados:

- Coorte aprovada: `d974f86d2deef3903ac052263c7edc406c5b2c21d794721e5220ed5d99acc05d`.
- Revision6: `55ab70a71119e31d0f2654f14d207daa1ab2481a0b33b568ca7066fd8f1b6a34`.

Nenhuma assertion foi removida e nenhum skip foi acrescentado. O modo documental
original continua padrão e mantém a auditoria integral dos PDFs/arquivos quando
seu bundle estiver disponível. CI com plano fixado **não é uma nova auditoria
documental dos PDFs**. A decisão histórica não autoriza escrita, deploy ou coleta.

## Reprodução em clone novo (sem artefatos locais anteriores)

Use Python 3.12, Node 24 e diretórios de saída novos. Não importe variáveis
privadas de banco do ambiente operacional.

```sh
python -m pip install -r backend/requirements.txt
python scripts/prepare_build_inputs.py --output dist/ci-revision6
export PYTHONPATH="$PWD"
export SIGRA_REVISION6_FIXTURE_MODE=pinned-runtime-plan-v1
export SIGRA_REVISION6_BUNDLE="$PWD/dist/ci-revision6"
export SIGRA_REVISION6_DECISION="$PWD/dist/ci-revision6/coverage-decision.json"
export SIGRA_CANONICAL_SQLITE_PATH="$PWD/tmp/sigra-ci-source.db"
python scripts/bootstrap_ci_sqlite.py
python -m unittest discover -s backend/tests -t backend -v
python scripts/verify_published_sources.py
python scripts/build_preview_project.py --output dist/preview-project
npm ci --prefix dist/preview-project/application/frontend --ignore-scripts
node dist/preview-project/application/deploy/build_vercel.mjs
```

Em PowerShell, configure esses mesmos nomes com `$env:NOME=...`; use
`(Get-Location).Path` para a raiz. Se o perfil isolado bloquear o diretório
temporário padrão, defina TEMP/TMP para uma pasta nova dentro desse clone.
Não alterar testes nem proteções por essa limitação do perfil.

As suítes PostgreSQL completas usam **somente o serviço descartável postgres:16**
do job backend-postgresql. Não usam Neon, Supabase ou banco homologado. Os skips
já existentes de integração na execução SQLite não substituem esse job.

## Function Linux oficial, sem publicação

O job `reproducible-preview-function` executa este procedimento em Ubuntu:

```sh
python -m pip install uv==0.10.11
npm ci --prefix tools/preview-builder --ignore-scripts
node tools/preview-builder/build.mjs dist/preview-project dist/preview-function
python scripts/validate_preview_function.py dist/preview-function
```

O lock fixa @vercel/python 25.1.3 e @vercel/build-utils 14.21.3, como na
integração anterior. O builder pode obter dependências apenas dos registries
públicos; não exige conta Vercel. Não chama CLI, API de deploy, banco ou migrations.
O verificador compara bytes, modos e links internos do ZIP oficial e da extração,
o manifesto completo, imports/factory e fechamento do runtime sem configuração.
O orçamento de 225 MiB é o limite observado no build anterior, não uma garantia
genérica de plano. Tamanho anterior (128,06 MiB) não mede automaticamente este build.
Os recibos públicos são artefatos do CI; o bundle não é publicado em registry.

## Identidade e privacidade

`correspondence.json` e a tag `tcc-preview-http-20261022` continuam referências
históricas intactas. `source-revisions.json` registra separadamente duas mudanças
runtime deliberadas, com hashes antes/depois. O verificador exige ambos os mapas,
não aprende novos hashes e continua detectando mudanças reais.

A montagem produz **nova identidade**, manifesto exato e recibo determinístico.
Ela não afirma equivalência binária com a release remota
`sigra-be98bd5b78ce6ddd81592d08`; o Preview existente não é alterado.
O overlay pv22 com includeFiles **string** é preservado byte a byte.

O build não inclui nem fabrica os dois aceites operacionais privados. O manifesto
novo seleciona explicitamente `external-acceptances-v1`. Para futura execução,
além das variáveis documentadas do runtime, o operador precisará fornecer
privadamente `SIGRA_FUNCTIONAL_ACCEPTANCE_B64` e
`SIGRA_NEON_TRANSPORT_ACCEPTANCE_B64`, com os bytes dos aceites originais.
O startup exige seus SHA-256 originais, grava cópias efêmeras restritas e valida
seu conteúdo pelo contrato existente. Valor ausente/alterado não recebe fallback.
Não há necessidade desses valores para montar ou compilar o projeto público.

Identidade real do destino, OIDs, CA, credenciais, chave de pseudonimização e aceites
restritos continuam configuração privada: não podem ser inventados pelo CI.
Build/import aprovado não demonstra lifespan conectado nem fluxo remoto novo.
O modo histórico com aceites embutidos permanece compatível e inalterado.

Preview protegido e fictício; coleta real desligada; `historical_row_changed=1`.
Este trabalho não repete autenticação, recomendação, exportação ou deploy remoto,
não amplia aceites e não autoriza merge automático.
