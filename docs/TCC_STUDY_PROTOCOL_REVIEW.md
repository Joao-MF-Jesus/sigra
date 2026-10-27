# Instrumento do TCC: implementação para homologação e proposta para revisão

Estado: **somente homologação com participantes fictícios**. Não autoriza coleta
real, não aprova o protocolo acadêmico e não declara o deploy pronto.

Fonte: monografia `TCC_SIGRA_Joao_Marcelo_Ferreira_de_Jesus_e_Felipe_Aceti_Araujo.pdf`,
apêndices C/D, páginas 46/47, SHA-256
`8c59530cf1a12fe1ba14146eff2f5ca980fc915404f9deb3db9bf5e43e85497b`.
Os apêndices foram lidos e conferidos visualmente. Não foram modificados.

## Correspondência do instrumento

| Requisito | Implementação | Limitação / decisão pendente |
| --- | --- | --- |
| Código pseudônimo | HMAC estável do participante + UUID da sessão experimental | Chave privada estável; não é anonimização |
| Cenário A–E | `scenario_id` separado de perfil/scenario low/base/high | Tarefas e opções específicas A–E não estão definidas no apêndice; revisar antes da coleta |
| Familiaridade | Nenhuma / Baixa / Média / Alta | Não vira nota do veículo |
| Até três prioridades antes do ranking | Contexto imutável criado antes do cálculo, ligado à sessão autenticada no servidor | Na homologação usa as sete opções existentes do formulário; aprovação da lista por tarefa ainda pendente |
| Clareza da interface | `interface_clarity`, inteiro estrito 1–5 | Independente das outras respostas |
| Entendi o primeiro veículo | `first_vehicle_explanation`, 1–5 | Sem média automática / nota inventada |
| Coerência com cenário | `scenario_coherence`, 1–5 | Independente |
| Critérios influentes | `influential_criteria`, 1–5 | Independente |
| Comentário opcional | Até 4.000 caracteres | Instrução para não inserir informações pessoais; revisão antes de compartilhar CSV |
| Apêndice D: sessão/versões | `execution_id`, `participant_code`, `scenario_id`, UTC, dataset/algoritmo/pesos/Alembic | Valores ausentes ficam null; `analysis_ready=false` impede tratar como rodada reproduzível |
| Entradas/elegibilidade/ranking | Parâmetros efetivos, IDs elegíveis/excluídos, motivos, posição/grupo/nota, contribuições originais | Não inventa contribuições negativas; array vazio se o motor não as produzir |
| Qualidade/proveniência | Diagnóstico documental e campos indisponíveis completos + resposta apresentada imutável | Estimativas/proxies não viram evidência observada |
| Estado/duração/erro/ambiente | Status, `duration_ms`, categoria de erro, `homologation_synthetic` | Falha após iniciar cálculo é registrada; payload rejeitado pela validação HTTP não é execução |

As respostas de feedback antigas continuam separadas. Uma avaliação geral não é
convertida em quatro respostas. Simulações sem dataset/pesos identificáveis são
guardadas no histórico, mas **não podem ser combinadas** com a rodada de ranking.
O instrumento não altera pesos, fórmulas, taxa, elegibilidade ou parâmetros do
recomendador. Prioridades declaradas são dado experimental: não substituem os
pesos que o usuário efetivamente informou no formulário.

## API e persistência

- `GET /api/v1/study-sessions/metadata`: texto, escala e opções; modo habilitado.
- `GET /api/v1/study-sessions/current`: contexto da própria sessão autenticada.
- `POST /api/v1/study-sessions`: cenário/familiaridade/prioridades/ciência da
  apresentação; não recebe user_id, papel ou token. Um novo contexto não altera
  resultados anteriores. Depois de novo login, deve registrar novo contexto.
- Endpoints `/api/v1/test-runs/*`: exigem contexto anterior quando o modo é
  `homologation`; cálculo e proprietário vêm do servidor.
- `PATCH /api/v1/test-runs/{id}/questionnaire`: quatro respostas e comentário.
- Histórico privado e CSV administrativo incluem ligação sessão/execução/
  respostas, mas não nome/e-mail/hash de senha/digest de autenticação.

`SIGRA_TCC_COLLECTION_MODE=disabled` é o padrão. `homologation` permite somente
o piloto fictício. Qualquer outro valor bloqueia. Não há switch que declare
aprovação acadêmica ou libere coleta real. A caixa de ciência da apresentação
é um requisito do piloto, **não um TCLE aprovado**.

Migration nova: `20261007_0015`, pai `20261007_0014`, sem alterar 0014.
Adiciona `participant_study_sessions`, `participant_questionnaires` e duas
colunas nullable nos registros; preserva dados existentes. Reversão vazia:
`alembic -c backend/alembic.ini downgrade 20261007_0014`. Com dados experimentais,
o downgrade bloqueia antes de remover registros. Não apagar dados para permitir
reversão. No destino atual/original **não foi autorizada aplicação**.

