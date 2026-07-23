# Metodologia futura do recomendador de motocicletas

O contrato metodológico central é `MOTORCYCLE_RECOMMENDER_SPEC_V1.md`. Esta página resume as fronteiras que não podem ser ultrapassadas na versão `0.3.0`.

## O que está preparado

- ficha técnica objetiva com unidades;
- fontes por grupo, confiança e referência temporal;
- métricas derivadas em tabela separada;
- estados estruturais de elegibilidade;
- seis estratégias candidatas documentadas;
- TCO, matriz de dupla contagem, guardrails e rubricas conceituais;
- plano de testes e critérios para aprovação futura.

## O que não existe

Não existem Nota SIGRA, pesos, ranking, TCO funcional, compatibilidade com perfil, estratégia executada, guardrail decisório ou recomendação de motocicletas. O endpoint reservado retorna HTTP 501.

## Princípios para a próxima fase

1. Não reutilizar `cars-v1` nem parâmetros de TCO de automóveis.
2. Não usar cilindrada isoladamente como dificuldade ou segurança.
3. Não transformar ausência em zero ou média silenciosa.
4. Não misturar confiança da evidência com qualidade da moto.
5. Não pontuar o mesmo dado dentro do TCO e novamente como benefício.
6. Não calibrar pesos para forçar modelos desejados ao topo.
7. Exigir rubricas versionadas, revisão especialista e análise de sensibilidade antes do ranking.

Documentos complementares: `DADOS_E_INDICADORES_MOTOCICLETAS.md`, `TCO_MOTOCICLETAS.md`, `MATRIZ_CRITERIOS_MOTOCICLETAS.md`, `GUARDRAILS_MOTOCICLETAS.md` e `PLANO_VALIDACAO_MOTOCICLETAS.md`.
