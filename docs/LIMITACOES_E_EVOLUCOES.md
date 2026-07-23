# Limitacoes e evolucoes

## Fundação de motocicletas 0.3.1

- Motocicletas possuem cadastro, auditoria, ficha objetiva, fontes canônicas por grupo, métricas derivadas, estimativas econômicas separadas, cobertura e elegibilidade estrutural, mas não possuem Nota SIGRA, ranking, TCO, pesos, estratégia ou guardrails funcionais.
- Indicadores derivados são opcionais e ainda não possuem rubrica validada. A ausência deles não invalida a ficha.
- Gestao de usuario, despesas, manutencao, consumo, relatos, pecas e alertas continua exclusiva de automoveis; a decisao futura esta em `ADR_GESTAO_VEICULAR.md`.
- SQLite legado permanece suportado localmente; PostgreSQL possui migration
  Alembic e pipeline auditável, mas exige validação real no ambiente alvo.
- Registros inválidos ou sem especificações são omitidos da lista pública, contabilizados e não recebem preenchimento automático. A leitura individual retorna erro controlado e o reparo exige estado final válido.
- A metodologia futura está documentada, mas não existem fórmula, pesos, TCO definitivo, guardrails funcionais ou Nota SIGRA de motocicletas.
- Fontes ausentes permanecem nulas; o sistema não transforma dados demonstrativos em oficiais nem cria uma fonte geral para grupos desconhecidos.
- `eligible` significa apenas prontidão estrutural e não deve ser interpretado como recomendado, adequado ou seguro.
- A base piloto auditável ainda não foi coletada. O repositório contém somente template, validador offline e importador com dry-run.
- Depreciação pode ser cadastrada apenas como estimativa demonstrativa/não validada; não há fórmula automática nem uso no TCO.
- A cobertura mínima piloto possui quatro grupos: identidade, preço, ficha
  técnica e consumo. Manutenção e demais dados econômicos são complementares;
  a ausência reduz a prontidão futura, mas não vira zero nem Nota SIGRA.
- `future_recommendation_readiness` é apenas um estado de preparação dos dados,
  não certifica recomendabilidade.
- O SQLite oficial de desenvolvimento é `backend/sigra.db`. Cópias antigas
  detectadas em outros caminhos não são apagadas automaticamente e nunca
  entram nos pacotes gerados.
- O seed canônico possui quatro motos demonstrativas distintas e reconstrução
  transacional com backup. Esses registros continuam fictícios e não elevam a
  maturidade metodológica do futuro recomendador de motocicletas.
- `scripts/clean_workspace.py` só remove artefatos reconhecidos após
  confirmação explícita; banco canônico, código, documentação, `.env`,
  dependências e backup mais recente são protegidos por padrão.

## Regressao automotiva

`cars_regression_v1.json` congela o comportamento validado do algoritmo `2.1.2/cars-v1` sem depender do banco vivo. Atualizar dados de producao nao exige atualizar a fixture. Qualquer mudanca intencional na formula ou nos pesos devera criar uma nova versao da fixture apos aprovacao metodologica.

## Limitacoes atuais

- O financiamento `1.0.3` e uma simulacao stateless no sistema Price; nao consulta bancos, nao garante aprovacao, nao persiste propostas e ainda nao implementa SAC.
- A comparacao aceita no maximo 10 cenarios informados pelo usuario e nao elege uma proposta unica como melhor. Cenarios com veiculos ou bases de preco diferentes sao comparaveis apenas como aquisicoes completas e recebem aviso explicito. Orcamentos ou custos mensais distintos suprimem o vencedor de comprometimento sem esconder os percentuais individuais.
- CET informado nao e decomposto em juros puros quando os componentes nao estao disponiveis.

- A base de 34 veiculos e demonstrativa.
- Os precos e custos sao referencias internas para o MVP e nao substituem cotacao real.
- As imagens e links externos sao demonstrativos e nao representam anuncio validado.
- As imagens dos veiculos sao ilustrativas e usadas apenas para fins academicos/demonstrativos. Elas podem nao representar exatamente cor, versao ou acabamento do modelo.
- Dados, precos, links, pecas e imagens nao substituem cotacao real.
- O login e simplificado, com usuarios de demonstracao.
- Ainda nao ha cadastro completo de perfis individuais.
- O modo visitante permite simular recomendacoes, mas nao salva historico.
- A area "Meu carro" usa relatos demonstrativos para validar o fluxo.
- Alertas preventivos sao baseados em regra simples por quilometragem e recorrencia, nao em diagnostico mecanico.
- Precos de pecas, fornecedores e compatibilidades sao demonstrativos.
- Nao ha scraping real de autopecas ou marketplace nesta etapa.
- Nao ha integracao real com FIPE, seguradoras, oficinas ou marketplaces.
- O algoritmo usa pesos definidos manualmente, nao aprendizado de maquina.

## Por que isso e adequado ao MVP

O objetivo academico e demonstrar arquitetura, fluxo funcional, regra explicavel e viabilidade de evolucao. Para a defesa, a prioridade e mostrar que o sistema funciona de ponta a ponta e que as decisoes sao transparentes.

## Evolucoes futuras

- Coletar e revisar a base piloto de 20 a 30 motocicletas antes de definir rubricas, pesos ou algoritmo de recomendação.
- Manter a comparação SQLite/PostgreSQL verde e validar concorrência/carga
  antes de tornar PostgreSQL o único banco de ambientes publicados.
- Conectar Supabase somente com credenciais externas, SSL e rollback testado.

- Integrar API FIPE ou fonte equivalente para precos atualizados.
- Buscar anuncios reais em marketplaces por API autorizada.
- Criar cadastro completo de usuarios.
- Salvar diferentes perfis de recomendacao por usuario.
- Implementar autenticacao real com senha criptografada e token.
- Melhorar a base de manutencao por modelo e ano.
- Adicionar filtros por cambio, carroceria, combustivel e localizacao.
- Coletar feedback do usuario para calibrar os pesos.
- Coletar relatos reais suficientes para melhorar alertas por modelo, ano, motor e versao.
- Evoluir o indice de risco com filtros por quilometragem, gravidade, custo e recorrencia.
- Integrar APIs ou fornecedores reais para precos de pecas.
- Validar compatibilidade de pecas por versao, motor, cambio e chassi.
- Criar historico de cotacoes para detectar preco abusivo com mais precisao.
- Criar relatorios historicos de custo por veiculo.
- Implementar historico persistente por usuario logado.
- Publicar backend e frontend em ambiente cloud.

## Risco principal

O principal risco e tratar a base demonstrativa como fonte definitiva. Na apresentacao, deixe claro que os dados servem para validar o funcionamento do sistema, nao para substituir uma cotacao real.
# Estabilizacao anterior ao modulo de motocicletas

- O SIGRA recomenda apenas automoveis nesta versao. O seletor de motocicletas sinaliza desenvolvimento futuro e nao reutiliza resultados de carros.
- A interface nao possui fallback demonstrativo na jornada real: falhas da API produzem erro recuperavel.
- A referencia temporal consolidada da base ainda pode ser desconhecida; nesse caso a API retorna `data_reference: null`.
- Valores iguais na normalizacao podem receber 100 provisoriamente. A formula nao foi alterada nesta estabilizacao.
- A confianca informa cobertura dos dados e nao influencia a Nota SIGRA.
- O modulo futuro de motocicletas exigira base, categorias, TCO, pesos, validacoes e testes proprios.
