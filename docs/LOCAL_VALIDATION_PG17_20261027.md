# Candidata consolidada: evidência local Linux/PostgreSQL 17

Esta revisão prepara código para o PR #3; não publica nem revalida o Preview.
A aplicação remota continua sendo a release `sigra-be98bd5b78ce6ddd81592d08`.
Coleta real desligada; `historical_row_changed=1` e aceites restritos preservados.

## Identidade e alcance

- Base confirmada do PR: `08caf44a197a1aaa21400abb8c180487776bd712`.
- Candidata testada: `sigra-710d5e8c13a8b665a00fe658`, 462 arquivos de aplicação.
- Manifesto aprovado: SHA-256 `ee5e60648ac732d66173b3c58f59ae26a7f4a1b14b447defecdb044293a18286`.
- Function Linux preservada: ZIP SHA-256 `1f56b4370e340436080c535d0c35b10d650ebd40be0bff99c05889038c5283a7`, 134.328.487 bytes descompactados; conjunto de arquivos, modos, links e 169 insumos backend conferidos pelo controlador.
- Execução: `attempt-20261027t133720112227z`, 27/10/2026, aproximadamente 10:37–10:48 em Brasília (13:37–13:48 UTC). Os relatórios completos permanecem no acervo local; caminhos privados, credenciais e configurações de conexão não são distribuídos.
- 295 testes backend direcionados passaram no Linux, zero falhas/skips e sete testes desselecionados pelo filtro explícito `not http`. Não é a suíte backend completa.
- 48 checks de integração passaram no destino PostgreSQL **17.11** descartável, incluindo alterações reais, versões, commit concorrente, permissões, isolamento, refresh e auth montada. Esses checks não equivalem a 48 testes pytest independentes.

Build, 236 testes frontend e auditoria nativa de 63 arquivos já aprovados foram
reutilizados. Esta integração não reconstruiu a Function nem repetiu Linux/PG17.

## PostgreSQL, integridade e encerramento

O destino foi identificado como fixture vazia antes das escritas. TLS cliente
observado com `verify-full`, CA/hostname conferidos e channel binding obrigatório;
o PostgreSQL observou TLS 1.3 na própria sessão. SNI foi solicitado explicitamente,
mas seu valor efetivo não foi exposto pelo driver nesse recibo.

Alembic `20261007_0015` foi confirmado por conexão independente. A materialização
de 60 veículos e 1.080 avaliações teve commit confirmado e comparação integral
contra o plano fixado, inclusive fingerprints, campos escalares, JSON e flags.
O UUID do snapshot novo não foi registrado no recibo final: não é reconstruído
nem substituído pelo UUID de outro ambiente.

Alterações de payload/escalar com fingerprint preservado, versão divergente e
commit concorrente foram rejeitados. Revogação de permissão não reutilizou entrada
antiga. Expiração, mudança de escopo e limpeza explícita forçaram nova auditoria.
Clones por request e filtro de proprietário foram conferidos.

O validador terminou com exit 0, sem OOM ou reinício. Os comandos de parada do
validador e do PG que a própria execução iniciou retornaram 0. Lease liberada,
sem falha de cleanup. Rede, volumes, imagem e recursos anteriores não foram
apagados. Não houve nova inspeção remota ou acesso ao Neon nesta consolidação.

## Medições locais: consultas, TCP/TLS e latência

Enviado significa aplicação → PostgreSQL; recebido significa PostgreSQL →
aplicação. São deltas do relay TCP/TLS local nos blocos nomeados, não o contador
de egress faturado pelo Neon, nem bytes da resposta HTTP ao navegador.

