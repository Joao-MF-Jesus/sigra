# Preview fictício: Vercel Hobby + Neon Free — transporte gerenciado aceito

Aceite separado em release/neon-transport-acceptance.json: somente projeto
young-haze-62223574, branch br-icy-frog-b6jetlre, endpoint ep-round-glade-b6bhigmc,
organização org-morning-wave-65946706, Free. O usuário autorizou provisionamento
isolado e publicação exclusivamente Preview Vercel Hobby. Isso não aprova build,
conexão ou smoke remoto ainda não executados. Coleta real permanece falsa.

Seleção obrigatória e coincidente no recibo e ambiente:
SIGRA_NEON_TRANSPORT_MODEL=neon-managed-preview-v1 e pin do aceite. Não há fallback.
O modo strict-postgresql-tls-v1 continua exigindo ssl=true no próprio PostgreSQL.
No modelo aceito, cliente→endpoint é observado; proteção interna é garantia
documental do provedor, mecanismo específico não comprovado. ssl=false permanece
false no relatório; isso NÃO é equivalente a TLS constatado pelo PostgreSQL.

## Identidades propostas e isolamento

- Organização já observada: org-morning-wave-65946706, Free. Não criar outra conta.
- Projeto novo proposto: `sigra-tcc-preview-ficticio`, PostgreSQL **17**, AWS São
  Paulo `aws-sa-east-1`, uma branch raiz e um endpoint. Os IDs reais vêm do painel,
  não dos nomes. Antes da criação, inventariar recursos/assinatura para evitar
  duplicação. Se o painel oferecer região/plano diferentes, parar para revisão.
- Banco separado: `sigra_tcc_research`, proprietário `sigra_research_owner`,
  aplicação `sigra_research_runtime`. Nomes herdados do contrato de deploy NÃO
  significam coleta real: purpose=fictitious_preview, modo=homologation e
  SIGRA_RESEARCH_COLLECTION_ENABLED=false são obrigatórios.
- Nenhum dado, usuário, sessão, chave de pseudonimização ou credencial dos bancos
  anteriores será importado. Somente plano acadêmico fixado e contas fictícias
  novas, quando a próxima etapa for autorizada. Supabase permanece intocado.

## Orçamento e limites verificados documentalmente

O Free publicado é US$0, sem prazo de trial/cartão. São 100 CU-h/projeto/mês,
1 GB PostgreSQL/projeto (20 GB na conta), 5 GB egress/projeto/mês e suspensão
após 5 min inativos. Compute Free até 2 CU/8 GB, dez branches por projeto;
monitoramento retido por um dia. Exaurir compute/egress suspende acesso até
renovação/upgrade; armazenamento cheio impede escritas (inclusive DELETE), não
resolve apagar por SQL sem espaço. Não fazer upgrade automático ou contornar
limites criando projetos. Conferir condições efetivas no painel antes de criar.

