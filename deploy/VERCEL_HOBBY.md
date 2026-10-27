# SIGRA — candidata Vercel Hobby, exclusivamente fictícia

## Estado e escopo

Candidata separada da release `sigra-e2217c7cec76bbeeb6112d9b` e da imagem
`sha256:5648f57624ca2d0f95fc3c70fc2642ea926b6fba5ecd77234a33cb30980a7916`.
A identidade dos bytes novos está em `release/manifest.json`; não é a imagem
homologada. Sem publicação, vínculo Vercel, banco novo ou validação remota nesta
preparação. A coleta real é recusada explicitamente pelo adaptador.

Os mesmos 60 IDs, plano de 1.080 avaliações por snapshot, V6/Revision6,
configurações Base/Ampliada, regras, custos, pesos e desconhecidos permanecem.
Base: 10/60/10/24/9/9; Ampliada: 0/8/0/3/8/8, por perfil, na ordem Cidade,
Aplicativo, Trabalho, Espaço, Família, Estrada. Documentação completa não é
presença de todo equipamento nem pontuação completa. Focus 80 continua sem
massa; Fiesta 44 tem ESC ausente; Tiguan 70 permanece bloqueado. Não houve
coleta documental ou migração. O aceite histórico continua restrito a um campo,
com `historical_row_changed=1`, origem desconhecida e sem preservação histórica
integral. O aceite e o plano mantêm os bytes e hashes originais.

## Limites consultados em 15/10/2026

Fontes oficiais:

- [Hobby](https://vercel.com/docs/plans/hobby): gratuito para uso pessoal não
  comercial; quotas mensais de 4 CPU-h, 360 GB-h, 1 milhão de invocações,
  100 GB de transferência CDN e 10 GB de origem. São quotas, não capacidade
  simultânea garantida. Ao esgotar, pode haver indisponibilidade até renovação.
- [Functions](https://vercel.com/docs/functions/limitations): Hobby Fluid
  Compute, 2 GB/1 vCPU, até 300 s, corpo de requisição/resposta de 4,5 MB;
  Python padrão até 500 MB descompactados. Não habilitar large-functions beta
  nem contratar Pro para contornar limites sem nova decisão.
- [Python](https://vercel.com/docs/functions/runtimes/python) e
  [FastAPI](https://vercel.com/docs/frameworks/backend/fastapi): ASGI/lifespan,
  Python 3.12, dependências nativas precisam ser Linux. O encerramento tem janela
  curta; persistência fica no PostgreSQL, não depende do shutdown.
- [Filesystem](https://vercel.com/docs/functions/runtimes): código somente
  leitura, scratch `/tmp` até 500 MB, env total até 64 KB. O plano é lido do
  bundle, não copiado para `/tmp`. Apenas CA e recibo são temporários.
- [Rotas](https://vercel.com/docs/functions/runtimes/python/api-directory) e
  [configuração](https://vercel.com/docs/project-configuration/vercel-json):
  preset Vite explícito + uma Function Python em `api/index.py`.
- [Conexão PostgreSQL](https://supabase.com/docs/guides/database/connecting-to-postgres):
  session pooler porta 5432 permite IPv4 e conexões de sessão, com usuário
  `ROLE.PROJECT_REF`; endpoint vem de Connect, nunca inferido pela região.
  Serverless pode congelar sockets. O adaptador usa NullPool para fechá-los a
  cada sessão. Não altera o pool dos inicializadores existentes.

O teste anterior em 2 CPUs NÃO demonstra latência equivalente em 1 CPU. Os
17,3 s sequenciais/38,7 s com concorrência dois e pico 1.378.684.928 bytes são
da imagem Linux anterior, não desta Function. As medições Windows com afinidade
de uma CPU usam repository offline: não incluem consultas, auditorias, rede,
runtime Vercel, TLS real ou inicialização integral da factory. Não servem para
dimensionar uma turma simultânea. Fazer teste remoto controlado antes de abrir
mais participantes, sem otimização metodológica nesta rodada.

## Transporte e consumidores

O cliente pede `X-SIGRA-Transport: sigra-json-dictionary-v1`. O middleware
transforma somente JSON 2xx grande, depois de autenticação e persistência.
Objetos/listas repetidos viram referências tipadas. A expansão recompõe TODOS
os campos e sua ordem sem compartilhamento mutável de objetos. Não é gzip,
projeção, truncamento, imputação ou recálculo. Clientes sem opt-in conservam a
resposta antiga, que pode exceder a Vercel; usar o frontend desta candidata.

Resultados, diagnósticos, critérios, fontes, explicações e fichas continuam
consumidos pelos componentes existentes. `record_result` persiste o objeto
completo original; fingerprints são calculados antes do transporte. Histórico
compacto de listagem continua o aprovado; detalhes completos exigem dono e
usam o mesmo codec. Não há armazenamento da resposta compacta no banco.
Acima do orçamento de 4.000.000 bytes o caminho Vercel opt-in falha
explicitamente, sem truncar; se houver recibo salvo ele é preservado na resposta.
Consultar o histórico antes de repetir uma operação potencialmente gravada.

O CSV completo antigo é mantido no backend como referência, mas não deve ser
baixado diretamente pela Function por causa do limite de corpo. O botão usa
manifesto administrativo somente leitura e uma linha por GET, cada um protegido
por `require_admin`. Preserva as mesmas 36 colunas, BOM UTF-8, CRLF, quoting,
comentários, células vazias/zeros e tokens JSON exatos, inclusive `17.0` e
ordenação de chaves numéricas. O navegador verifica SHA de cada linha e do CSV
inteiro antes de baixar. Mudança concorrente retorna 409: nenhum arquivo
inconsistente é aceito, sem retry, alteração de referência ou exclusão de registros.
O manifesto não é token de autorização. Exportações muito maiores ainda precisam
ser medidas; nada é agregado ou removido para caber.

## Empacotamento, build e ASGI

A pasta de projeto gerada é `project/`, contendo `api/index.py`, `vercel.json`,
`requirements.txt`, `.python-version` e `application/` (fonte fixado completo).
As dependências da Function ficam fora de `application/`; assim o verificador
original do conjunto exato de arquivos continua válido. `node_modules` não vai
para a Function. Não flexibilizar `verify_release` para aceitar bundle faltante.

Configuração: preset Vite explícito; npm ci pelo lock; build força apenas
`VITE_API_URL=/sigra-api`, flags públicas false. Assets/SPA servidos pelo CDN;
API primeiro em `/sigra-api/:path*` → `/api`, sem redirecionamento de origem.
Fallback da SPA não captura API/assets. O prefixo original é preservado no ASGI;
composição real do rewrite ainda exige smoke da plataforma. Não servir o código,
plano ou templates como arquivos estáticos; output público é apenas frontend/dist.

Não existe listener/PORT/Uvicorn subprocess na Function. O FastAPI shell não
abre conexão ao ser importado. No lifespan, materializa CA/recibo em scratch
restrito, valida settings/manifest e executa o lifespan da factory original:
TLS cliente e backend do PID próprio, CA/hostname, OID/role, Alembic0015,
grants/RLS e snapshot. Sem esses gates não serve requisições. Não há DDL, seed,
materialização ou chamada de coleta no startup. Não depender de arquivos
persistentes locais nem de hash/cache em disco mutável.

O caminho Vercel não usa o ProxyHeadersMiddleware TCP do Uvicorn. Não confiar em
`X-Forwarded-*` arbitrário ou inventar CIDRs. Exige `scope.scheme=https` e Host
exatamente iguais à URL confirmada. Se o adaptador Vercel não os entregar assim,
o teste deve bloquear e diagnosticar o contrato, não ativar wildcard nem forçar
scheme sem evidência. Cookies Secure/HttpOnly/Lax, CSRF e CORS exatos continuam.
Cada preview precisa de hostname explícito, sem `*.vercel.app`. O domínio
gratuito do provedor é suficiente; compra de domínio/registry não é necessária.

## Preenchimento privado — ainda não executável remotamente

1. Em etapa autorizada, definir o projeto Vercel **Hobby pessoal não comercial**,
   sem Git auto-deploy, e anotar a URL exata fornecida. Não publicar ainda.
2. Autorizar/provisionar separadamente `sigra_tcc_research` e
   `sigra_research_runtime`, com owner/migration fora do web, no projeto Supabase
   confirmado. Apesar do nome, esta implantação continua **fictícia**. Não ler,
   copiar ou migrar o banco TLS A/B. Reutilizar os comandos de provisão/auditoria
   preparados, após gate de novo/vazio, sem migrations históricas modificadas.
3. Registrar recibo real/OID/endpoint de Connect/CA/grants/Alembic0015. O relatório
   `ssl-enforcement-test-20261009/result.json` comprova TLS nos dois trechos em
   conexões posteriores à ativação, mas somente no destino antigo: não dispensa
   nova verificação. Não se reutiliza o diagnóstico ssl=false anterior nem se
   presume upstream certificado auditado por `pg_stat_ssl`.
4. Preencher privadamente os nomes de `vercel.runtime.env.example` no painel de
   variáveis. Não usar shell history/argv, `VITE_*` ou Git para segredos.
   DATABASE_URL usa runtime novo, senha percent-encoded, `verify-full` e token
   literal `sslrootcert=SIGRA_CA_FILE`, substituído somente pelo caminho da CA
   fixada. Base64 da CA/recibo preserva os bytes exatos; NÃO cifra esses dados.
   Hash SHA-256 do recibo em SIGRA_DEPLOY_TARGET_SHA256; ca_sha256 dentro dele.
   O template UNCONFIGURED não é recibo e não deve receber confirmed=true sem
   provas. Chave pseudônima estável do dataset novo fica em backup privado.
5. Revisar a candidata e executar build Vercel local após vínculo explícito
   autorizado. CLI Vercel não estava disponível nesta preparação; não foi
   instalado/vinculado projeto silenciosamente. O build Vite local não substitui
   a construção da Function nem prova bundle final, rotas ou runtime Linux.
6. Só após autorização de publicação: preview fictício e smoke online com
   contas novas desse destino: HTTPS, cookies/CSRF, /sigra-api/health, metadados
   60/1080 e fingerprints, Base/Ampliada e pesos, propriedade, exportação e
   persistência após cold start. Não repetir contra o banco de homologação local.
   Registrar memória/CPU/latências/corpos e quotas na Vercel antes de ampliar uso.

Não há comando de preview aplicável sem hostname, recibo/OID/CA/runtime novos e
autorização de provisionamento/publicação. Templates vazios falham fechados.
Não pedir novamente decisão de Render/Railway, registry ou autorização acadêmica.
O que falta é infraestrutura e validação da candidata no destino escolhido.

## Reversão e proteção

Preservar ZIP/imagem originais e relatórios. Nenhum banco/conta foi acessado
nesta preparação. A–E, 403 e CSV anteriores são reutilizados como referência,
não reexecutados nem apresentados como validação da Function.

Antes de dados reais, backup privado do destino novo, com identidade/TLS
confirmados e role apropriada; restaurar somente em outro banco vazio e auditar
contagens/FKs/fingerprints/grants. Comandos e cuidados em TCC_DEPLOY_PREPARATION
continuam válidos; não aplicar reset/downgrade no banco ativo. Não exportar
backups para logs, ZIP de código ou browser público.

Rollback inicial: desabilitar o preview/novas requisições preservando banco e
chave. Não apontar ao banco antigo nem fingir que a imagem Docker é uma Function
Vercel anterior. Só alternar release depois de validar compatibilidade real.
