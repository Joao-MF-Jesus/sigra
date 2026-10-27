# Redução de leituras — patch local para revisão

Este patch não está publicado. A release remota continua `sigra-be98bd5b78ce6ddd81592d08`. A revisão v2 testa somente um cluster PostgreSQL 18.3 novo, descartável, em loopback com TLS verify-full e certificado de teste. Nenhuma conexão ao Neon, operação remota ou mudança nos bancos existentes foi realizada. Coleta real desligada; `historical_row_changed=1` preservado.

## Caminhos comprovados

- `packed_plan.restore_plan` restaura a representação gzip incluída no pacote para scratch local. Os 192.101.420 bytes restaurados **não são uma consulta ao Neon**. `deployment.load_plan` já tem cache local por processo; não se remove a validação integral.
- `main.lifespan → deployment.validate_startup → service._snapshot` faz uma auditoria integral ao iniciar a aplicação. Um processo aquecido pode atender mais de uma requisição; não se assume um cold start por request.
- `academic_cohort.routes → deployment.service_for_session → Revision6Service._snapshot` volta a auditar ao obter metadados e ao calcular. A auditoria antiga traz todos os 60 veículos e 1.080 payloads de avaliação para Python.
- A recomendação ainda lê os 60 veículos e as 60 avaliações do perfil/cenário solicitado e recalcula o resultado. Esses acessos não são o mesmo que os 1.080 registros da auditoria integral.
- `participant_trials.record_result` fazia refresh da linha completa imediatamente depois do commit. Essa linha contém o resultado apresentado e o registro técnico grandes, embora o recibo precise apenas de ID e data.
- O histórico compacto já adia os JSONs grandes. Detalhes, avaliação, leitura do histórico completo e exportações ainda podem transferi-los; não devem ser contabilizados como recomendações.
- Helpers de materialização/reconciliação auditam os dois snapshots completos. Receber/gravar um relatório local ou consultar metadados Vercel pela API de controle não equivale a ler o banco. Requisições bloqueadas na proteção Vercel também não provam invocação da aplicação.

## Mudanças preparadas

### V1 preservada somente como comparação; não selecionada pelo runtime

O experimento `compact_audit.py` permanece como baseline reproduzível, não como serviço escolhido pela factory. Seu EXCEPT ALL preserva a igualdade integral, mas o PostgreSQL local mediu 40.842.174 bytes enviados para receber 202 bytes. Trocar a direção não resolve a transferência bidirecional. A proposta v1 foi arquivada separadamente, sem substituir sua evidência.

### V2: catálogo público versionado, jamais dados pessoais

Somente `provider=neon` seleciona `CachedPublishedRevision6Service`. Identidade, TLS, transporte aceito, role, grants/RLS e Alembic continuam verificados antes do serviço, em cada requisição. Outros destinos continuam com o auditor original. Nenhum guard de permissão é armazenado.

- Escopo: processo, hostname/porta, OID do banco, role runtime, projeto, SHA do plano, snapshot, versão e fingerprint. No máximo duas entradas; validade máxima 60 segundos desde a carga. Concorrência fria usa lock local limitado a 15 segundos; timeout bloqueia, sem retry ou resultado antigo.
- Cada aquisição exige uma consulta PostgreSQL bem-sucedida. A marca MVCC cobre PK, tableoid/xmin/ctid de **todas** as linhas dos três conjuntos, época de XID e metadados estruturais das tabelas. Ela é um mecanismo de invalidação, não um fingerprint de confiança declarado pelo conteúdo.
- Carga fria, expiração ou qualquer mudança: o auditor original compara integralmente grão, campos escalares, JSON completo, fingerprints e flags contra o plano pinado. Marcas antes/depois bloqueiam commit concorrente durante essa carga. O cabeçalho/plano também é validado em hits. Nenhum cache antigo é usado se a leitura ou comparação falhar.
- Uma alteração SQL de payload ou escalar muda a versão da linha mesmo que seu fingerprint seja preservado. Versão de catálogo divergente bloqueia; não se atualiza a referência automaticamente. DDL/reescritas e mudança de escopo também invalidam.
- Só bytes imutáveis de catálogo entram nas entradas. Cada request recebe clones próprios, sem ORM Session global. Sessões, usuários, permissões, histórico, recomendações e avaliações de pessoas **não** entram no cache.
- Validade corresponde à visão MVCC da consulta; teste realizado em READ COMMITTED. Restore físico/troca de cluster exige reiniciar o processo/limpar o cache e revalidar a identidade. A marca não é prova de ausência de corrupção física fora do PostgreSQL. TTL não substitui essa disciplina operacional.
- Não há extensões, migrations, funções persistidas ou concessões novas na aplicação. O teste cria apenas suas próprias fixtures/roles no cluster descartável.

