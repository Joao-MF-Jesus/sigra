# Preparação de publicação do SIGRA — 14/10/2026

**Preparação, não publicação. Coleta real desligada.** O aceite funcional com ressalva é o adendo `acceptance-20261014/report.json`, SHA-256 `e23eb2be3ba98a2520fb87b51c5534271530ccbb8ea1e1c1a9890dbc3cf2914a`. Preserva parecer `451cd7ff391f99e7132c01aa4eb40112996be43589a154fc8f8a2d86a67c5f18`, CSV `a8ca17f4658df75ecbc5cb0b7f9a5af6ba69a3e0876de98652743917d49203f5` e `historical_row_changed=1`. A ressalva não é ampliada nem apagada. Não repetir A–E, recuperação, exportação ou testes 403 locais.

## Entrega exata e arquitetura

HEAD base real: `ba2fb4d6ee9e0cf4e50ee8b2538b862b89fd7648`, branch `feature/frontend-v2`. Há trabalho local ainda não commitado, inclusive a integração aceita. Publicar apenas esse HEAD pelo Git **não** publicaria a versão homologada. O pacote é congelado a partir dos bytes atuais, com `release/manifest.json`, identificação `sigra-<24 dígitos hex>` e SHA-256 do ZIP. Esse identificador, não um hash Git copiado, vira `system_version`. Nada é staged/commitado nesta preparação.

Reutiliza React/Vite, FastAPI, PBKDF2 e sessões opacas existentes; Supabase é somente PostgreSQL. A imagem serve frontend em `/` e API em `/sigra-api`, na mesma origem HTTPS. `VITE_API_URL=/sigra-api` evita localhost, cookies de terceiros e o cruzamento vercel.app/onrender.com. A factory é separada: `app.deployment:create_app`; não substitui os launchers locais 8010/8011/14184/14185.

V6 aprovado e Revision6 coexistem sem Gold operacional. Plano pinado conserva 60 identidades e 1.080 avaliações, com Cidade 10, Aplicativo 60, Trabalho 10, Espaço 24, Família 9, Estrada 9 nos três cenários. A leitura reutiliza `Revision6Repository`, `Revision6Service`, `validate_plan` e `audit_snapshot`; não libera `validate_replay` V6 nem reclassifica a candidata como aprovação operacional. Tiguan 70, Focus sem massa, Fiesta sem ESC e desconhecidos continuam como no recorte aceito.

Base/Ampliada só são disponibilizadas com `SIGRA_DERIVED_PERSONALIZATION_ENABLED=true`, explicitamente, e escolhidas pelo participante. Vetores, método `academic-derived-seven-v1`, cenários, custos e requisitos permanecem nos contratos existentes. Cobertura de nota completa Base 10/60/10/24/9/9 e Ampliada 0/8/0/3/8/8; não confundir com prontidão documental. O artefato de runtime contém valores, fontes, unidades, hashes e os dois replays; não depende de caminhos temporários para recuperar esses dados. Originais documentais continuam no acervo preservado, não são PDFs servidos ao público.

## Bloqueios de pesquisa resolvidos no código, sem ativação

Antes: modo `research` inexistente, etiqueta somente fictícia, seleção Revision6 restrita ao launcher local e template antigo sem escolha do snapshot. Agora: entrada de deploy distinta, modo de pesquisa preparado, etiqueta `research_participant` por sessão experimental e controles duplos de liberação. Não há alteração retroativa de linhas, datas ou fingerprints.

O protocolo já aprovado é reutilizado (`tcc-appendices-cd-v1`): A–E, familiaridade, até três prioridades antes do ranking e quatro respostas 1–5. Não se cria novo protocolo, nem se afirma que o checkbox seja TCLE. Documentos históricos de proposta continuam históricos; a autorização acadêmica informada pelo usuário não é reaberta.

**Default executável para smoke é sempre fictício:** `SIGRA_TCC_COLLECTION_MODE=homologation`, `SIGRA_RESEARCH_COLLECTION_ENABLED=false`, `research_release_authorized=false`. Só `.test`/`.invalid` passam na autenticação desse modo. O modo real requer, em etapa futura explicitamente liberada, ambos os gates verdadeiros e `mode=research`, no perfil/destino `research`, não no banco que contém TLS A/B.

