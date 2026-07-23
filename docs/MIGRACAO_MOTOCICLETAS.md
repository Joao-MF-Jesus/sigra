# Migração da fundação de motocicletas

## Histórico

- `0.1.0`: isolamento por `vehicle_type`, tabelas `motorcycles` e `motorcycle_specifications`.
- `0.1.1`: rastreabilidade geral legada.
- `0.1.2`: auditoria resiliente, paginação e reparo transacional.
- `0.2.0`: ficha objetiva, fontes por grupo, métricas derivadas separadas e registro de versão.
- `0.3.0`: fontes agrupadas canônicas, campos legados opcionais, marcação demonstrativa explícita e estimativas econômicas separadas.
- `0.3.1`: estabilização contratual; manutenção anual opcional em toda a
  jornada, cobertura piloto unificada, prontidão futura separada e respostas
  canônicas por padrão.

## Migração 0.3.1

A etapa `0.3.1` não altera a fórmula de automóveis, não cria recomendador de
motocicletas e não fabrica valores. Como a coluna de manutenção já era
anulável desde `0.3.0`, a migração apenas registra idempotentemente a versão do
contrato. Dados legados continuam fisicamente preservados e só são expostos
sob `include_legacy=true`.

## Migração 0.3.0

A migração torna `data_source`, `data_confidence` e `annual_maintenance_cost` opcionais, adiciona `is_demonstration` e cria `motorcycle_economic_estimates`. Ela não cria fontes, métricas ou estimativas e não transforma depreciação legada em dado validado.

Antes da reconstrução SQLite é criado `sigra.db.pre-motorcycles-v0.3.0.bak`. A versão é registrada em `sigra_schema_migrations`; a segunda execução não duplica nem reescreve dados.

## Migração 0.2.0

A migração cria `motorcycle_objective_specifications`, `motorcycle_data_sources`, `motorcycle_derived_metrics` e `sigra_schema_migrations`. Ela adiciona versão, condição, combustível e data do preço e torna opcionais, no SQLite legado, os indicadores derivados que antes estavam na ficha principal.

Dados objetivos da tabela legada são copiados para a nova ficha. Scores só são migrados quando o registro está explicitamente marcado como `demonstration`; recebem `metric_status = demonstration` e `method_version = demonstration-v0`. Nenhuma fonte ou métrica é inventada.

## Segurança

Antes da mudança estrutural `0.2.0`, um SQLite existente recebe, uma única vez:

`sigra.db.pre-motorcycles-v0.2.0.bak`

Backups anteriores (`pre-motorcycles-v0.1.0` e `pre-motorcycles-v0.1.1`) continuam preservados. A aplicação não apaga nenhum banco ou backup.

A migração é transacional e idempotente: a versão fica em `sigra_schema_migrations`, cópias objetivas usam unicidade por motocicleta e métricas usam unicidade por motocicleta, nome e método. Executá-la novamente não duplica dados.

## Compatibilidade e precedência

- a ficha objetiva nova é a fonte de verdade;
- `motorcycle_specifications` permanece para bancos legados;
- campos gerais de fonte em `motorcycles` são compatibilidade; fontes agrupadas são a estrutura canônica;
- lacunas permanecem `NULL`;
- os 34 automóveis não são regravados nem recebem dados de motos.

## SQLite e PostgreSQL

SQLite exige reconstrução controlada da tabela para alterar nulabilidade. Por
isso o backup é obrigatório e a migração copia colunas explicitamente. Não
existe ramo PostgreSQL implementado nesta versão. A adoção futura deverá usar
ferramenta formal de migração, revisar constraints equivalentes e executar
suítes SQLite e PostgreSQL em paralelo.

## Restauração

1. Pare o backend.
2. Preserve o banco que apresentou falha.
3. Restaure a cópia `.pre-motorcycles-v0.3.0.bak` (ou a última anterior à etapa afetada).
4. Inicie a API e valide `/health`, `/vehicles` e `/motorcycles?envelope=true`.

Não altere o registro demonstrativo principal por edição manual. Use o seed explícito para novas inserções ou uma migração corretiva aprovada.
