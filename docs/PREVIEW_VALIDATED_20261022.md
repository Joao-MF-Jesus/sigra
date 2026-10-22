# Preview fictício validado — consolidação de fontes

STATUS=PREVIEW_DEPLOYED_AND_BASIC_FLOW_VERIFIED

Release: `sigra-be98bd5b78ce6ddd81592d08`.
Deployment: `dpl_2DDsiQ61tuB8WNB2qpZ7nQQFQdus`.
[URL protegida](https://sigra-neon-preview-ficticio-4k3n5kawz.vercel.app).
Estado documentado em 22/10/2026: READY/Preview, Vercel Hobby + Neon Free.
Não há promoção para produção, liberação da coleta real ou novo deploy por esta consolidação.

## O que foi comprovado

Smoketest HTTP/API no perfil autorizado: frontend/health 200, PostgreSQL
acessível, Alembic `20261007_0015`, 60 veículos, snapshot
`4539918b-b64e-4f2a-b331-d8bb0ee68924`, fingerprint da coorte
`55ab70a71119e31d0f2654f14d207daa1ab2481a0b33b568ca7066fd8f1b6a34`.
Cadastro/login normal, sessão reconhecida, escolhas antes do resultado, uma
recomendação, quatro avaliações, histórico próprio e igualdade do detalhe
em novo cliente HTTP. Exportação administrativa negada ao participante (403).

Contador no recibo final: 1 tentativa, 1 sucesso, 0 incertas, saldo 29/30.
É ledger operacional, não prova de rate limit instalado. Não autoriza consumir
o saldo automaticamente. Recomendação: 33,657 s, resposta HTTP 2.401.094 bytes;
38 statements, 53.598.232 bytes de campos SQL, que **não são egress do provedor**.

Não foram comprovados por esse smoke: navegação visual, isolamento remoto entre
duas contas, CSV administrativo desse banco novo, carga, restauração ou produção.
Os testes locais anteriores A–E/CSV valem para seu ambiente, não substituem esses
critérios remotos. Melhorias de desempenho e fotos são trabalhos futuros separados.

## Correspondência exata e diferenças deliberadas

[correspondence.json](../deploy/published/correspondence.json) relaciona cada
arquivo da aplicação congelada ao caminho versionado e a ambos os SHA-256.
451 arquivos públicos foram comparados. A documentação de frontend teve somente
dois caminhos pessoais substituídos por instruções portáveis; a diferença consta
no mapa. Os fontes executáveis publicados não foram refatorados.

O ZIP original tem SHA-256
`1e3e7688e4bf0309ca32a8257e165dd7b169f5c81f169f5d1469ed59da24c016`.
O upload efetivo difere dele **apenas no vercel.json externo**, pelo overlay pv22:
`includeFiles` é string (união de globs), não lista. Seu SHA-256 é
`13189e0531a8b566bf0be6b2938f33b9b6a32a5cba56cf1a96abe9cd754c80ae`.
O arquivo efetivo está em `deploy/published/project/vercel.json`; não usar uma
configuração antiga do pacote como raiz de novo upload.

O projeto enviado tinha `application/` separado das dependências da Function.
Neste Git os fontes canônicos continuam em `backend/`, `frontend/`,
`data_platform/`, `scripts/` e `deploy/`. Os quatro wrappers/manifestos externos
ficam em `deploy/published/project/`. Essa pasta **não é um projeto completo
para deploy direto**: falta montar o application congelado.

Seis artefatos do manifesto não são publicados aqui: dois recibos privados,
plano comprimido, dois resíduos de test-results e configuração interna original.
Seus hashes permanecem no mapa, sem publicar conteúdo. O catálogo e seus fontes
de evidência continuam em `data_platform/`; o plano operacional exato permanece
no arquivo selado local. Isso evita publicar caminhos privados, configuração
operacional ou temporários. Não se enfraqueceu o guard de conjunto exato.
O checkout público sozinho não recebe a identidade do ZIP nem pode passar
automaticamente pelo guard da release congelada. Alterações futuras precisam de
novo manifesto/candidata e validação; nunca atualizar o manifesto antigo para
acompanhar diferenças.

`.gitattributes` preserva os bytes dos fontes mapeados, inclusive finais de linha,
pois o runtime compara hashes. O primeiro commit desta consolidação preserva
o estado local prévio; o seguinte aplica os fontes efetivamente publicados.
Três stashes e os artefatos originais permanecem locais e não são publicados.

## Instalação e checks locais

Use Python 3.12 e uma versão Node compatível com o lock do frontend. Em ambiente
novo e isolado, sem importar variáveis privadas de banco:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci --ignore-scripts
& .\.venv\Scripts\python.exe scripts/verify_published_sources.py
npm --prefix frontend test
npm --prefix frontend run build
```

Para o build same-origin do pacote Vercel, o comando congelado é
`node application/deploy/build_vercel.mjs`, executado **na pasta preparada**
com application completo, após `npm --prefix application/frontend ci --ignore-scripts`.
O script fixa `VITE_API_URL=/sigra-api` e as flags públicas falsas.
O entrypoint externo é `api/index.py`, ASGI, sem criar banco no import.
As 10 dependências diretas e 39 constraints estão no pyproject publicado;
os requirements preservam a sintaxe corrigida para o builder Python.

Para desenvolvimento de UI sem usar o Preview remoto:
`npm --prefix frontend run dev -- --host 127.0.0.1`.
O backend operacional exige destino isolado e configuração própria revisada;
não é iniciado por este guia. Migrations, materialização e provisionamento não
fazem parte de instalação/build nem de startup automático do Preview.

## Configuração privada (somente nomes, nunca valores)

Templates não configurados em `deploy/vercel.runtime.env.example`,
`deploy/neon.runtime.env.example` e arquivos `*.UNCONFIGURED.json`.
Os valores de exemplo não são configuração válida nem recibos de identidade.

- Runtime: `DATABASE_URL`, `DATABASE_ENV`, `DATABASE_SSL_REQUIRED`,
  `DATABASE_BOOTSTRAP_SCHEMA`, `SIGRA_VERCEL_ENABLED`, `SIGRA_DEPLOY_ENABLED`.
- Identidade: `SIGRA_SYSTEM_VERSION`, `SIGRA_DEPLOY_PLAN_SHA256`,
  `SIGRA_DEPLOY_TARGET_SHA256`, `SIGRA_VERCEL_TARGET_B64`,
  `SIGRA_VERCEL_EXPECTED_PROJECT_ID`, `SIGRA_VERCEL_EXPECTED_TEAM_ID`.
- Transporte/origem: `SIGRA_VERCEL_CA_B64`, `SIGRA_NEON_TRANSPORT_MODEL`,
  `SIGRA_NEON_TRANSPORT_ACCEPTANCE_SHA256`, `SIGRA_VERCEL_ORIGIN_MODE`,
  `SIGRA_PUBLIC_ORIGIN`, `SIGRA_VERCEL_EXACT_HOST`, `CORS_ALLOWED_ORIGINS`,
  `ALLOWED_HOSTS`, `SIGRA_COOKIE_SECURE`, `SIGRA_COOKIE_SAMESITE`.
- Proteções: `SIGRA_RESEARCH_PSEUDONYM_KEY`, `SIGRA_TCC_COLLECTION_MODE`,
  `SIGRA_RESEARCH_COLLECTION_ENABLED`, `ACADEMIC_COHORT_ENABLED`.

Consulte o código/template para demais flags. Nunca copiar credenciais operador
para runtime, valores privados para VITE_ ou segredos para Git. TLS cliente,
hostname/CA, SNI, channel binding e identidade do destino continuam exigidos.
Aceites de transporte gerenciado, memberships e atributos do operador são
restritos ao preview/projeto original, não templates de privilégios gerais.
`pg_stat_ssl.ssl=false` continua evidência; proteção interna é garantia documental,
não TLS observado pelo PostgreSQL. Nenhum aceite habilita coleta real.

## Ressalva histórica preservada

`historical_row_changed=1`. O aceite funcional histórico se limita ao campo
`questionnaire_at` do registro pseudonimizado `RUN-f05b43ca0998deaa`, de
`2026-10-09T20:22:23.074813+00:00` para `2026-10-10T14:45:56.306172+00:00`.
Origem desconhecida; não se declara preservação histórica integral. Nenhum dado
histórico foi copiado para o Preview novo. Os aceites originais continuam privados.

## Evidências reutilizadas

Build Linux: Function de 134.276.292 bytes; ZIP de 53.591.009 bytes,
SHA-256 `661849a7789e75f529d5053902dcd6b353129569ca27c32cef5c3fc134eadf27`.
15 testes e auditoria nativa aprovados, sem repetição na consolidação.
O build remoto e o smoke HTTP são evidências distintas dessa validação local.
O manifesto público registra os hashes dos relatórios sanitizados usados, sem
publicar recibos de autenticação. Não foi feito novo deploy por commit/tag.

Checks desta consolidação: correspondência de 451 arquivos públicos e cinco
arquivos externos; parsing AST de 231 fontes Python; 10 dependências e 39
constraints preservadas; build Vite aprovado; 234 testes frontend aprovados;
54 testes Python focais e seis regressões do verificador aprovados. A primeira
tentativa Python teve 34 erros de fixture por criação da pasta temporária do
perfil isolado; a execução completa passou com basetemp novo e explícito, sem
mudança da aplicação. Não foi executada a suíte PostgreSQL remota nem repetido
qualquer fluxo autenticado do Preview. Os checks locais não ampliam a evidência
funcional remota já registrada.
