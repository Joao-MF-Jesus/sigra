# Política de fontes de motocicletas

## Prioridade por grupo

Identidade e especificações: fabricante, manual e ficha técnica oficial. Preço: FIPE, fabricante ou fonte de mercado identificada conforme a finalidade. Consumo: fonte oficial, teste especializado identificado, estimativa explicitamente metodológica e relato de usuário apenas como complemento. Manutenção: manual, plano de revisão, oficina ou catálogo identificado; estimativas exigem metodologia. Confiabilidade e peças: múltiplas evidências e rubrica documentada antes de qualquer uso decisório.

## Fonte principal

Cada moto pode ter no máximo uma fonte principal por grupo. A principal deve ser a evidência mais diretamente relacionada ao campo, identificável, atual e revisada. A troca é transacional: a anterior é rebaixada e a nova promovida no mesmo commit. Fontes secundárias permanecem para auditoria.

## Confiança e atualidade

Confiança varia de 0 a 100 e mede cobertura/qualidade da evidência, não qualidade da motocicleta. A elegibilidade futura exige pelo menos 60 nos grupos obrigatórios. Preço usa janela de referência de 548 dias; ficha técnica usa 1.825 dias. Datas ausentes não são substituídas por hoje.

Uma segunda fonte é recomendada para consumo, manutenção, confiabilidade e peças. Ela é obrigatória antes de validar rubricas de confiabilidade ou disponibilidade de peças, mas não para cadastrar a ficha piloto.

## Conflitos

1. Não calcular média silenciosa.
2. Conferir versão, ano, condição e unidade.
3. Manter ambas as fontes.
4. Escolher principal por aderência ao dado e data, documentando a decisão em `methodology_notes`.
5. Se o conflito permanecer material, reduzir confiança ou deixar o campo pendente.

## Fontes demonstrativas

Fonte demonstrativa não pode ser chamada de oficial. Quando secundária e opcional, afeta apenas o grupo. Quando principal de identidade, ficha técnica ou preço, ou quando o próprio registro está marcado, a moto recebe `demonstration_only`.

Não inventar nomes, URLs, instituições, datas ou níveis de confiança. A base demonstrativa usa somente a identificação explícita `Base demonstrativa SIGRA`.
