# Coorte acadêmica v5 — composição parcial e aditiva

A autorização de composição separa o inventário da amostra experimental. A meta
é uma coorte de **60 testáveis**, e não a exclusão dos registros sem evidência.
O inventário materializado no preview parte de 60 identidades e acrescenta
somente os dossiês comprovados nesta rodada. A fila reservada de IDs 35–100
continua intacta; nenhum ID foi criado, reutilizado ou renumerado.

## Resultado desta rodada

`ACADEMIC_COHORT_V5_PARTIAL`: 67 identidades integradas ao inventário do preview,
50 testáveis selecionados, dez vagas não preenchidas. Preservam-se os 43
testáveis anteriores e os 17 legados como holdouts:
1, 6, 7, 9, 11, 13, 17, 18, 19, 21, 23, 24, 25, 26, 27, 28 e 33.
Eles continuam registrados, mas não selecionados nem classificados como
testáveis pela v5. Isso não altera nem reprova seu estado operacional original.

Novas admissões exclusivamente acadêmicas: 62 (Golf Comfortline 2018),
65 (Punto Attractive 2017), 72 (CR-V Touring 2019), 76 (5008 Griffe 2019),
77 (Trailblazer LTZ gasolina 2019), 88 (Accord Touring 2020) e
94 (Tiggo 2 Look 2020). O perfil habilitador é Aplicativo pelo caminho
`academic_habitability_proxy`, não uma certificação de espaço interno ou de
aceitação por plataformas comerciais.

Contagens dos seis perfis: Cidade 10, Aplicativo 50, Trabalho 10,
Espaço/capacidade 24, Família 1 e Estrada 1. Não há nove novos inventários de
segurança admissíveis. `operationally_active=0`, `recommended=0` e ranking
operacional vazio em todos os resultados da v5.

## Contrato e reprodução

`academic_cohort_v5.json` fixa a composição inicial, seus 60 fingerprints,
os holdouts, os IDs adicionais autorizados e a meta. O manifesto de evidência
contém seleções de campos e vínculos revisados, nunca respostas brutas. Cada
entrada é revalidada contra bytes externos por SHA-256, ano, código FIPE,
versão, combustível, câmbio e linha PBEV individual. As grafias distintas
dos três provedores são registradas explicitamente no dossiê; não existe
associação por distância textual ou pesquisa automática na admissão.

`build_cohort(inventory, archive, excluded_ids=())` recebe o inventário original
e um `SourceArchive` local. Falta de cache, hash divergente, identidade
ambígua, unidade inválida ou perda de testabilidade gera falha, nunca fallback.
Excluir um ID logicamente conserva sua linha no inventário; retirar essa
exclusão recompõe a mesma amostra. O módulo não acessa rede, banco ou publicação.

O adaptador v5 reconhece A-10 somente como câmbio automático de dez marchas,
explicitamente confirmado na ficha do Accord. Não modifica o registro de
transmissões da v3. A ausência da palavra turbo no PBEV não significa motor
aspirado: a aspiração mantém o valor explicitamente declarado na ficha técnica.
Combustível e transmissão do preview continuam provenientes do PBEV.

Os cálculos e critérios reutilizam a v4 sem mudar fórmula, peso ou gate. Para
cada admitido, o mesmo perfil precisa passar nos cenários baixo, base e alto.
O TCO usa o contrato acadêmico vigente, 1.000 km/mês e R$ 6/l. Combustível,
IPVA, manutenção, seguro e depreciação calculados são estimativas de cenário,
não custos observados. Ausências observacionais continuam `null/unavailable`.
Largura corporal não supre largura com espelhos. Nenhum equipamento é inferido.

## Rejeições e orçamento

O ID 74 permanece bloqueado: PBEV da versão GL traz aro 17, enquanto a ficha
recebida traz R18. O ID 61 também fica fora da admissão: dimensões 4365/1837/2613
mm não foram reconciliadas com a geração e o ano-alvo; o arquivo oficial de
geração não autoriza corrigir a ficha por transferência de outro ano.

O documento oficial de lançamento do 5008 é de 2018. Seus equipamentos não
foram transferidos para o alvo 2019 sem prova de continuidade da configuração.
As fichas CarPedia coletadas não oferecem inventário explícito completo de
airbags/ABS/ESC. Campo ausente permanece desconhecido, não `false`.

O contrato de coleta registra 9/9 tentativas CarPedia, 11/18 FIPE e 21/21
unidades documentais, sem retry. Estas últimas são 17 buscas de descoberta e
quatro downloads. Os 24 requests diretos retornaram HTTP 200; o mecanismo de
busca não expõe status HTTP de transporte. Uma validação local
da lista de marcas FIPE foi corrigida e o cache revalidado sem repetir a chamada.
Os saldos conservadores são 0, 7 e 0; não se afirma exaustão de fontes oficiais.
Cada consulta de descoberta consome uma unidade do mesmo teto público,
além de cada download; seus resultados não foram promovidos a observações técnicas.

## Limitações e viés

A ficha técnica é uma declaração CarPedia com proveniência de seu fornecedor,
não medição independente nem documento de homologação. O consumo é PBEV e o
preço é a observação FIPE de setembro/2026. Dados com rastreabilidade não
garantem ausência de erro da fonte; conflitos encontrados impedem a admissão.

A seleção favorece disponibilidade documental e códigos individualizáveis.
Não é amostragem probabilística do mercado. Os novos participantes incluem
SUVs e sedãs de preço elevado, o que pode afetar distribuições de TCO.
Não se conclui representatividade, superioridade ou segurança a partir da
testabilidade. Faltam dez dossiês completos para 60; Família/Estrada ainda
necessitam nove inventários exatos adicionais. Nenhuma quantidade foi obtida
flexibilizando os requisitos. A v3/v4 e seus resultados permanecem congelados.