## Proposta concreta de apresentação/consentimento — NÃO APROVADA

Texto-base para revisar com a orientação: esta atividade avalia a clareza e o
comportamento de um sistema acadêmico de apoio à decisão automotiva. Não orienta
compra nem constitui recomendação comercial. A participação é voluntária e pode
ser interrompida. Serão registrados um código pseudônimo, cenário, familiaridade,
prioridades, parâmetros/resultados apresentados e quatro avaliações/comentário.
Custos são estimativas e critérios sem evidência continuam indisponíveis.

Proposta de fluxo antes da coleta real, ainda não habilitado: apresentar versão
aprovada do termo e contato responsável; registrar aceite ou recusa com versão/
timestamp e código pseudônimo; recusa não cria registro experimental; permitir
interromper sem penalidade e solicitar retirada usando o código. Não inventar
contato, prazo, benefício ou aprovação de comitê. A instituição deve revisar o
enquadramento e o procedimento aplicável.

## Proposta de retenção/acesso — decisões abertas

Separar contas identificáveis (nome/e-mail/hash da senha) de dados analíticos.
CSV somente administrador autorizado, sem identificadores diretos. Guardar
chave HMAC e backups fora do Git, em armazenamento controlado; não distribuir
chave junto ao CSV. Registrar quem tem acesso e revisar comentários antes de
compartilhamento. Não chamar HMAC/texto livre de dados anônimos.

| Decisão a revisar | Proposta / pendência |
| --- | --- |
| Responsável/controlador e contato | Nomear responsável pela coleta e pela resposta à retirada; não definidos |
| Participantes e tarefas | Aprovar A–E, opções/prioridades, público, recrutamento e cobertura limitada dos perfis |
| Prazo de retenção | Definir prazo e evento inicial para contas, execuções, CSV e backups; **nenhum prazo inventado** |
| Retirada | Definir canal pelo código, extensão de exclusão/pseudonimização e limites após análise consolidada |
| Descarte e backups | Procedimento revisado, evidência de conclusão e calendário consistente com retenção |
| Exportação | Autorizar destinatários, tratamento de comentários e separação da chave de reidentificação |
| Consentimento | Aprovar texto/versionamento e mecanismo antes de habilitar coleta real |

Não há rotina de expurgo executada nem alteração de registros nesta proposta.

## Roteiro de aceite PostgreSQL/browser (pendente do projeto)

1. Confirmar projeto exclusivo/custo, CA verify-full, runtime não privilegiado.
2. `tcc_supabase_session.py prepare` em projeto novo/vazio, incluindo 0014/0015,
   V6 60/1.080 e RLS das dez tabelas pessoais. Não executar no banco original.
3. `test` executa o opt-in PostgreSQL; seus skips não são aprovação.
4. `serve` com localhost HTTP/cookie Secure=false somente para teste local;
   abrir Vite, cadastrar **duas contas fictícias**, testar duplicidade/senha
   errada/escalada rejeitada; cenário A/prioridades antes do ranking; Aplicativo
   com orçamento amplo deve considerar 60 únicos, motor sem scores armazenados.
5. Responder quatro questões/comentário, abrir histórico, testar isolamento.
6. Registrar UUID/fingerprints; Ctrl+C **apenas no terminal que iniciou esta
   API**, repetir o mesmo comando `serve`, mesma chave HMAC e banco PostgreSQL.
   Reabrir histórico sem recalcular: respostas e fingerprints devem persistir.
7. Provisionar administrador por operador confirmado, verificar CSV pseudônimo,
   logout e 401. `audit` posterior mede banco e confirma V6/permissões read-only.
8. Validar HTTPS/CORS/cookies em domínios escolhidos antes de qualquer deploy.

Recriar TestClient/pool não equivale a reiniciar o processo da API. Testes locais
SQLite e replay não comprovam esse roteiro. Até o projeto existir, ele permanece
**não executado**.

## Capacidade: até 100 execuções, não promessa de 100 acessos simultâneos

O audit mede `pg_database_size(current_database())` (todos os schemas da base),
relações/índices/TOAST da aplicação e payload real dos registros. Projeta payload
de 100 execuções somente se houver amostras reais, sem apresentar a projeção como
tamanho total/egress. Conferir uso agregado da organização e painel do projeto.
Free: 500 MB de banco, 5 GB de egress; pausa por inatividade e ausência de backup
automático exigem plano de continuidade. Não contratar add-ons nesta etapa.

Fontes oficiais consultadas em 07/10/2026:
https://supabase.com/pricing e
https://supabase.com/docs/guides/platform/database-size.
Número de execuções não comprova uso de disco ou capacidade concorrente.
