# Revisão focal dos quatro bloqueios de empacotamento

Esta política não autoriza deploy, acesso a banco ou coleta real. Os pacotes
técnico e acadêmico continuam incluindo testes para reprodução e avaliação,
conforme `ACADEMIC_RELEASE.md`. Nenhum teste foi retirado da varredura ou do ZIP.

## URLs de testes: classificação sem divulgar valores

| Arquivo / linhas revisadas | Evidência de origem fictícia | Uso |
|---|---|---|
| backend/tests/test_deployment_preparation.py:44 | Módulo declarado offline/sintético; configuração construída no teste, senha literal explicitamente sintética, CA/recibo artificiais e fixtures locais. Nenhum segredo é lido do ambiente. | Validar settings, identidade, TLS e rejeição de configurações; não autenticar no endpoint citado. |
| backend/tests/test_revision6_homologation.py:31–33,127–128,149 | Configuração declarada fictícia; doubles SQL em memória, sem engine. URLs de loopback/porta não operacional e domínio reservado `.test` também cobrem rejeição de destino incorreto. | Verificar guards de destino/credenciais e binds de doubles, nunca estabelecer conexão. |
| frontend/tests/academic-cohort.test.mjs:137 | Corpo de erro criado por `fetchImpl` falso, sem requisição de rede. A assertion exige que os detalhes autenticados não apareçam na mensagem pública. | Regressão de sanitização de erro HTTP. |

Esses valores são literais/doubles de teste, não credenciais obtidas de um
cofre, configuração privada ou conta existente. Não se tentou autenticá-los
para classificá-los. Não foram divulgados valores das URLs nesta revisão.

O detector anterior só admitia fixtures Python com usuário **e** senha marcados,
host local e banco terminado em `_test`. Essa regra não cobre, corretamente,
os casos negativos de host/role incorretos e o teste JavaScript de sanitização.
Não se alteram as URLs, sua construção ou suas assertions para enganar o detector.

### Admissão restrita, sem exceção genérica para testes

`REVIEWED_SYNTHETIC_URL_FIXTURES`, em `scripts/release_packaging.py`, fixa estes
três caminhos **e os SHA-256 dos arquivos completos**:

| Arquivo | SHA-256 dos bytes revisados |
|---|---|
| backend/tests/test_deployment_preparation.py | 88934f4d655fe1eb4326524ec92807c53cfc138215caccda35b084acf9f6efc5 |
| backend/tests/test_revision6_homologation.py | 1478c0825c9eef7a4be09dfa78cda2d7068d5a5c8e6a9b760d5b399779ec7205 |
| frontend/tests/academic-cohort.test.mjs | d1dedf26ad8b13d79156ee00e2c6b8df95c9cea101917a0e0e8083234da3ab6f |

Esses hashes históricos correspondem aos bytes CRLF revisados no Windows e
permanecem inalterados. O Git armazenou os três testes em LF; a primeira
regressão do commit `6b25709` admitia apenas CRLF, o que bloqueou o CI Linux.
A admissão agora aceita também a representação **inteiramente LF**, somente
se trocar cada LF por CRLF reconstruir exatamente o hash histórico acima.
Nenhum arquivo é regravado. Não se normalizam espaços, tabs, BOM, campos,
linhas finais ou outros bytes; CR isolado e mistura LF/CRLF continuam bloqueados.
Essa verificação alternativa só é chamada para os três caminhos enumerados.

Prova independente dos blobs Git LF revisados:

| Arquivo | SHA-256 LF | Quantidade de LF / acréscimo de bytes em CRLF |
|---|---|---:|
| backend/tests/test_deployment_preparation.py | b5cb11b983465df8e598749aee0f1f4fd8177f3e86ccb16f93d9e1a3b2a4f1df | 353 |
| backend/tests/test_revision6_homologation.py | 4434f91b238529debf29dad4a649d1fc2088933caf3bb7864ed0f25f72000982 | 437 |
| frontend/tests/academic-cohort.test.mjs | 80c8221fb73c84f7346cde8f537448dcf011058ab1a3b4e80cac85bec01f47b2 | 182 |

As regressões verificam os hashes LF e CRLF completos, a igualdade byte a byte
após trocar exclusivamente CRLF por LF e a preservação dos hashes históricos.
Ambas as representações são coletadas pelo empacotador. Edições em cada uma
(espaço, tab, BOM, conteúdo e newline final), EOL misto e CR isolado bloqueiam.

Todos ainda são examinados por todos os padrões. Só a classificação
`credentialed_database_url`, sozinha, é admitida para esses bytes exatos.
Qualquer edição que mantenha esse finding bloqueia, inclusive se a URL passar
a parecer uma fixture local genérica; não há atualização automática de hash.
Um token/chave adicional continua bloqueando. Copiar para outro caminho não
herda a admissão. A regra local estrita preexistente permanece para os demais
testes, sem ampliação a todos os arquivos ou destinos.

## Plano comprimido: integridade e limite específicos

Arquivo: `build_inputs/revision6/plan.json.gz`.

- Bytes comprimidos originais e preservados: **10.499.497**.
- SHA-256 gzip: `77bde60efdb96e4bfd540055555824319d668991e9020425a9295340e91b620f`.
- Conteúdo restaurado: **192.101.420 bytes**.
- SHA-256 restaurado: `cb70ff5298ffc4c52fc74e44588b2e34a39584b4cacfa6146981670737f3be97`.
- Gate global preservado: **10 MiB = 10.485.760 bytes**; excedente de 13.737 bytes.

Comparação local, sem gravar/substituir o artefato: gzip padrão nível 6 produz
10.819.292 bytes; nível 9 produz os mesmos 10.499.497 bytes. Ambos restauram o
hash original. O header já indica compressão máxima, e o nível 9 já estava em
uso. Reformatar o JSON mudaria o hash restaurado e não é permitido. Nenhum
novo compressor/dependência foi introduzido.

O pacote precisa desse insumo público para os testes Revision6 e para a
montagem reproduzível do Preview. O contrato de restauração existente já fixa
sua identidade. Por isso, `PINNED_LARGE_BUILD_INPUTS` admite **somente** o caminho
acima, com máximo de 10.499.497 bytes, hash comprimido exato e leitura gzip em
blocos limitada a 192.101.420 bytes, exigindo também tamanho/hash restaurados.
A identidade é verificada mesmo se uma substituição for menor que 10 MiB.
Outros arquivos grandes continuam bloqueados. Não se alteram `inputs.json`,
o gzip, o plano, contagens, fingerprints ou referências históricas.

## Verificação reproduzível

```text
python -m unittest discover -s backend/tests -t backend -p "test_release_packaging*.py" -v
python -m unittest discover -s backend/tests -t backend -p "test_motorcycle_stabilization_v031.py" -v
python -m unittest discover -s backend/tests -t backend -p "test_stabilization_patch.py" -v
python scripts/create_clean_package.py --output dist/package-validation/SIGRA-technical.zip
python scripts/build_academic_release.py --output dist/package-validation/SIGRA-academic.zip
```

Usar checkout limpo, Python 3.12 e dependências de `backend/requirements.txt`.
Os relatórios dos dois ZIPs e seus manifestos devem coincidir com os bytes
incluídos. As regressões cobrem edição/cópia das fixtures, segredo adicional,
plano alterado/truncado/maior, gzip inválido, hash/tamanho restaurados e limite
de descompressão. Testes e insumos legítimos continuam no pacote, junto de seus
hashes. Nenhuma configuração privada é necessária para a geração offline.
