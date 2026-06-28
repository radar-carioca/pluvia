![Pluvia logo](https://raw.githubusercontent.com/ericmiguel/pluma/v0.1.1/assets/static/logo.png)

Cliente para coleta de dados hidrometeorológicos do Brasil.

## Instalação

```bash
pip install pluvia
```

## Como usar

### Uso via CLI

Após a instalação, o comando `pluvia` fica disponível no PATH do seu ambiente Python.

Por conveniência, o pacote inclui contornos dos estados brasileiros (IBGE) embutidos.

```bash
pluvia --state SP --start 2026-01-01 --end 2026-06-30 --output ./dados
```

Para filtrar estações por qualquer limite vetorial (bacias hidrográficas, municípios, áreas de estudo etc.):

```bash
pluvia --shapefile ./bacias.shp --shape-column codigo --shape-id 01 --output ./dados
```

| Argumento         | Descrição                                                                                    |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `--state`         | Sigla do estado brasileiro (ex: CE, SP, RJ). Obrigatório se `--shapefile` não for informado. |
| `--start`         | Data de início no formato YYYY-MM-DD (padrão: ontem).                                        |
| `--end`           | Data de fim no formato YYYY-MM-DD (padrão: hoje).                                            |
| `--output`        | Diretório para salvar os dados CSV (padrão: diretório atual).                                |
| `--rebuild`       | Ignora o cache e re-consulta todas as estações.                                              |
| `--update-active` | Re-consulta estações ativas mesmo que o intervalo já esteja coberto (padrão: True).          |
| `--shapefile`     | Caminho para shapefile vetorial customizado (.shp, .gpkg, .geojson).                         |
| `--shape-column`  | Coluna de atributo do shapefile para filtrar (padrão: `acronym`).                            |
| `--shape-id`      | Valor do ID na coluna de atributo do shapefile.                                              |
| `--station-type`  | Tipo de estação: `fluviometrica`, `pluviometrica`, `telemetric`.                             |

### Uso via API

```python
import pluvia

client = pluvia.ANA()

# Contornos embutidos (estados brasileiros)
stations = client.get_stations(
    contour="uf.shp", column="acronym", value="SP"
)

# Shapefile customizado
stations = client.get_stations(
    contour="./bacias.shp", column="codigo", value="01"
)

# Filtro por tipo de estação
stations = client.get_stations(
    contour="uf.shp", column="acronym", value="SP",
    station_type="fluviometrica"
)

data = client.fetch_data(
    stations=stations,
    start="2026-01-01",
    end="2026-06-30",
    variable="chuva",  # chuva, nivel, vazao, cota
    rebuild=True,  # força re-consulta completa (use na primeira execução)
    update_active=True,  # re-consulta estações ativas mesmo com cache válido
)
```

## Caching

O serviço de dados da ANA (Agência Nacional de Águas) é lento e com limitações diversas.
Para otimizar o uso dos dados, a biblioteca implementa uma estratégia de caching incremental
e orientado a intervalos.

1. Apenas os períodos ainda não baixados são consultados na API.
2. O inventário de estações é re-buscado apenas quando expira (padrão: 7 dias).
3. Estações sem dados são marcadas como inativas e re-consultadas com TTL dinâmico.
4. Erros de rede consecutivos colocam a estação em cooldown de 24 h.

O TTL dinâmico dita a frequência com que as estações são re-consultadas:

- diariamente se tiveram dados recentes
- a cada 3 dias se o último dado tem entre 30 dias e 1 ano
- semanalmente se ainda mais antigo

Essa estratégia visa reduzir tempo de coleta de dados ao mesmo tempo em que busca não
desperdiçar estações que, por eventual (milagre) voltem a operar ou que tenham sofrido
interrupções temporárias no serviço.

## Desenvolvimento

```bash
pixi run -e dev lint        # ruff check
pixi run -e dev format      # ruff format
pixi run -e dev typecheck   # pyrefly
pixi run test               # pytest
```

### Build e publicação no PyPI

O projeto usa [Conventional Commits](https://www.conventionalcommits.org/) e versionamento
semântico automatizado com `bump-my-version`. O changelog é gerado automaticamente com
`git-cliff` a partir dos commits seguindo Conventional Commits.

Configure um token em [pypi.org/manage/account/token](https://pypi.org/manage/account/token/) e salve em `~/.pypirc`.

```ini
# ~/.pypirc
[pypi]
username = __token__
password = pypi-xxxxxxxxxxxx
```

Siga o fluxo para release de uma nova versão:

```bash
# 1. Atualizar versão (cria tag automaticamente)
pixi run -e dev bump        # patch
pixi run -e dev bump minor  # minor
pixi run -e dev bump major  # major

# 2. Atualizar changelog
pixi run -e dev changelog

# 3. Build
pixi run -e dev build

# 4. Publicar (requer API token no PyPI)
pixi run -e dev publish
```
