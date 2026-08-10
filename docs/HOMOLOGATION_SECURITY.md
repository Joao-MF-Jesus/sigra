# Seguranca da homologacao

## Objetivo

A homologacao e publica para demonstracao academica e nao e um ambiente de
cadastro de usuarios. `PUBLIC_DEMO_MODE=true` transforma a API em um catalogo
somente leitura com calculos sem estado.

## Superficie permitida

- health e status do banco;
- catalogo de automoveis e motocicletas;
- pecas e metadados publicos;
- recomendacao de automoveis;
- simulacao, simulacao reversa e comparacao de financiamento;
- endpoint reservado de motos, que continua retornando HTTP 501.

Os POSTs de recomendacao e financiamento calculam uma resposta, mas nao
persistem registros.

## Superficie bloqueada

- login e autenticacao;
- usuarios, despesas, manutencoes e veiculos de usuario;
- relatorios e estatisticas pessoais;
- criacao, alteracao ou exclusao de automoveis;
- criacao, alteracao ou exclusao de motocicletas e suas fontes;
- qualquer outra operacao persistente com metodo POST, PUT, PATCH ou DELETE.

O bloqueio retorna HTTP 403 com o codigo estavel `demo_read_only`. O frontend
tambem oculta login, administracao, despesas e "Meu carro", mas o backend e a
barreira de seguranca efetiva.

## CORS e hosts

Em `homologation` e `production`:

- nao existem origens localhost implicitas;
- somente origens HTTPS explicitas sao aceitas;
- `*` e ignorado;
- `ALLOWED_HOSTS` limita o host HTTP aceito;
- a origem Vercel deve ser cadastrada sem barra final.

Preview URLs variaveis da Vercel nao devem ser liberadas com curinga. Use um
deployment estavel da homologacao ou atualize explicitamente a allowlist.

## Segredos

Segredos ficam apenas nos cofres das plataformas. Nunca registre:

- senha do Supabase;
- `DATABASE_URL` ou `MIGRATION_DATABASE_URL` reais;
- token de Vercel, Render, Supabase ou GitHub;
- chaves `service_role`;
- arquivos `.env` reais.

Variaveis `VITE_*` sao publicas e so podem conter URL e flags nao secretas.

## Logs

Cada requisicao recebe `X-Request-ID`. O backend registra timestamp do logger,
metodo, rota, status e duracao. O middleware nao registra query string, corpo,
senha, token, URL de banco ou dados pessoais.

No Render, consulte os logs do servico e filtre pelo request ID. Um erro interno
nao deve retornar stack trace ao navegador. Logs do provedor continuam sujeitos
a retencao e aos limites do plano escolhido.

## Limitacoes

- a homologacao nao implementa autenticacao publica segura;
- nao ha rate limiting distribuido nesta versao;
- nao ha WAF proprio ou observabilidade externa contratada;
- os dados sao demonstrativos, nao garantia de preco, falha ou aprovacao;
- o endpoint de motocicletas nao possui algoritmo nem Nota SIGRA;
- a disponibilidade e os limites dos planos de terceiros podem mudar.

Se qualquer rota persistente responder diferente de HTTP 403 em modo publico,
interrompa a homologacao e execute o rollback de aplicacao.