Fonte de quotas atual: [planos](https://neon.com/docs/introduction/plans).
Preços: [Neon pricing](https://neon.com/pricing). Blogs antigos com 0,5 GB/20
projetos não substituem a tabela atual. Launch/Scale são medidos e não autorizados;
ativar serviços adicionais, upgrade ou backup tarifado exigiria nova revisão.
Não usar Neon Auth/Functions/Storage/AI: FastAPI conserva autenticação própria.

Proposta inicial: compute fixo 0,25 CU, se o controle do Free permitir; registrar
o máximo realmente configurado. 0,25 CU por 10 h ativas = 2,5 CU-h, por 400 h =
100 CU-h. Autoscaling eleva consumo; não prometer 400 h com máximo 2 CU. Não
instalar keepalive/cron que impeça scale-to-zero. CPU/RAM Neon são do banco, não
substituem o consumo de 1,38 GB da aplicação Linux nem dimensionam Vercel.

## Conexões e TLS: gates anteriores a qualquer DDL

Copiar o endpoint **direto, não PgBouncer**, de Connect, porta 5432. Não derivar
hostname por região, não usar endereço IP como host nem PGHOSTADDR. A plataforma
documenta conectividade IPv4/IPv6, mas DNS A/AAAA e TCP do endpoint real ainda
foram medidos pelo operador; repetir apenas o gate necessário sob o novo modelo,
reutilizando DPAPI. Conectividade a partir da Vercel continua pendente.

Psycopg 3/libpq com SNI (libpq>=14) é compatível documentalmente. O ambiente local
inspecionado tem psycopg 3.2.3/libpq 140012; registrar também a versão da Function.
Exigir parâmetros exatos `sslmode=verify-full`, `sslsni=1`, `channel_binding=require`, `sslrootcert` para CA
real. A documentação indica Let's Encrypt ISRG Root X1, obtida da autoridade:
[CA](https://letsencrypt.org/certs/isrgrootx1.pem),
[TLS Neon](https://neon.com/docs/connect/connect-securely). Validar bytes/certificado
real, vigência, hostname e pin SHA-256; não inventar CA/recibo ou aceitar require.

Mesmo a conexão chamada direta passa pelo proxy Neon. Primeiro, no novo projeto
confirmado, conectar ao banco inicial com operador e consultas SOMENTE LEITURA:

```sql
SELECT current_database(), current_user,
       (SELECT oid FROM pg_database WHERE datname=current_database()),
       b.pid, s.pid, s.ssl, s.version, s.cipher
FROM (SELECT pg_backend_pid() AS pid) b
LEFT JOIN pg_stat_ssl s ON s.pid=b.pid;
```

Registrar somente identidade pública sanitizada, linha encontrada, ssl, versão e
presença de cipher; nunca URI/senha. Driver ssl_in_use e parâmetros efetivos
comprovam cliente→endpoint; a linha do próprio PID comprova o trecho observado
pelo PostgreSQL. Não são prova criptográfica de canal ininterrupto entre ambos.
Linha ausente, valor desconhecido, PID incorreto ou erro de consulta NÃO aprovam.
ssl=false bloqueia no modo estrito. No modelo gerenciado, o aceite exato permite
prosseguir preservando false/null/sem cipher e a distinção documental acima.
Nenhum fallback para pooler, Supabase ou sslmode=require está implementado.
A documentação pública não é evidência empírica de TLS no backend observado.

PgBouncer Neon é transaction mode: não aprovado nesta candidata. SET de sessão,
opções de startup, cursores/streaming CSV, DDL e administração exigem revisão
própria. Prepared statements de protocolo suportados não resolvem toda essa
semântica. Vercel mantém NullPool e fecha conexões; isso NÃO limita autoscaling
global. A tabela atual dá 104 conexões em 0,25 CU, sete reservadas:97 disponíveis,
não 10.000 consultas simultâneas. Smoke inicial: concorrência máxima dois.
[Pooling](https://neon.com/docs/connect/connection-pooling).

## Provisionamento futuro: ordem e fronteiras de autorização

DDL autorizado somente no destino novo exato, após preflight real completo.
Antes de qualquer escrita, inventariar nomes e reconciliar existência parcial.
Falha ou resultado incerto bloqueia sem retry. A ordem continua:

1. Inventariar plano, projetos, região, quotas e configurações; confirmar a nova
   identidade. Criar somente o projeto acordado, caso ausente, sem adicionais.
2. Confirmar endpoint, CA, TLS cliente e backend somente leitura, como acima.
3. Operador Neon (credencial administrativa efêmera, nunca na Function): criar
   as duas roles por **SQL**, LOGIN e NOSUPERUSER NOBYPASSRLS NOCREATEDB
   NOCREATEROLE NOREPLICATION, sem associação a neon_superuser. Roles criadas pela
   Console/API recebem neon_superuser; não usá-las para owner/runtime do SIGRA.
   Usar senha aleatória forte e entrada oculta/local aprovada; sem literais de
   senha em script, argumento, relatório ou editor SQL com histórico.
4. Criar somente o banco novo, UTF8, owner exato, revogar CONNECT/TEMP de PUBLIC,
   permitir CONNECT apenas às roles previstas. Nenhuma criação se o nome existir.
   CREATE DATABASE não é transacional: em falha parcial inventariar e parar, não
   apagar/recriar automaticamente. Operador pode precisar associação temporária
   ao owner para atribuir ownership; retirar e conferir ao final. As roles alvo
   não podem herdar privilégios de operador.
5. Gerar uma UUID uma única vez para comentário `sigra-neon-preview-v1:<UUID>`;
   COMMENT ON DATABASE via parâmetro/identifier SQL seguro; obter OID real. Ler
   novamente com pg_catalog.shobj_description (catálogo compartilhado). Esses
   dados são identidade, não uma referência inventada para liberar o guard.
6. Confirmar owner e runtime mínimos, zero relações não-sistema no banco novo;
   registrar recibo externo real e pin. Não instalar extensões irrelevantes ou
   segunda cadeia de migrations. Os scripts históricos seguem intactos.

Os comandos seguintes são reais, **somente futuros**, a partir de application/,
depois de preencher privadamente e confirmar todos os campos abaixo:

```powershell
python -B scripts/inspect_neon_preview.py --phase empty
python -B scripts/manage_tcc_deploy.py migrate-new --confirm-database sigra_tcc_research
```

Antes de inspect --phase empty, manter a variável de migration AUSENTE; fornecê-la
somente ao processo manager. O manager exige runtime e owner no mesmo destino/CA e revalida vazio antes de
Alembic até `20261007_0015`. Em seguida executar o arquivo existente
`deploy/research-grants.sql` no banco novo **conectado como sigra_research_owner**,
nunca pelo provisionador nem no Supabase. Seu gate exige current_user=owner;
o arquivo não cria roles nem exige CREATEROLE. Usa roles fixas; anon/authenticated
só são revogados quando existentes. Não conceder BYPASSRLS ao runtime. Ele recebe
CRUD apenas nas tabelas privadas necessárias, políticas RLS/FORCE RLS de serviço
e SELECT no catálogo; isolamento por participante permanece no FastAPI.
Grants que exigirem extensão de privilégio fora desse arquivo devem bloquear.

```powershell
python -B scripts/manage_tcc_deploy.py materialize-new --confirm-database sigra_tcc_research
```

Materializa V6 histórico e Revision6 distinta a partir do plano aprovado, em
transação com lock e contratos originais. Nova tentativa encontra snapshots e
bloqueia: não resetar. Ao terminar, remover owner URL do ambiente e realizar:

```powershell
python -B scripts/inspect_neon_preview.py --phase materialized
python -B scripts/manage_tcc_deploy.py audit
```

Conferir ownership, grants, RLS, ausência de privilégios/memberships, Alembic,
60 identidades/1.080 avaliações por snapshot, fingerprints e contagens Base
10/60/10/24/9/9; Ampliada 0/8/0/3/8/8 em cada cenário. Não confundir presença
documental com nota final nem ativar Gold. O audit é leitura, mas consome egress.

## Preenchimento privado (templates inválidos por construção)

Não sobrescrever a pasta privada aprovada nem cofres existentes. Usar uma pasta
nova da candidata com ACL restrita ao operador/sistema necessário. Confirmar ACL
antes de ler/gravar, e preservar a chave nova entre reinícios/backups.

- Copiar `vercel.runtime.env.example` e complementar com `neon.runtime.env.example`
  somente na configuração privada. Runtime URL: psycopg, role runtime, senha nova
  URL-encoded, host exato, banco/porta fixos e query verify-full/CA/sslsni=1/channel_binding=require.
- Native operator: `SIGRA_RESEARCH_MIGRATION_URL` owner SOMENTE no processo de
  preparação; o manager retira essa variável antes de settings. Nunca configurar
  owner/provisionador na Vercel. Não reutilizar SIGRA_REVISION6_* do banco antigo.
- Completar `neon.target.UNCONFIGURED.json` com IDs observados de organização,
  projeto, branch, endpoint, host, OID, comentário e SHA da CA; confirmed e
  quota_checked só mudam após comprovação. Não usar o template como recibo.
- `SIGRA_NEON_ORGANIZATION_ID`, PROJECT_ID, BRANCH_ID, ENDPOINT_ID, HOST,
  DATABASE_OID e DATABASE_COMMENT confirmam exatamente os valores do recibo.
  Não basta o sufixo neon.tech. Região/plano/purpose são fixos; divergência bloqueia.
- Nativo: SIGRA_DEPLOY_TARGET_FILE, SIGRA_DEPLOY_TARGET_SHA256, CA absoluta,
  SIGRA_DEPLOY_PLAN_FILE e SIGRA_FUNCTIONAL_ACCEPTANCE_FILE fixados. Na Vercel:
  SIGRA_VERCEL_TARGET_B64 e SIGRA_VERCEL_CA_B64, sslrootcert=SIGRA_CA_FILE;
  o adapter cria scratch privado e revalida. Base64 NÃO é criptografia.
- SIGRA_RESEARCH_PSEUDONYM_KEY nova estável >=32 bytes, sem importar a chave TLS A/B;
  SIGRA_SYSTEM_VERSION deve ser o ID desta candidata em release/manifest.json.
- Origem HTTPS exata atribuída à Function, CORS/ALLOWED_HOSTS exatos, sem wildcard
  ou proxy inventado. Cookies Secure/HttpOnly/Lax continuam; frontend usa
  `/sigra-api`. Não carregar segredos em variáveis VITE_*.

## Egress, armazenamento e teste limitado proposto

O estimador offline externo traffic-estimate.json mede JSON de payloads do plano,
não rede real. Auditoria lê todos os 60/1.080 payloads a cada recomendação; depois
relê veículos e 60 avaliações do perfil/cenário. Proxy:43.930.203 bytes por
recomendação;100≈4,393 GB;500≈21,965 GB, antes de protocolo, startup, histórico,
exportação e monitoramento. Não é limite inferior/superior. Os 2,40 MB enviados
ao navegador NÃO medem Neon→Vercel. Nenhum cache ou guard foi removido.

Orçamento global: no máximo 30 recomendações, incluindo manuais e smoke.
Primeira execução instrumentada: somente uma, sem retry automático;
medir delta real de egress/CU-h, pg_database_size, TOAST/índices e crescimento por
execução. Pausar manualmente ao consumir orçamento experimental acordado antes
de novas chamadas. Isso não implementa um teto na plataforma. Armazenar 100
resultados completos de ~7,14 MB implica ~714 MB de JSON bruto, antes de duas
coortes, índices e questionários; compressão JSONB/TOAST altera ocupação. Sem
medição não garantir 100 testes. Otimização é etapa posterior, não esta entrega.

## Backup, rollback e retomada Vercel

Free oferece janela PITR até seis horas/1GB de mudanças; não confundir com
retenção de pesquisa. A documentação de snapshots menciona preço de armazenamento
US$0,09/GB-mês sem isenção inequívoca na seção: não ativar snapshot tarifado nem
backup agendado (não Free) sem confirmação. Usar futuro pg_dump direto com
operador autorizado que veja FORCE RLS, pg_service/entrada local privada e arquivo
protegido/criptografado fora da distribuição. Dump inclui hashes/sessões: segredo.
Teste de restore só em outro destino novo autorizado e sob as mesmas quotas;
nunca sobrescrever bancos anteriores. Backups externos também contam no egress.
[Backup](https://neon.com/docs/manage/backups).

Rollback: retirar/impedir acesso ao novo preview, conservar banco e chave para
investigação/retomada, não downgrade/reset/drop nem voltar silenciosamente para
Supabase. Guardar release/recibo/CA/hash e deployment anterior; nenhuma migração
reversa no banco existente.

Ordem única: conta/inventário → autorização de provisionamento → identidade e
TLS → banco/roles/recibo → migrations/grants/materialização → preflight → build
remoto/preview da factory → publicação explicitamente autorizada → smoke online
fictício limitado. O código ASGI não migra na inicialização. Bundle remoto,
roteamento HTTPS/Host/lifespan, cold start, resposta compacta e CSV paginado ainda
são gates Vercel; os testes locais não os aprovam. Não reaplicar a imagem Docker
na Function. Não repetir fluxos A–E/CSV no banco antigo. Sem domínio comprado ou
registry: usar hostname Vercel atribuído após confirmação. historical_row_changed=1,
aceite limitado e coleta real=false permanecem obrigatórios.

Fontes técnicas adicionais:
[roles](https://neon.com/docs/manage/roles),
[compatibilidade](https://neon.com/docs/reference/compatibility),
[regiões](https://neon.com/docs/introduction/regions),
[IPv4/IPv6](https://neon.com/blog/ip-allow-with-ipv6),
[SQLAlchemy](https://neon.com/docs/guides/sqlalchemy).
