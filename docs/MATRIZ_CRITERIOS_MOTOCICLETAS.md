# Matriz de critérios e dupla contagem de motocicletas

> Proposta metodológica sem pesos, fórmula ou ranking.

## Critérios candidatos

Viabilidade financeira, TCO, adequação urbana, adequação ao trabalho, facilidade para iniciantes, segurança, ergonomia, manutenção, confiabilidade, peças, consumo, autonomia, passageiro, bagagem, estrada e risco econômico.

## Mapa de uso dos dados

| Dado | Aparece em | Estratégia futura contra dupla contagem |
|---|---|---|
| preço | viabilidade de compra e depreciação | requisito financeiro; não premiar novamente como baixo custo |
| consumo | combustível no TCO, autonomia e contexto urbano | entrada de TCO/autonomia; não pontuar isoladamente na mesma estratégia |
| tanque | autonomia e estrada/trabalho | entrada do indicador de autonomia; não pontuar tanque e autonomia |
| manutenção preventiva | TCO e manutenção | custo entra no TCO; rubrica avalia previsibilidade, não repete custo |
| histórico de falhas | corretiva, confiabilidade e risco econômico | alimentar reserva ou confiabilidade; reduzir/retirar contribuição paralela |
| peças | manutenção, continuidade de trabalho e risco | indicador de disponibilidade; custo fica no TCO; manter explicação separada |
| ABS | requisito explícito, guardrail e segurança | guardrail primeiro; eventual score só diferencia equipamento residual |
| CBS/controle de tração | segurança | entrada de rubrica, sem bônus independente |
| peso | ergonomia, urbano e iniciante | entrada compartilhada de rubricas; contribuição consolidada por perfil |
| altura do assento | ergonomia e iniciante | contexto com preferência declarada; nunca filtro físico isolado |
| potência/torque | experiência e estrada | relação peso/potência ou rubrica composta; não três bônus independentes |
| categoria | domínio, uso e experiência | filtro de escopo e contexto; não substitui dados objetivos |
| carga útil | passageiro e bagagem | entrada nos indicadores; não pontuar diretamente em ambos |
| transmissão | urbano, iniciante e manutenção | entrada contextual; não bônus global |
| transmissão final | manutenção e TCO | custo mensalizado; tipo só explica operação |
| ano/condição | elegibilidade, preço, manutenção e risco | contexto e estratificação; não bônus automático por ser novo |
| fonte, cobertura e atualidade | confiança e elegibilidade | nunca compõem adequação ou eventual Nota SIGRA |

## Precedência candidata

1. Regras de domínio e requisitos explícitos.
2. Cálculos de custo com cobertura declarada.
3. Rubricas compostas e versionadas.
4. Critérios não sobrepostos.
5. Explicações e indicadores informativos.

Antes dos pesos, a equipe deverá testar correlação, retirar critérios redundantes e registrar para cada dado se ele é guardrail, entrada, critério único ou apenas explicação.