A consulta quente final, com permissões atuais verificadas, mediu 2.006 bytes enviados / 11.532 recebidos, contra 3.779 / 40.718.423 para metadados antes do patch. São bytes TCP/TLS observados localmente, não faturamento Neon. A carga fria ainda recebe aproximadamente 40,7 MB. Processos novos e TTL expirado repetem a auditoria integral: não é cache compartilhado entre Functions e não garante caber na franquia Free. As amostras foram 16,80 s antes, 15,20 s aquecido e 29,68 s frio, sem garantia de desempenho no provedor. A validação repetida do plano continua custosa em CPU.

### Recibo seletivo após gravar

O refresh passa a pedir somente `id` e `created_at`. A transação, persistência do resultado integral, hashes, questionário, owner filter e detalhes/exportação permanecem iguais. Não há alteração de tabela ou dos registros existentes. O double da integração foi atualizado para exigir esses dois atributos, em vez de ignorar a chamada; as verificações do instrumento/CSV não foram removidas.

## Limites das medições

A soma local dos payloads JSON com separadores espaçados é 40.415.176 bytes: 1.248.147 de veículos e 39.167.029 de avaliações. São bytes de uma representação nomeada, não contador de tráfego Neon, e não incluem overhead do protocolo/TLS.

Um recibo remoto anterior mede 53.598.232 bytes de campos SQL e 2.401.094 bytes de resposta HTTP de uma recomendação. O contador era restrito ao request de recomendação: startup, catálogo, auth, histórico e helpers não estão todos nessa medição. Não há ledger temporal que permita repartir exatamente os 5,88 GB mostrados no Neon.

## Condições para uma entrega futura

- Revisar os patches e os resultados offline vinculados, preservando os artefatos anteriores.
- Rever as provas PostgreSQL locais da v2, inclusive alteração mantendo fingerprint, versão, commit concorrente, resultado devolvido após refresh seletivo e owner isolation. PostgreSQL 18.3/Windows não substitui validação 17/Linux do destino.
- Gerar uma nova candidata/manifesto para os bytes novos. Este patch não altera o manifesto da release histórica para fingir correspondência.
- Medir inicializações e todos os acessos SQL, além do request de recomendação, com correlação por invocação e consumo do provedor. Não usar corpo HTTP como proxy de egress PostgreSQL.
- Não ativar coleta real. A ressalva `historical_row_changed=1` e os aceites restritos continuam intactos.

## Personalização: integração não muda metodologia

O smoke remoto aprovado de 22/10 selecionou explicitamente `academic-derived-seven-v1` + `academic-derived-base-five-v1`, gasolina manual R$6, Aplicativo e percurso 100/0. Não validou as sete notas originais. O formulário padrão mantém o método original; cenário de custos Base não escolhe a configuração derivada Base.

A reprodução offline usa o React real, ASGI, motor, transporte compacto e renderer, com catálogo público pinado e sem conexão ao banco. Cidade/50-50/preço geral R$7 sem preço manual reproduziu 0%; com preço manual R$7 reproduziu 35%, ambos sem nota final. A seleção explícita do payload de 22/10 reproduziu 60 notas na Base de cinco dimensões. UF/semana e payload históricos do episódio visual não foram preservados: não se atribui uma seleção ao usuário sem esse registro.

O patch de UI só explicita método e origem do preço na revisão, nomeia corretamente a comparação de referência e deixa de classificar um resultado stale como atual. Não muda política padrão, pesos, critérios, fontes, notas ou posições. Usar a alternativa em um roteiro requer escolha explícita; mudar o método padrão ou substituir critérios originais continua sendo decisão metodológica.

Uma regressão de layout foi reproduzida no CSS do HEAD 08caf44: inputs de pesos tinham dimensão zero após selecionar a configuração. Desativar somente `container-type` nos rótulos de pesos mantém a grade e os containers dos selects e restaura a altura intrínseca dos inputs. A interação passou em 1440 px e 320 px, sem fill forçado. Esse CSS já difere da release publicada: não se atribui este bloqueio ao Preview nem se explica a cobertura zero por ele. A mensagem de preço agora informa que o adaptador não consulta ANP, em vez de afirmar sem consulta que não existe preço no recorte.