Destino proposto de pesquisa no mesmo projeto já confirmado: banco **novo** `sigra_tcc_research`, roles novas `sigra_research_owner`/`sigra_research_runtime`. São nomes propostos, **não recursos já criados/confirmados**. O recibo externo exige OID real, CA e identidade antes de conectar. Preserva banco `sigra_revision6_homologation_test` e suas 19 execuções/15 questionários. A separação física e `environment_tag` impedem confundir smoke fictício com pesquisa; na análise, filtrar explicitamente o tag no `technical_record`. CSV permanece com 36 colunas, sem migração nem reescrita de exportadores.

## Destino recomendado e custos verificados

Não foi encontrado recibo de serviço público destinado ao TCC. `sigra-api-homolog.onrender.com` em `render.yaml` é configuração da demo antiga, não prova de serviço existente ou destino autorizado. Não reaproveitar seu bootstrap de 34 veículos.

Recomendação para uma rodada acompanhada: **um serviço Docker Render de 2 GB, React + FastAPI same-origin, Supabase existente**, preço-base US$25/mês (`1c-2g`). O plano de runtime pinado sozinho tem aproximadamente 192 MB serializados e sua representação em memória é maior; a imagem ainda precisa de medição de RAM sob carga antes da contratação. A opção de 512 MB custa US$7/mês (`0.5c-512mb`), mas não é considerada suficiente sem essa prova de memória. Esses valores são preço-base publicado, não orçamento fechado nem autorização de cobrança. Não contratar workspace pago/add-ons automaticamente.

Alternativa concreta: **Railway Hobby com a mesma imagem Docker e origem única**. A página oficial informa mínimo de US$5/mês, com US$5 de créditos de uso; excedentes de RAM/CPU/egress são cobrados. Não é preço fixo de US$5 nem Free. RAM publicada a US$0,00000386/GB/s, CPU a US$0,00000772/vCPU/s e egress US$0,05/GB. Configurar uma réplica e limite de memória compatível, revisar orçamento antes de contratar. Usa o mesmo PORT, comando e endpoints; domínio HTTPS, arquivos privados, proxy confiável e conectividade/TLS reais ainda precisam de validação nessa plataforma.

Render Free tem US$0 de compute, suspensão após 15 minutos e 750 horas/workspace/mês, mas foi **descartado para o artefato atual**: a verificação Windows de extração/carregamento atingiu 1.036.324.864 bytes de pico de working set, acima de 512 MB. Não é benchmark Linux nem teste de carga, mas não sustenta prometer funcionamento no Free/Starter512MB. O template de imagem propõe 2 GB para revisão, sem autorizar cobrança. A prova do container permanece pendente.

O template Vercel existente continua disponível como alternativa de frontend (Hobby US$0, uso pessoal não comercial; preços/limites oficiais devem ser confirmados no checkout). Ele não é a opção pronta desta entrega: frontend Vercel + API Render exigiria proxy same-origin ou domínios same-site e outra validação de cookies; o rewrite SPA antigo sozinho não encaminha a API. Nenhum domínio ou conta foi contratado.

Supabase Free publicado: US$0, 500 MB de banco, 5 GB de egress e pausa após uma semana inativo. Auth MAU do Supabase não mede participantes da autenticação própria. Auditoria existente de 10/10 registrou 55.719.603 bytes; **não é medição de 14/10 nem garantia para 100 testes**. Medir todos os bancos do projeto e egress no destino antes de liberar a rodada; não projetar quota usando somente quantidade de participantes ou tamanho de CSV. Nenhuma consulta de custos indisponível foi repetida.

Fontes oficiais consultadas em 14/10/2026:

- https://render.com/pricing e https://render.com/articles/production-rails-hosting-guide (preços de compute).
- https://render.com/docs/free (limitações, suspensão, horas e tráfego).
- https://render.com/docs/blueprint-spec e https://render.com/docs/docker (imagem por digest).
- https://supabase.com/pricing e https://supabase.com/docs/guides/database/connecting-to-postgres (quota e endpoints).
- https://supabase.com/changelog (índice Markdown não foi suportado pelo leitor; HTML conferido). Mudanças Data API/GraphQL não alteram esta arquitetura, que não usa esses serviços.
- https://vercel.com/pricing e https://vercel.com/docs/plans/hobby (alternativa de frontend).
- https://railway.com/pricing e https://docs.railway.com/networking/public-networking (alternativa Docker, custo variável e domínio HTTPS).
- https://uvicorn.dev/deployment/ (proxies confiáveis explícitos).

