# SIGRA Frontend V2

## Objetivo e base protegida

A Frontend V2 transforma a recomendação em uma jornada guiada, responsiva e explicável sem alterar os contratos de domínio. A implementação nasceu na branch `feature/frontend-v2`, criada diretamente da tag anotada `tcc-apresentacao-v1.0.0` (commit `85db2483a1012c066dd224420c5434b78182c0f0`). O banco, as migrations e os datasets Gold desse setpoint permanecem fora do escopo.

## Princípios de experiência

- Uma decisão principal por etapa: necessidade, orçamento, prioridades, ajustes opcionais e revisão.
- Valores preenchidos permanecem no estado React quando a pessoa avança ou volta.
- O perfil multifator fica sob divulgação progressiva e desativado por padrão.
- A tela de revisão distingue parâmetros do usuário, resultado derivado e fontes publicadas.
- Loading, vazio, erro, conflito, indisponibilidade, sucesso, resultado anterior e resultado desatualizado possuem estados próprios.
- A comparação, os detalhes, a simulação configurável e o financiamento continuam acessíveis sem serem misturados em uma única decisão.

## Identidade visual

A paleta usa tokens centralizados em `frontend/src/styles.css`:

- grafite: `#101214`, `#191C1F`, `#22262A` e `#34383D`;
- bronze: `#B7793E` e `#CE9255`;
- texto: `#F3F0EA` e `#AAA7A1`;
- estados de sucesso, alerta e erro possuem cores adicionais com contraste sobre superfícies escuras.

O conteúdo ocupa a largura disponível, limitado a 1760 px para leitura em telas grandes. Não existe sidebar dominante. O cabeçalho reúne marca, fontes ativas e navegação.

## Componentes e responsabilidades

- `AppHeader.jsx`: marca, navegação principal, sessão e menu móvel.
- `RecommendationForm.jsx`: apresentação e interação do fluxo guiado.
- `recommendationWizardModel.js`: passos, navegação determinística, roteamento de erros e resumo da revisão.
- `RecommendationPage.jsx` e `RecommendationResults.jsx`: contexto, estados e grade de resultados.
- `VehicleCard.jsx` e `RecommendationDetails.jsx`: síntese, evidências, explicação e aprofundamento.
- `VehicleCostSimulationPanel.jsx`: coleta parâmetros e exibe apenas resultados calculados pelo backend.
- `FinancingPage.jsx` e seus componentes: fluxo financeiro independente da recomendação.

## Fluxo

1. A pessoa escolhe automóvel ou consulta a disponibilidade do módulo de motocicletas e informa o uso principal.
2. Informa orçamento de compra e limite mensal de uso.
3. Define prioridade, quilometragem e referência de combustível.
4. Se desejar, habilita o perfil multifator e seus parâmetros explícitos.
5. Revisa o perfil antes de solicitar a recomendação.
6. Compara ranking, confiança e evidências; pode abrir detalhes, comparar alternativas e simular custo.

O botão Voltar preserva respostas. Se a validação final encontrar um erro, o fluxo retorna à primeira etapa que precisa de correção.

## Responsividade e acessibilidade

- desktop amplo: margens fluidas de 24 a 64 px e grade de resultados com até quatro cards conforme o espaço real;
- desktop/notebook: três cards quando comportados;
- tablet: duas colunas e formulário acima do resultado;
- celular (incluindo 390 × 844): uma coluna, ações em largura total e modal em tela cheia;
- zoom de 200%: as grades colapsam sem overflow horizontal da página.

Controles possuem alvo mínimo de 44 px, foco visível, labels e mensagens associadas, landmarks semânticos, `aria-current` na navegação e modal com Escape, contenção de foco e restauração do elemento anterior. Animações são reduzidas com `prefers-reduced-motion`.

## Contratos preservados

- O ranking legado permanece idêntico quando `multifactor_profile` não é solicitado.
- O backend continua responsável por ranking, Decimal, TCO, simulação e financiamento.
- A Gold permanece somente leitura e é consultada pelos endpoints existentes.
- Preferências e resultados derivados não são persistidos pelo fluxo guiado.
- Erros 409, 422 e 503 continuam sanitizados pela camada de API/apresentação.
- Identidade Gold ausente ou ambígua aparece como indisponível; nunca recebe associação automática ou nota zero inventada.
- FIPE continua responsável por preço/identidade comercial, PBEV por consumo/eficiência e ANP por preços de combustível.

## CarPedia

CarPedia não é uma fonte ativa no navegador. `CARPEDIA_UI_ENABLED` permanece `false`; não existe chamada, endpoint, token ou chave CarPedia no frontend. Uma futura ativação deve depender de contrato de backend versionado, campos opcionais e evidência publicada válida.

## Execução e testes

```powershell
Set-Location frontend
npm test
npm run build
npm run test:e2e
```

Não há script de lint configurado no pacote atual. Os testes cobrem modelos, contratos de API, fluxo guiado, avanço/retorno, preservação de respostas, estados, financiamento, simulação, ambiente E2E e a flag CarPedia desabilitada.
