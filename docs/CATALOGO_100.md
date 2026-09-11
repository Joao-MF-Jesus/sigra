# Catálogo 100: seleção não equivale a ativação

## Estado parcial

34 modelos legados preservados no código, 66 candidatos selecionados, zero
novos modelos ativados. Não há seed de 100 veículos, migração, escrita na Gold
ou renormalização do ranking. O intake é offline: valida a seleção e a
completude dos dossiês antes da ingestão pelos pipelines existentes. Não é
uma segunda camada Bronze/Silver/Gold nem é chamado pelo startup.

Fonte: `sigra_66_modelos_candidatos.xlsx`, quatro abas integralmente lidas,
sem alteração. SHA-256:
`8e2401a447ab6e39360f03db4f09ed96596123ebd2e9715caeade4ad76f1c884`.
`data_platform/catalog/selection_v1.json` preserva IDs 35–100, versões-alvo,
linhas da planilha, grupos de 11 e os 34 IDs anteriores. Grupo é metadado de
coleta e não entra em TCO, score ou elegibilidade.

## Ausência de dados

O modelo operacional exige valores numéricos para preço, consumo, manutenção,
confiabilidade, peças, depreciação e adequação. A planilha não fornece essas
fichas. `app.sample_data.SEGMENT_DATA` contém notas demonstrativas, não uma
rubrica reproduzível com entradas observáveis para os novos veículos.
Copiar essas notas ou satisfazer NOT NULL com zeros criaria evidência falsa.

Ausência permanece `None`/`unavailable` no dossiê e impede emissão de alvo
de ingestão. Não chamar `ensure_seed_data()` para a expansão: ele também
atualiza registros existentes, não sendo um loader restrito aos novos IDs.

## Contrato do intake v1

- Identidade por revisão explícita: código/ano/descrição/preço/mês FIPE,
  documento e linha PBEV, motor, câmbio, combustível e justificativas para
  sete dimensões de equivalência. Não há fuzzy matching.
- Evidência por campo: observado, derivado, demonstrativo ou indisponível,
  unidade, URL pública, hash, localizador e coleta com fuso horário.
- Decimal, scores 0–100, consumo positivo, moeda não negativa, manutenção
  em BRL/ano. Diesel/híbrido/elétrico não viram gasolina implicitamente.
- Derivados exigem método versionado e entradas. Esses metadados sozinhos
  não comprovam a validade científica nem a reprodução do método.
- Dossiês com a mesma chave FIPE/ano são rejeitados, sem escolha automática.
- Completude resulta apenas em
  `dossier_complete_pending_source_and_integration_validation`, nunca active.
  `fipe_target()` prepara um contrato existente; não consulta nem publica.
- Fixtures completas dos testes são sintéticas, nunca seed ou ficha pesquisada.

Não há adaptador de ativação ainda. A validação de metadados não substitui
revisão da fonte, quality gates produtivos, seed idempotente ou rollback.

## Pesquisa do lote 1

Respostas públicas foram deduplicadas por URL, preservadas por SHA-256 e
data fora do repositório. Reutilizados cliente FIPE, downloader/parser PBEV
e hashes oficiais já auditados. Zero chamadas CarPedia/Fenabrave.
Os resultados abaixo são observações para revisão, não vínculos aprovados.

| IDs | Divergência ou gate específico |
| --- | --- |
| 35–38 | Fontes encontradas; revisão completa e demais campos pendentes. |
| 39 | Linha PBEV C3 1.2 não identifica versão Attraction. |
| 40 | Endpoint FIPE EX consultado não oferece 2018; não prova ausência global. |
| 41 | FIPE informa Gasolina; descrição contém Flex e PBEV informa flex. |
| 42–43 | Fontes encontradas; alias Novo Palio/configuração exigem revisão. |
| 44 | Fiesta/New Fiesta e linha compartilhada SE/SEL exigem vínculo explícito. |
| 45 | Endpoint FIPE LX consultado não oferece 2021. |
| 46–47 | Fontes encontradas; revisão exata e campos restantes pendentes. |
| 48 | PDF PBEV 2019, página 10: FEEL AUT e M-6 na mesma linha, confirmado visualmente. Não corrigir por suposição. |
| 49 | Linha PBEV agrupa Allure/Griffe/Business. |
| 50 | PBEV Elantra sem versão e versão B não distinguem Special Edition. |
| 51–52 | Fontes encontradas; revisão exata e campos restantes pendentes. |
| 53 | Endpoint FIPE Optima 2.0 consultado não oferece 2019. |
| 54–55 | Linhas agrupadas/alias Novo Sentra exigem revisão explícita. |
| 56 | FIPE 2021 retorna GSX, não Pro. PBEV lista ambas; alvo não substituído. |

Todos os 22 ainda carecem de evidência aprovada para campos não fornecidos por
FIPE/PBEV. IDs 57–100 estão selecionados, mas a pesquisa dos lotes 2/3 não
iniciou porque o lote 1 não passou. Relatório externo contém os 66 IDs,
observações FIPE/PBEV, fontes, hashes, campos ausentes e bloqueios individuais.

## Execução offline

Na raiz, executar `backend/.venv/Scripts/python.exe -m data_platform.catalog.cli`
com `--report` apontando para arquivo novo fora do repositório. `--batch`
aceita 1, 2 ou 3; `--dossiers` aceita lista JSON. Sem conexão, seed ou rede.
Exit 2: bloqueio/entrada inválida. Exit 0: somente completude estrutural.
Relatórios existentes não são sobrescritos; erros não ecoam dados rejeitados.

## Próximos gates

1. Aprovar cada configuração FIPE/PBEV do lote 1; resolver contradições pelas
   fontes, sem semelhança textual nem substituição silenciosa de versão.
2. Obter evidências ou rubricas reproduzíveis para os campos restantes,
   sem copiar os 34 demonstrativos ou alterar pesos.
3. Usar Bronze/Silver/Gold existentes, respeitando os payloads FIPE v1/v2
   distintos e todos os gates produtivos.
4. Implementar adapter e seed transacional apenas para novos IDs, preservando
   integralmente os antigos; testar idempotência e rollback.
5. Provar equivalência SQLite/PostgreSQL, ranking dos seis perfis e consumo
   compatível antes de ativar e avançar aos lotes seguintes.
6. Atualizações futuras: FIPE mensal/sob demanda, PBEV por ciclo, ANP semanal;
   CarPedia opcional. Nenhuma agenda foi criada nesta etapa.

Os testes atuais não comprovam 100 ativos, seed, equivalência de bancos ou
homologação visual. A expansão permanece incompleta até esses gates.