## Congelar e conferir o pacote offline

Na raiz real, usar Python 3.12 da `.venv-validation`. `prepare_tcc_release.py --help` mostra os quatro parâmetros obrigatórios; `--output` precisa ser caminho novo fora do repositório. `--bundle` e `--decision` são a extração Revision6 e decisão de nove já existentes; `--acceptance` é o recibo acima. O comando valida os planos existentes antes de copiar arquivos e não abre banco. Exclui `.env`, DPAPI, bancos, caches, PDFs, CSV de participantes, venv/node_modules e `tatus --short`.

```powershell
& '.\.venv-validation\Scripts\python.exe' -B scripts/prepare_tcc_release.py --output $releaseNovo --bundle $bundleRevision6 --decision $decisaoDeNove --acceptance $aceiteFuncional
& '.\.venv-validation\Scripts\python.exe' -B scripts/manage_tcc_deploy.py verify-release --release $releaseNovo
docker build --file "$releaseNovo\deploy\tcc.Dockerfile" --tag "sigra:$releaseId" "$releaseNovo"
docker image inspect "sigra:$releaseId" --format '{{.Id}}'
```

Não usar `docker build` diretamente no checkout sujo. Frontend usa `npm ci --ignore-scripts`, lockfile e Node22; backend usa Python3.12.14 e dependências diretas pinadas em `backend/requirements.txt`. Os dois digests das imagens-base foram confirmados na API pública oficial Docker Hub e estão fixados no Dockerfile. Pacotes transitivos Python não são um lock completo; congelar também o **digest da imagem final** e guardar inventário de pacotes do build. Não se afirma reprodução bit-a-bit de instalações transitivas ainda não congeladas. `pdfplumber` é dependência existente, não coleta externa no build/start.

Para publicar futuramente, com autorização e registry privado escolhidos:

```powershell
docker tag "sigra:$releaseId" "$registry/sigra:$releaseId"
docker push "$registry/sigra:$releaseId" # FUTURO: não executado nesta etapa
docker image inspect "$registry/sigra:$releaseId" --format '{{json .RepoDigests}}'
```

No Render: New Web Service → Existing Image → informar o digest imutável e credencial privada do registry. Revisar custo/plano antes de confirmar. `deploy/tcc-image.render.example.yaml` contém um endereço deliberadamente inválido, não é configuração aplicável sem preencher digest/segredos. Serviços de imagem não seguem `autoDeployTrigger`; não criar auto-updater. Não trocar esse fluxo por Git HEAD, pois o trabalho homologado ainda é local.

## Runtime, TLS e segredos

Preencher privadamente os nomes de `deploy/tcc.runtime.env.example`; não carregar `.env` por adivinhação nem enviar valores ao chat. O processo web só recebe `DATABASE_URL` runtime. URLs de migration são rejeitadas no web. Preservar a chave `SIGRA_RESEARCH_PSEUDONYM_KEY`; DPAPI do Windows não funciona como cofre no Linux: transferir a chave pelo canal privado do operador para o secret manager, sem incluí-la na imagem.

Instalar CA e recibo em secret files fora de `/app`, por exemplo `/etc/secrets/project-ca.crt` e `/etc/secrets/sigra-target.json`. Copiar `deploy/tcc.target.example.json`, conferir OID/endpoint/role/CA verdadeiros por preflight somente leitura e só então marcar `confirmed=true`, calcular SHA-256 e preencher `SIGRA_DEPLOY_TARGET_SHA256`. Nunca inferir um novo endpoint pela região. O único session pooler admitido é o já observado `aws-1-sa-east-1.pooler.supabase.com:5432`, tenant `tqlufobzzaabakflyxha`; direto admite somente `db.tqlufobzzaabakflyxha.supabase.co:5432`. Transaction/6543 e projetos antigos continuam rejeitados.

