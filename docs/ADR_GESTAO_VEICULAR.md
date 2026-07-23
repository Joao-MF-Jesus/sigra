# ADR — Arquitetura futura da gestão veicular

## Status

Proposta recomendada para uma etapa futura. Nenhuma migração estrutural ampla foi executada nesta versão.

## Contexto

O SIGRA mantém automóveis em `vehicles` e motocicletas em `motorcycles`, com especificações em `motorcycle_specifications`. Despesas, manutenções, veículos do usuário, relatos, consumo real, peças, alertas e estatísticas ainda referenciam `vehicles.id` e, portanto, pertencem ao domínio de automóveis.

O problema futuro é permitir gestão equivalente para motocicletas sem misturar IDs de tabelas diferentes, duplicar regras indefinidamente ou colocar em risco os 34 automóveis e o algoritmo `2.1.2/cars-v1`.

## Opção A — módulos separados

Automóveis mantêm os relacionamentos atuais. Motocicletas ganhariam tabelas paralelas para propriedade, despesas, manutenção, consumo, problemas, peças e alertas.

### Vantagens

- Menor risco imediato para o módulo consolidado.
- Regras específicas ficam explícitas.
- Migração inicial simples.

### Desvantagens

- Duplica tabelas, endpoints, relatórios e validações.
- Consultas consolidadas exigem união manual.
- Evolução e manutenção ficam progressivamente mais caras.

### Riscos

- Divergência semântica entre funcionalidades equivalentes.
- Mais esforço para uma futura adoção de PostgreSQL e visão comercial unificada.

## Opção B — entidade veicular comum

Uma tabela `vehicle_catalog` concentraria identidade e dados realmente comuns. `car_specifications` e `motorcycle_specifications` conteriam atributos específicos. Gestão e histórico referenciariam a identidade comum.

### Vantagens

- Chaves estrangeiras reais e consultas consolidadas.
- Evita referências polimórficas ambíguas.
- Melhor base para PostgreSQL, auditoria e expansão comercial.
- Separa identidade, especificação e decisão de forma academicamente defensável.

### Desvantagens

- Exige migração coordenada dos 34 carros e de todas as tabelas dependentes.
- Impacta contratos, seeds, FIPE, peças, histórico e autenticação.
- Possui maior custo de teste e rollback.

### Riscos

- Uma migração prematura pode alterar rankings ou quebrar relacionamentos já validados.
- Campos aparentemente comuns podem ter semânticas diferentes entre categorias.

## Opção C — adaptação incremental

Preserva `vehicles` e `motorcycles`, introduzindo primeiro uma camada de serviços e contratos comuns. Em uma etapa posterior, uma identidade veicular mínima pode mapear `(vehicle_type, domain_id)` com unicidade controlada, sem converter imediatamente todas as tabelas.

### Vantagens

- Reduz o risco e permite validar casos reais antes da migração definitiva.
- Centraliza regras comuns sem fingir que os domínios são iguais.
- Permite preparar testes, contratos e dados de origem gradualmente.

### Desvantagens

- É uma arquitetura de transição.
- Referências compostas não substituem chaves estrangeiras fortes.
- Exige disciplina para não espalhar condicionais por tipo.

### Riscos

- A transição pode se tornar permanente se não houver marco de migração.
- Uma referência polimórfica sem serviço central pode misturar IDs.

## Decisão recomendada

Adotar a **Opção C como transição controlada**, preparando serviços e contratos, e planejar a **Opção B como arquitetura-alvo** somente após validar o módulo de motocicletas e aprovar uma migração formal.

Nesta etapa, `vehicles` permanece exclusivamente automotiva e todos os seus fluxos filtram `vehicle_type = car`. Motocicletas usam somente seus endpoints e não participam de gestão, FIPE, peças, histórico ou recomendação de automóveis.

## Plano futuro de migração

1. Inventariar todas as FKs e contratos ligados a `vehicles.id`.
2. Definir quais atributos são realmente comuns e quais continuam específicos.
3. Criar identidade veicular comum com chaves estáveis e tabela de correspondência.
4. Migrar cópia do banco, mantendo mapa de IDs e auditoria de contagens.
5. Adaptar gestão e relatórios por serviço, sem alterar recomendadores.
6. Executar regressão imutável dos automóveis e testes próprios das motocicletas.
7. Planejar rollback e somente então migrar o banco principal.

## Fora do escopo atual

- Gestão de motos pelo usuário.
- Despesas, manutenção, consumo, relatos, peças ou alertas de motos.
- Catálogo veicular comum.
- Migração de FKs existentes.
- Comparação entre carros e motos.
- Algoritmo, Nota SIGRA, TCO ou ranking de motocicletas.
