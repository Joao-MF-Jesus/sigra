# Auditoria de registros de motocicletas 0.3.0

## Objetivo

`audit_motorcycle_record` protege o contrato público contra dados persistidos inválidos. A auditoria é somente leitura: não aplica `clamp`, não completa campos e não inventa fontes, datas, custos ou scores.

## Dados auditados

São validados identidade, ano, preço, consumos, manutenção, tipo veicular, enums, booleanos, ficha objetiva, unidades, valores finitos e metadados legados. Indicadores derivados não são requisitos da ficha; quando existem, são validados pelo schema e pelo repositório próprio.

Fontes agrupadas validam grupo, tipo, URL, datas, confiança, requisitos de fonte oficial/estimada e anonimização básica de relato. Apenas uma fonte pode ser principal por grupo.

## Resiliência do CRUD

- listagem: omite registros objetivos inválidos, mantém os válidos e informa contagens seguras;
- leitura individual: retorna `409 motorcycle_record_invalid` para persistido inválido;
- atualização: combina payload e estado bruto, audita antes do commit e faz rollback na falha;
- exclusão: funciona por ID mesmo quando a serialização do registro falha;
- relações de fonte, ficha e métricas usam cascata ou `SET NULL` documentado.

## Auditoria versus elegibilidade

Auditoria responde se o cadastro atende ao contrato objetivo. Elegibilidade responde se há prontidão estrutural para uma avaliação futura. Uma ficha válida pode ser `incomplete`, `outdated_data`, `insufficient_confidence` ou `demonstration_only`. Nenhum desses estados calcula qualidade ou adequação.

## Limitações

A auditoria não corrige banco legado, não certifica a veracidade da fonte e não habilita recomendação. Registros demonstrativos continuam válidos para CRUD, porém estruturalmente inelegíveis para decisão.
