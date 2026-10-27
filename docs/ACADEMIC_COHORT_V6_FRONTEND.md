# Frontend v6: integração no fluxo de Recomendação

O fluxo vigente é Recomendação, descrito em
ACADEMIC_COHORT_V6_RECOMMENDATION.md. A entrada “Teste acadêmico” foi removida;
não use #academic ou VITE_ACADEMIC_TEST_MODE para selecionar candidatos.
Detalhes, proveniência, formatação e cliente HTTP desta implementação foram
preservados e reutilizados. Abaixo está o registro histórico da primeira entrega,
não instruções para iniciar uma aba separada.

## Histórico da primeira entrega (substituído)

Entrada explícita **Teste acadêmico** na navegação existente, ou URL
`http://127.0.0.1:5173/#academic`. A entrada direta não solicita `/vehicles`,
`/recommendations` nem dados pessoais. Ao voltar ao modo operacional, suas
funcionalidades e seu catálogo continuam independentes. CarPedia permanece
desativada como integração do navegador: evidências já publicadas pela API
podem ter essa proveniência, mas o browser não consulta o provedor.

## Contrato utilizado

O frontend consome exclusivamente `/api/v1/academic-cohort` neste modo:

- `GET /metadata`, versão, fingerprint, snapshot e cobertura;
- `GET /vehicles?limit=20&offset=...&snapshot_id=...`, todas as páginas;
- `GET /vehicles/{catalog_id}?snapshot_id=...`, detalhes e avaliações;
- `POST /evaluate`, perfil, cenário, snapshot, limite por grupo e filtros
  opcionais `max_purchase_price_brl` e `max_monthly_tco_brl`.

Os 60 itens do catálogo são carregados em três páginas da API e apresentados
em páginas de 20. Totais, duplicação, fingerprint e troca de snapshot são
verificados. Um erro não produz catálogo parcial ou fixture substituta.
`eligible_count` é diferente do total apresentado: o limite é **por grupo**.
Grupos e posições são os retornados pelo backend; não há reordenação global.

Perfis sem filtros: Cidade 10, Aplicativo 60, Trabalho 10,
Espaço/capacidade 24 (`suv` no contrato), Família 1 e Estrada 1.
Cenários: baixo (`low`), base e alto (`high`). Quilometragem, preço por litro,
taxas e pesos não são editáveis nesta API, que utiliza cenários congelados.
O formulário não promete que preferências não suportadas afetariam o resultado.

Preço FIPE e mês de referência são individuais. TCO e seus componentes são
estimativas de cenário fornecidas pela API; nenhuma fórmula financeira é
reimplementada. Habitabilidade derivada não é espaço interno medido nem
certificação para plataformas. Cobertura, natureza das evidências, unidades,
fórmulas, entradas, fontes e hashes são apresentados nos detalhes. Confiança
descritiva não é convertida em percentual estatístico.

IDs acadêmicos nunca são enviados a Despesas, cadastro, peças ou “Meu carro”.
Os detalhes não oferecem essas ações. `operationally_active` e `recommended`
devem permanecer falsos; a interface não ativa Gold. Respostas antigas são
descartadas por geração de requisição **e** abort, inclusive sob StrictMode.

## Iniciar sem alterar o banco

Reutilize o backend dedicado já materializado e validado em `8010`.
Se estiver parado, use o procedimento seguro de inicialização do backend em
`docs/ACADEMIC_COHORT_V6_BACKEND.md`, com credenciais somente no ambiente do
processo, `ACADEMIC_COHORT_ENABLED=true`, `DATABASE_ENV=test` e
`FIPE_AUTO_REFRESH=false`. Não execute migrations ou materialização novamente
para iniciar esta interface. Não use o banco de demonstração.

Retomada externa, no terminal em que `DATA_PLATFORM_TEST_POSTGRESQL_URL` já foi
configurada com segurança para o banco materializado:

```powershell
# Exemplo histórico: informe privadamente o launcher local já aprovado.
& '.\backend\.venv\Scripts\python.exe' -B $approvedLocalLauncher
```

Esse launcher externo recusa alvo diferente de PostgreSQL local
`sigra_academic_v6_test`, recusa porta ocupada e recebe a credencial somente
pelo ambiente. Não executa importação ou Alembic. O startup PostgreSQL existente
faz verificações de conexão, não bootstrap SQLite. Logs são sanitizados antes
da saída. `--validate-only` confere somente a configuração, sem conexão ao banco.

No PowerShell, em outro terminal, se a porta `5173` estiver livre:

```powershell
Set-Location -LiteralPath '.\frontend'
$env:VITE_API_URL = 'http://127.0.0.1:8010'
& 'C:\Program Files\nodejs\npm.cmd' run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Abra `http://127.0.0.1:5173/#academic`. Alternativamente,
`VITE_ACADEMIC_TEST_MODE=true` inicia diretamente nesse modo, sem impedir
a navegação operacional. Nenhuma credencial deve usar o prefixo `VITE_`.
Se os serviços já estão ativos, não abra uma segunda instância: use a URL.
Ctrl+C encerra somente o servidor executado naquele terminal.

## Validação e limites

Testes: `npm test`; focais: `node --test tests/academic-cohort.test.mjs`;
build: `npm run build`. Fixtures sintéticas existem somente nos testes unitários.
Esses testes não comprovam PostgreSQL nem substituem a inspeção real:

1. catálogo completo com 60 IDs únicos, três páginas e detalhes;
2. Aplicativo/base sem filtros com 60 elegíveis;
3. troca de cenário e dos seis perfis com as coberturas reais;
4. filtros positivos, resultado vazio e recuperação;
5. detalhes, proveniência, navegação por teclado e responsividade;
6. ausência de erro de renderização e requisições operacionais no modo acadêmico.

Se a API estiver indisponível, a tela mantém erro explícito e botão de nova
tentativa. Não classificar a integração real como homologada nesse estado.
