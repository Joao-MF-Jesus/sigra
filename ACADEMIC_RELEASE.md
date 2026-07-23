# Release acadêmica do SIGRA

O repositório principal privado é a fonte completa e contínua do projeto. A
release acadêmica é uma cópia congelada, criada exclusivamente para avaliação
do Trabalho de Conclusão de Curso.

O comando `python scripts/build_academic_release.py` gera o ZIP em
`dist/academic`, um manifesto com SHA-256 de cada arquivo, metadados com a data
UTC e o commit de origem quando Git estiver disponível, além do hash SHA-256
do próprio pacote. Quando o diretório não for um repositório Git válido, o
commit fica `null`, sem inventar uma origem.

A cópia inclui código executável, testes, documentação, `.env.example`,
arquivos demonstrativos permitidos, migrations Alembic, scripts de migração e
`NOTICE.md`. São excluídos bancos, exports reais de dados,
credenciais, ambientes virtuais, dependências instaladas, caches, logs,
backups, pacotes antigos, artefatos de trabalho, configurações locais de IDE e
traces do Playwright.

## Execução

Consulte o `README.md` incluído no pacote para instalar as dependências e
iniciar backend e frontend. Nenhuma credencial real ou banco de produção é
incluído.

## Limitações

A versão de motocicletas permanece estrutural e não possui Nota SIGRA,
ranking, pesos, TCO ou recomendação. O endpoint reservado continua em HTTP
501. Os dados demonstrativos não representam uma base comercial ou garantia
de mercado.

Autoria: João Marcelo Ferreira de Jesus. A geração do pacote não o publica nem
o envia automaticamente.

## Congelamento desta linha

- automóveis: algoritmo `2.1.2`, pesos `cars-v1`;
- financiamento: módulo `1.0.3`, método `price-v1.2`;
- motocicletas: módulo estrutural `0.3.1`, algoritmo e pesos `null`;
- banco de produção: ausente do pacote;
- finalidade: avaliação acadêmica controlada, sem cessão automática de
  titularidade ou autorização comercial.

## Baseline de estabilização

O identificador técnico desta geração é `stabilization_build=2026.07.1`. Ele
não altera nenhuma versão funcional da API.

Antes da geração, a baseline deve passar pelo comando oficial de backend sem
`PYTHONPATH`, instalação limpa e testes do frontend, build Vite, `compileall`,
regressões congeladas e cinco fluxos Playwright. O banco canônico é
`backend/sigra.db`, mas nenhum SQLite ou backup entra no ZIP. O seed JSON com
as quatro motocicletas demonstrativas é permitido por ser dado acadêmico
declarado e não conter registros reais.

PostgreSQL/Supabase não acompanham credenciais nem dumps. O pacote inclui
somente a migration inicial, o Docker Compose local, os scripts auditáveis e a
documentação necessária para executar a migração em ambiente controlado.
