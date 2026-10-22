# Rollback da homologacao

## Registro minimo antes de publicar

- commit e branch;
- deployment ID anterior e novo de Vercel;
- deployment ID anterior e novo de Render;
- revisao Alembic;
- URL publica de cada servico;
- relatorio do bootstrap e do smoke;
- responsavel e horario.

## Frontend

1. interrompa novas validacoes;
2. retorne ao deployment anterior na Vercel;
3. confirme `VITE_API_URL` do ambiente restaurado;
4. valide abertura, assets, navegacao e ausencia de localhost;
5. confirme que o banner demonstrativo continua visivel.

## Backend

1. mantenha o banco preservado;
2. retorne ao commit ou deployment anterior no Render;
3. faca redeploy sem force push;
4. valide `/health` e `/health/database`;
5. confirme CORS, HTTP 403 para escrita e logs sem segredo.

## Banco

Nao execute downgrade Alembic automaticamente. Enquanto o schema novo for
compativel, faca rollback apenas da aplicacao.

Se houver incompatibilidade:

1. bloqueie o frontend;
2. crie outro banco;
3. restaure um dump validado ou recrie com Alembic e bootstrap;
4. compare revisao e contagens;
5. aponte o backend para o banco recuperado;
6. execute smoke e E2E antes de reabrir.

Nunca apague ou limpe o banco remoto ativo sem confirmacao explicita. Nunca
restaure um dump diretamente sobre ele como teste.

## Desligamento

Para encerrar a homologacao:

1. desative o deployment da Vercel;
2. suspenda o servico Render;
3. remova secrets dos paineis;
4. exporte evidencias necessarias;
5. pause ou exclua o projeto Supabase somente apos backup e confirmacao;
6. registre a data do desligamento.

Este runbook nao executa rollback, deploy ou exclusao de recursos.