Exigir `sslmode=verify-full` e `sslrootcert` absoluto; CA parseada e hash pinado, libpq valida CA/hostname. Preflight real mede driver TLS e `pg_stat_ssl` no próprio PID separadamente. `ssl=false`, linha ausente e erro não viram aprovação. A resolução/acesso IPv4/IPv6 do futuro host ainda precisa ser observado; TLS local anterior não prova esse novo trecho. Não se flexibiliza upstream TLS.

Origem HTTPS exata deve ser igual em `SIGRA_PUBLIC_ORIGIN`/`CORS_ALLOWED_ORIGINS`; `ALLOWED_HOSTS` é seu host sem esquema. Cookie Secure/HttpOnly/Lax e CSRF permanecem. Informar `SIGRA_TRUSTED_PROXY_IPS` com IPs/CIDRs reais do proxy do host; `*` e redes /0 são rejeitados. Não adivinhar a faixa nem confiar em X-Forwarded-For público. Confirmar essa configuração com o provedor é uma pendência concreta. Usar **um worker/uma instância** nesta entrega; rate limit em memória não é distribuído.

Start efetivo: `python -B deploy/start_tcc.py`. Ele deriva versão do manifest, valida flags antes de abrir porta e usa a factory. Health publicado: `/sigra-api/health`; diagnóstico de banco: `/sigra-api/health/database`. Docs/OpenAPI públicos ficam desligados. Não há migration, seed, FIPE, CarPedia ou import na inicialização.

## Preparação de banco futura — nada foi aplicado

Não é necessária migration de schema nova: `environment_tag` já existe em 0015 e comporta `research_participant`. Migrations históricas continuam intactas. Banco novo de pesquisa requer aplicar a cadeia existente até `20261007_0015` em outro destino confirmado, não fazer downgrade/reset no homologado.

Procedimento revisável para o operador, somente após aprovar separadamente os novos nomes/recursos e confirmar o projeto:

1. Criar as duas roles propostas com LOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, NOREPLICATION e sem memberships; definir senhas ocultas no terminal (`\password`). Criar `sigra_tcc_research OWNER sigra_research_owner`. Não reutilizar contas TLS A/B.
2. Conferir destino novo/vazio por SQL somente leitura, endpoint/role/CA e TLS antes do primeiro DDL; guardar recibo externo com OID. Ainda não existe esse recibo nem essas credenciais nesta preparação.
3. Em terminal **de migration**, configurar privadamente `SIGRA_RESEARCH_MIGRATION_URL` para o owner novo e `DATABASE_URL` para runtime novo, ambos verify-full. Não herdar o ambiente do banco de homologação. Manter coleta desligada e recibo research/OID confirmado; não definir URL de migration no web.
4. Usar `python -B scripts/manage_tcc_deploy.py migrate-new --release $releaseNovo --confirm-database sigra_tcc_research`. O helper valida as duas roles, banco/OID/TLS e ausência de relações antes de chamar a cadeia Alembic existente até 0015; não usar um comando Alembic genérico sobre uma URL não guardada. Parar em qualquer falha; sem downgrade/retry automático.
5. Como owner do novo banco, executar `psql --set ON_ERROR_STOP=1 --dbname 'service=sigra_research_owner' --file deploy/research-grants.sql`, com pg_service.conf privado que aponta **somente ao novo banco**. O SQL recusa outro banco/owner/revisão, tabelas privadas preenchidas ou hardening prévio. Grants/RLS são separados da cadeia Alembic, sem Supabase Auth.
6. Retirar a URL genérica de migration do processo. Configurar `SIGRA_RESEARCH_MIGRATION_URL` só no terminal da materialização, e o runtime/example com perfil research, coleta desligada. Depois da revisão dos guards, executar:

```powershell
python -B scripts/manage_tcc_deploy.py materialize-new --release $releaseNovo --confirm-database sigra_tcc_research
# O segredo owner é removido antes de iniciar web. Auditoria é somente leitura:
Remove-Item Env:SIGRA_RESEARCH_MIGRATION_URL
python -B scripts/manage_tcc_deploy.py audit --release $releaseNovo
```

