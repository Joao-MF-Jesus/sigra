# Fotografias estáticas dos veículos

Implementação isolada a partir de main `ebb0f886a18c658f963ce633d74b839447cc3129`.
Não altera o catálogo, a API, o motor, os pesos, as notas ou os fingerprints.
Coleta real permanece desligada; `historical_row_changed=1` permanece preservado.
Nenhum merge, push, deployment ou acesso ao Neon faz parte desta entrega.

## Cobertura e correspondência

Foram admitidas **53 fotografias, cobrindo os 60 registros**. As versões Kicks
S/SV/SL, WR-V EX/EXL, Rio LX/EX, City LX/EX/Personal e Arrizo 5 RX/RXT compartilham
a foto da mesma carroceria/geração. Nenhum fallback conta como cobertura.
As 20 fotografias da entrega anterior, seus metadados e 40 arquivos foram
preservados integralmente; `ADMITTED20.json` é o recibo público imutável dessa
admissão, não uma nova referência metodológica ou de catálogo.

Consulte [VEHICLES.md](VEHICLES.md) para todos os IDs, anos, gerações, autores,
fontes, licenças e pendências. [SOURCES.json](SOURCES.json) preserva as fontes
públicas, revisões, hashes originais e transformações das imagens admitidas.
O manifesto de apresentação está em
`frontend/src/features/vehicle-images/vehiclePhotos.json`.

O vínculo acadêmico exige namespace, catalog_id inteiro e rótulo exatos. Quando
presentes, ano FIPE, chave canônica e fingerprint também precisam coincidir.
IDs operacionais nunca são reutilizados como IDs acadêmicos; apenas tuplas
explícitas de marca/modelo/ano conferidas no catálogo local possuem alias.
Marca semelhante, substring, URL enviada pela API ou modelo aproximado não
selecionam uma foto. Identidade desconhecida ou divergente produz fallback.

Todas as fotos são ilustrativas do modelo. Acabamento, mercado, motorização e
ano ilustrado podem diferir, dentro da carroceria/geração conferidas. O ano
do catálogo e o da fotografia são separados na matriz. No Fit, a fonte
identifica o intervalo 2017–2020, não um ano exato de fabricação. Onde a fonte
informa apenas a data da foto (Grand Siena, Arrizo 5 e Doblò), não se inventa um
ano-modelo. City híbrido estrangeiro, Arrizo GX/6 e Suran/SpaceFox possuem notas
explícitas de correspondência. Consulte [REVIEW.md](REVIEW.md) para esses casos e
as fontes rejeitadas por geração/carroceria divergentes.

## Licenças e otimização

Fotografias reais do Wikimedia Commons, não imagens geradas por IA. O crédito,
fonte e licença ficam visíveis em cards, comparação e detalhes. As derivadas
mantêm a licença original, inclusive ShareAlike quando aplicável; isso não
relicencia o código da aplicação. Conversão para WebP, retirada de metadados e
redução proporcional em 480/960 px, sem recorte. Os SHA-256 dos arquivos locais
e o SHA-1 do original estão preservados. Os nomes possuem hash de conteúdo.
O link CC0 da fonte que usava HTTP é apresentado em HTTPS, sem alterar o recibo.
Marcas e fabricantes não patrocinam nem endossam o SIGRA.

As 106 variantes totalizam **5.988.680 bytes (5,71 MiB)**. O navegador seleciona uma variante
por foto via srcset, com carregamento preguiçoso e decodificação assíncrona.
O quadro 16:10 reserva espaço e usa object-fit:contain, sem cortar o automóvel.
Falha de carregamento mantém o quadro e substitui a imagem por texto neutro.

## Separação da Function Python

No checkout, as fotos são assets de `frontend/public/assets/vehicle-photos`.
Na montagem pública revisável, são copiadas para
`public-assets/vehicle-photos`, fora do diretório `application` protegido pelo
manifesto Python. O build verifica o conjunto exato e cada hash antes de copiá-las
para `application/frontend/dist/assets/vehicle-photos`. Somente esse diretório
gerado e a entrada externa foram acrescentados a excludeFiles. dist deixou de
ser incluído explicitamente para não reintroduzir as fotos após essa exclusão;
os demais arquivos dist continuam sujeitos ao glob padrão, sem mudar os guards.
includeFiles continua uma string.
As rotas /assets já estão fora do rewrite de SPA.

O guard de release continua comparando o conjunto integral e todos os hashes dos
fontes Python/aplicação. Não se introduziu exclusão genérica de imagens nesse
guard. O empacotador de fontes admite somente WebP do caminho dedicado, com
nome, tamanho máximo de 300.000 bytes e hash declarados no manifesto; mídia
arbitrária continua excluída ou bloqueada.

`correspondence.json` e `source-revisions.json` históricos ficam intactos.
A nova `vehicle-photos-revision.json` registra apenas o delta contra a candidata
da main `sigra-710d5e8c13a8b665a00fe658`, com nova identidade de conteúdo.
Isto não é um deployment nem uma atualização da versão remota.

## Reprodução local, sem banco

Na raiz do checkout, com Python e dependências backend já instalados:

```powershell
npm --prefix frontend ci --ignore-scripts
node --test frontend/tests/*.test.mjs
node deploy/build_vercel.mjs
python -m pytest backend/tests/test_preview_source_additions.py backend/tests/test_reproducible_preview_build.py backend/tests/test_vehicle_photo_assets.py -q
node frontend/node_modules/playwright/cli.js install chromium
Set-Location frontend
node node_modules/playwright/cli.js test --config=playwright.photos.config.js
```

Os testes de fotos usam apenas a porta loopback 14221 e respostas HTTP locais
simuladas. Não calculam recomendações nem acessam autenticação/banco reais.
Bloqueiam requisições do navegador a outras origens. Não substituem o E2E do
motor ou uma homologação remota.

No perfil isolado Windows, pode ser necessário apontar
`PLAYWRIGHT_BROWSERS_PATH` ao Chromium 1228 existente. Se for iniciado um Vite
separado para esses testes, use obrigatoriamente `VITE_API_URL=/sigra-api`,
`VITE_PUBLIC_DEMO_MODE=false`, `VITE_ACADEMIC_TEST_MODE=false`, host 127.0.0.1 e
porta 14221 com strictPort. Só nesse caso use
`SIGRA_PHOTO_LOCAL_SERVER_STARTED=true`; encerre apenas o servidor dessa execução.

## Limitações

- Cobertura estática completa dos 60 registros; não prova a identidade de futuros
  modelos/anos adicionados ao catálogo. Identidades não revisadas continuam sem foto.
- As fotos não provam equipamentos, acabamento ou condição de uma unidade.
- Novo bundle completo da Function Linux e deployment remoto não foram
  executados nesta etapa. A seleção de arquivos usa o glob do SDK oficial
  pinado (Python 25.1.3 / build-utils 14.21.3), incluindo o merge de includeFiles
  depois de excludeFiles. O teste reproduziu 80 entradas de fotos com a primeira
  configuração e produziu zero com a correção. O mesmo guard foi adicionado
  ao build Linux para bloquear regressão antes de construir a Function.
- Dependências frontend existentes foram preservadas. O npm informou seis
  alertas de auditoria preexistentes (um moderado e cinco altos); não foi
  aplicado upgrade automático dentro da tarefa de fotos.
