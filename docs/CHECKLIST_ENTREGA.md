# Checklist de entrega

## Antes da apresentacao

- [ ] Backend inicia sem erro.
- [ ] Frontend inicia ou build estatico abre sem erro.
- [ ] `/health` retorna `status: ok`.
- [ ] `/docs` abre a documentacao da API.
- [ ] Login de usuario funciona.
- [ ] Login de admin funciona.
- [ ] Modo visitante abre sem login.
- [ ] Visitante consegue alterar perfil e gerar recomendacao.
- [ ] Visitante nao consegue registrar despesa sem login.
- [ ] `/health` mostra pelo menos 30 veiculos.
- [ ] Recomendacao gera ranking.
- [ ] Recomendacao muda entre cidade, estrada, app, familia e SUV.
- [ ] Ficha tecnica abre.
- [ ] Comparacao exibe veiculos.
- [ ] Busca online abre links demonstrativos.
- [ ] Registro de despesa funciona.
- [ ] Aba "Meu carro" abre apos login.
- [ ] Cadastro de veiculo do usuario funciona.
- [ ] Registro de problema funciona.
- [ ] Registro de consumo real funciona.
- [ ] Historico mostra alertas preventivos e estatisticas do modelo.
- [ ] Recomendacao mostra destaques por categoria e ajuste por dados reais quando aplicavel.
- [ ] Aba "Pecas" abre e mostra Indice SIGRA de Manutencao.
- [ ] Analise de pecas mostra menor preco, maior preco, media e variacao.
- [ ] Alertas de preco/fornecedor aparecem quando aplicavel.
- [ ] Recomendacao exibe destaques de manutencao e pecas.
- [ ] Painel admin exibe resumo.
- [ ] ZIP limpo nao contem `.git`, `.venv`, `node_modules`, `dist`, `work`, `outputs`, `.db`, logs ou outro ZIP.
- [ ] O arquivo enviado para a banca e `SIGRA-entrega-final.zip`.
- [ ] A pasta completa do ambiente local nao foi enviada.

## Comandos uteis

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Frontend dev:

```powershell
cd frontend
npm run dev
```

Frontend estatico:

```powershell
cd frontend
npm run build
cd dist
..\..\backend\.venv\Scripts\python.exe -m http.server 4173 --bind 127.0.0.1
```

Testes:

```powershell
python -m unittest discover -s backend/tests -t backend -v
```

Build:

```powershell
cd frontend
npm run build
```

Pacote limpo:

```powershell
.\scripts\create-clean-package.ps1 -OutputPath SIGRA-entrega-final.zip
```

Alternativa com Python:

```powershell
python scripts\create_clean_package.py --output SIGRA-entrega-final.zip
```

Instalacao limpa do frontend:

```powershell
cd frontend
npm ci
npm run build
```

## Riscos principais no dia

- Abrir `http://127.0.0.1:8000/` mostra `Not Found`; a interface fica no frontend.
- Se a porta `4173` nao responder, rode o servidor estatico dentro de `frontend/dist`.
- Se o banco local antigo causar resultado estranho, apague `sigra.db` e reinicie a API para recriar a base demonstrativa.
- Lembre de explicar que login, imagens, links e precos sao demonstrativos no MVP.
- Nao compacte manualmente a pasta raiz do projeto; use o script de pacote limpo.

## Credenciais demo

Usuario:

- Email: `usuario@sigra.local`
- Senha: `usuario123`

Admin:

- Email: `admin@sigra.local`
- Senha: `admin123`