Materialização verifica runtime sem privilégios, todas as tabelas privadas vazias e snapshots ausentes; no owner verifica banco/role/OID/TLS e trava transacional antes dos dois snapshots. Divergência provoca rollback. Se já existem snapshots/registros, usar somente `audit`, nunca importar para repará-los. O script de preparação nova não foi executado em PostgreSQL nesta rodada e precisa de ensaio no novo destino antes de ser considerado homologado. Não copiar nem limpar os 19 registros fictícios.

## Backup, restauração e rollback

Backup inclui hashes de senha/sessões: é sigiloso, não acompanha este ZIP. Preparar pg_service.conf/pgpass privadamente, CA verify-full e serviço de backup com acesso legítimo a todas as linhas sob FORCE RLS. Runtime web não é credencial de backup; owner sem BYPASSRLS pode não conseguir dump completo. Usar operador autorizado no banco exato, não alterar policies para fazê-lo passar. Validar no terminal identidade/banco e role antes de `pg_dump`.

```powershell
# FUTURO, em terminal privado; $backupNovo é caminho novo, privado e criptografado.
if (Test-Path -LiteralPath $backupNovo) { throw 'Backup já existe; não sobrescrever' }
pg_dump --dbname 'service=sigra_research_backup dbname=sigra_tcc_research sslmode=verify-full' --format=custom --no-owner --no-acl --file $backupNovo
if ($LASTEXITCODE -ne 0) { throw 'Backup não aprovado' }
Get-FileHash -LiteralPath $backupNovo -Algorithm SHA256
pg_restore --list $backupNovo
```

Registrar revisão 0015, release ID/digest, UTC, contagens por tabela, fingerprints dos snapshots e tamanho; restringir ACL/acesso e aplicar retenção já aprovada. Ensaiar restore em `sigra_tcc_restore_test`, **outro banco vazio e descartável**, nunca no ativo. Antes de restore, SQL deve comprovar nome exato e ausência de relações de aplicação; divergência interrompe. `--no-owner --no-acl` exige reaplicar os grants/RLS apropriados e auditá-los; não declarar permissões restauradas só pelo exit code.

```powershell
pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname 'service=sigra_restore_disposable dbname=sigra_tcc_restore_test sslmode=verify-full' $backupNovo
```

Sem `--clean`, sem drop/reset/downgrade. Comparar restauração com manifest/contagens/hash de payloads, revisão, FKs/órfãos, 60/1.080 **por snapshot**, e logs/exportação pseudonimizada. Medir backup/egress no limite Free. Este ensaio não foi executado.

Rollback de aplicação: suspender novas entradas no destino publicado, manter coleta desligada, selecionar no Render a imagem anterior **pelo digest registrado** ou substituir o digest no serviço. Preservar banco/volumes/chave, executar health/versão/isolamento no mesmo host e registrar resultado. Nenhum comando Git destrutivo ou downgrade. Se não houver imagem anterior compatível, manter manutenção e restaurar somente em outro banco por plano revisado. Nunca usar a demo antiga como fallback automático.

## Roteiro de aceite online, ainda pendente

Primeiro publicar somente configuração fictícia. No host final: conferir `/sigra-api/health` e banco/Alembic0015; confirmar project/database/role/OID/TLS/grants/RLS, 60/1.080 por snapshot, fingerprint V6/Revision6 e Base/Ampliada. Confirmar frontend sem localhost e sessões via cookie Secure/HttpOnly/Lax, CSRF, CORS e hosts; executar o fluxo com duas contas fictícias e admin existente daquele destino, sem promover participante.

Conferir parâmetros/pesos/cenário/lote, desconhecidos, histórico/atualização, 404 cruzado, 403 de exportação para participante e 200 administrativo, parsing de36colunas e revisão do texto livre. Comparar contagens antes/depois e preservar registros sem questionário. Reiniciar **apenas a API publicada** pelo host e conferir persistência/versão/pseudonimização. Isso é verificação no novo ambiente, não repetição retroativa da prova local A–E.

Antes da coleta real: encerrar smoke fictício, preparar recibo da liberação técnica do perfil research no destino separado e só então revisar ambos os gates de coleta com autorização específica. A autorização acadêmica já aprovada é mantida; não basta renomear uma flag. Nesta etapa nenhum gate foi armado e nenhum serviço foi publicado.