| Bloco | Consultas | Campos retornados (bytes) | Enviados (bytes) | Recebidos (bytes) | Segundos |
|---|---:|---:|---:|---:|---:|
| Conexão/consulta de identidade | 1 | 35 | 1.929 | 3.264 | 0,071 |
| Metadados, auditor anterior | 3 | 40.580.498 | 2.309 | 40.715.424 | 19,274 |
| Cache frio | 4 | 40.591.482 | 5.303 | 40.727.133 | 38,934 |
| Cache quente 1 | 1 | 10.918 | 2.006 | 11.532 | 16,093 |
| Cache quente 2 | 1 | 10.918 | 2.006 | 11.532 | 17,798 |
| Cache quente 3 | 1 | 10.918 | 2.006 | 11.532 | 17,828 |
| Limpeza explícita/reload | 4 | 40.591.482 | 1.733 | 40.727.211 | 33,590 |
| Gravação + refresh integral anterior | 2 | 7.631.431 | 7.645.798 | 7.647.022 | 1,273 |
| Gravação + refresh seletivo | 2 | 65 | 7.645.276 | 4.824 | 1,085 |

Cache quente: recebimento aproximadamente 99,972% menor; média de 17,240 s.
Isso **não** elimina o custo frio: aproximadamente 40,73 MB recebidos e 38,93 s
nessa amostra. O cache é por processo, limitado a duas entradas e 60 segundos,
com leitura de invalidação e comparação integral em misses; não compartilha
sessões, históricos, permissões ou resultados de usuários entre Functions.
Uma Function nova ou entrada expirada volta a pagar o custo da auditoria fria.

Restauração/parsing/validação inicial do plano local levou 15,303 s. Os
192.101.420 bytes restaurados vêm do artefato gzip, não do banco. Validação
integral repetida continua consumindo CPU; redução de bytes não implica redução
equivalente de latência. Não há prova de capacidade para usuários concorrentes
ou de consumo dentro da quota gratuita do provedor.

O refresh seletivo reduziu recebimento em aproximadamente 99,937%, mas o envio
permaneceu em cerca de 7,65 MB: o resultado completo continua persistido. Recibo,
detalhes em conexão nova, fingerprint e isolamento entre proprietários passaram.
Consultas fora desses blocos (migrations, materialização, mutações de teste,
autenticação etc.) não estão somadas à tabela; ela não reparte os 5,88 GB históricos.

## Personalização e cadastro

A alternativa derivada Base de cinco dimensões produziu 60 notas apenas quando
explicitamente selecionada. O método original continua padrão, sem inventar
evidências, preencher critérios ausentes ou redistribuir pesos. A interface
distingue preço de referência de preço manual e resultado stale de resultado
atual; não altera notas de referência ou força posições diferentes.

Cadastro sintético montado em `/sigra-api`: 201, duplicidade 409, validações 422
sem eco de dados privados, login 200, cookie seguro, sessão reconhecida e 403
administrativo do participante foram conferidos localmente. A causa do HTTP 500
histórico continua **desconhecida**; cadastro remoto ainda não foi revalidado.

## Integração e reprodução

Os 460 arquivos mapeados do repositório, o `vercel.json` efetivo e o plano gzip
correspondem byte a byte aos 462 insumos da candidata aprovada. O overlay pv22
`includeFiles` continua string. Dependências, plano, metodologia e referências
históricas não foram alterados.

`source-revisions.json` v2 registra revisões separadas e nove adições públicas;
o mapa histórico é imutável. A montagem exige identidade e contagem da candidata,
sem aprender hashes ou aceitar fallback. Diferenças deliberadas fora dos arquivos
de aplicação: verificador/montador público, metadados, atributos Git, documentação
e wiring pytest do CI. O manifesto/recibo gerado pelo montador público tem metadados
de proveniência distintos do pacote de revisão; não se afirma identidade do ZIP
futuro ou repetição do bundle Linux aprovado.

As correções anteriores de CI, E2E, três fixtures e limite do plano comprimido
permanecem. Testes pytest novos são executados explicitamente no CI, pois somente
`unittest discover` não os coleta. PostgreSQL, E2E e empacotamento antigos mantêm
seus gates/dependências. Checks remotos do novo HEAD dependem de futuro push.

O documento `NEON_TRANSFER_REDUCTION_REVIEW.md` preserva a análise anterior em
PG18/Windows; esta nota acrescenta a evidência PG17/Linux, sem alterar o artefato
testado. Não houve push, merge, deploy ou nova recomendação remota nesta etapa.
