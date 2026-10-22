# Preparação isolada da integração documental Revision6

## Decisão de escopo, não aprovação documental nova

Meta original: dez opções em Família e Estrada. Cobertura comprovada: nove,
nos cenários baixo, base e alto. O usuário autorizou prosseguir com nove e
encerrar a busca do décimo inventário. O resultado histórico `TARGET_NOT_MET`
permanece verdadeiro. Não foi criada Revision7 nem alterado teste para declarar dez.

A candidata continua inativa e não aprovada para substituir o snapshot padrão.
Os nove IDs são 31, 34, 44, 55, 62, 76, 80, 108 e 124. Completude não é igualdade
de equipamentos: Fiesta 44 mantém ESC explicitamente ausente e índice inferior.

## Fronteira aditiva proposta

`app.academic_cohort.safety_revision6.prepare_revision6(bundle, decision_file)`
valida o pacote fixado por hash, o replay V6 aprovado pelo contrato original,
as mesmas 60 identidades, os holdouts e a decisão humana separada. Reexecuta
as 1.080 avaliações com os avaliadores existentes, sem alterar suas fórmulas,
pesos, custos ou elegibilidade eliminatória. Mantém os dados e a proveniência
integrais nos registros de transporte e fornece preview diagnóstico somente em memória.

O tipo `InactiveRevision6Proposal` não é `MaterializationPlan` e não expõe
os atributos aceitos pelo materializador existente. Não há conexão, escrita,
endpoint, variável de seleção automática ou importação de código arbitrário
do pacote. `assert_write_allowed()` falha sempre. Nenhum módulo de runtime
existente é modificado ou importa esta proposta. O V6 aprovado continua sendo
o único snapshot padrão reconhecido pelo importador, repositório e serviço.

O contrato aditivo fixa fingerprint da candidata, inventário dos arquivos,
manifesto do método local, nove IDs, contagens e escopo documental acumulado.
Não relaxa `contracts.validate_replay`; esse contrato continua rejeitando Revision6.

## Evidências e limites que permanecem

- Tiguan 70: proposta Vega/TCM-PA não é publicação Volkswagen. Os três campos
  permanecem desconhecidos; aceitar cobertura nove não altera a política de fontes.
- Cruze 46: 1.807 mm corporal e 2.042 mm entre retrovisores. Manual Brasil MY2020,
  SHA-256 `d8b6d5be870780ffa2f80e0f3a26c2218225322b28c20804a1640e81e74f829f`,
  página PDF 306/impressa 303. A dimensão nominal não comprova equipamentos LT.
- Rio 102: quantidade total de airbags desconhecida; ABS/ESC preservados.
- Kicks 123: conflito de airbags não resolvido; nenhuma escolha arbitrária.
- Capturas normalizadas Ford, Honda e Volkswagen preservam limitações de acesso
  ao original e hashes de representação distintos. Não se chama captura de PDF original.
- Não se incorpora o experimento de altura livre ou outra candidata automaticamente.

## Reprodução offline

Python 3.12, Pydantic 2.x e dependências já instaladas do projeto. Não instalar
automaticamente nem consultar rede. Extrair o ZIP Revision6 sem alterar seus
membros e confirmar o SHA-256 do arquivo:

`6b5bc897167b676f6a19bee4d89536e42b5184413ac69d0d7e449c9f26d7daa7`.

Na pasta do pacote:

```powershell
python -B -I candidate_builder.py --verify-bundle
python -B -m unittest -v test_revision6
```

Na cópia do projeto, informar somente caminhos de artefatos, nunca credenciais:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
$env:SIGRA_REVISION6_BUNDLE = 'CAMINHO_ABSOLUTO_DA_EXTRACAO\SIGRA_Seguranca_V6_Revision6'
$env:SIGRA_REVISION6_DECISION = 'CAMINHO_ABSOLUTO\user-decision.json'
python -B -m unittest discover -s backend/tests -p test_academic_safety_revision6.py -v
```

Os testes exigem caminhos explícitos e não têm fallback para banco ou SQLite.
O registro da decisão humana contém meta, cobertura, aceite e permissões negadas;
não é um campo de evidência dos veículos.

## Pendências para homologação PostgreSQL — NÃO executadas nesta etapa

1. Revisar o patch e autorizar sua aplicação em checkout separado. Preservar V6,
   os fingerprints atuais e as alterações preexistentes.
2. Definir um namespace de snapshot candidato e seleção explícita de homologação;
   não trocar o default V6 nem alterar suas constantes de cobertura. Esta proposta
   não implementa importação ou ativação da candidata.
3. Autorizar um PostgreSQL exclusivo, vazio e descartável. Confirmar host, banco,
   role e identidade, sem imprimir URL autenticada; nenhum banco existente serve
   como substituto dessa verificação. Este passo exige infraestrutura e aprovação.
4. Revisar uma importação separada para candidata e auditorias de leitura com
   fingerprint fixado, coexistência com V6, 60 veículos/1.080 avaliações, replay,
   idempotência e rollback transacional. Nunca passar o tipo desta proposta ao
   materializador V6 atual.
5. Executar as regressões PostgreSQL reais, incluindo adulteração, duplicação,
   isolamento, grants/RLS e seleção exclusiva por snapshot. Não trocar por SQLite.
6. Validar API e navegador com o motor real, nove opções documentadas em Família/
   Estrada, custos baixo/base/alto e limitações de critérios; registrar versão e
   fingerprint em cada execução do participante. Não confundir esse passo com
   os previews offline que já foram testados.

## Publicação/deploy — preparado como sequência, não autorizado

Após homologação aprovada: confirmar protocolo acadêmico/consentimento/retenção,
destinos React/FastAPI/PostgreSQL, plano/custo, backup e restauração, TLS verify-full,
HTTPS, cookies seguros, CORS por origem exata, autenticação e isolamento dos
participantes, administrador e exportação pseudonimizada. Exigir teste real após
reinício da API e plano de reversão por seleção de snapshot. Só então solicitar
autorização explícita para ativação/publicação e deploy. Nada disso é executado
por esta proposta de preparação.
