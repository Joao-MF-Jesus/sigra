# Plano de coleta piloto de motocicletas

## Objetivo e escopo

Preparar uma base auditável de aproximadamente 20 a 30 motocicletas do mercado brasileiro, sem scraping nesta etapa. O recorte inicial cobre aproximadamente 100 a 500 cm³ nas categorias scooter, underbone/CUB, street, naked e trail, com modelos novos ou usados recentes voltados a deslocamento urbano, trabalho, iniciantes e uso misto leve.

## Campos obrigatórios

- identificação: marca, modelo, versão, ano, categoria, condição;
- mercado: preço em BRL e data de referência;
- ficha: cilindrada em cm³, potência em cv, torque em Nm, peso em kg, assento em mm e tanque em litros;
- operação: consumos urbano e rodoviário em km/l, transmissão, marchas e transmissão final;
- segurança observável: ABS, CBS e controle de tração, inclusive quando o valor for `false`;
- rastreabilidade: fonte principal de identidade, preço, especificações e
  consumo, nome, referência ou URL, confiança, data de coleta e data de
  referência.

## Campos opcionais

Capacidade de carga, intervalo de óleo quando indisponível na fonte, manutenção estimada, seguro, impostos, confiabilidade, disponibilidade de peças, conforto, bagagem e ergonomia. Ausência permanece vazia/`NULL`, nunca zero.

## Processo

1. Duas pessoas definem a lista de modelos e chaves estáveis.
2. O coletor registra uma linha por fonte no template, repetindo a ficha da moto.
3. Um revisor confere unidade, data, modelo/versão e conflito entre fontes.
4. O validador offline gera erros, avisos e cobertura.
5. O importador é executado primeiro com `--dry-run`.
6. Persistência exige `--confirm-import` e ocorre em uma transação.
7. O importador repete a validação antes de construir objetos e acessar o
   banco. Divergências objetivas por `record_key` bloqueiam o arquivo e listam
   todas as linhas conflitantes; não se escolhe a primeira nem a última linha.

## Comandos

```powershell
python scripts/validate_motorcycle_pilot_data.py backend/data/templates/motorcycle_pilot_collection_v1.csv
python scripts/import_motorcycle_pilot_data.py backend/data/templates/motorcycle_pilot_collection_v1.csv --dry-run
```

O template distribuído contém apenas o cabeçalho para não inventar veículos ou fontes. Ele deve ser duplicado como arquivo de trabalho antes da coleta. O validador não consulta rede nem banco. O dry-run não importa dados, não gera métricas e não gera depreciação.

## Critérios de encerramento

- 20 a 30 registros revisados;
- 100% de cobertura de identidade, preço, ficha técnica e consumo por fonte principal;
- unidades e datas validadas;
- consistência de marca, modelo, versão, ano, categoria, condição, combustível,
  preço, ficha, consumo, transmissão e booleanos em todas as linhas do mesmo
  `record_key`;
- manutenção pode ficar ausente e é tratada como grupo complementar;
- conflitos objetivos bloqueados com linhas e valores documentados;
- nenhuma URL, instituição, confiança ou valor fabricado;
- registro demonstrativo separado da base auditável.
