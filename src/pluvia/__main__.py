"""CLI simples para catalogação de estações hidrometeorológicas da ANA.

Parâmetros básicos:
  --state        Sigla do estado brasileiro (ex: CE, SP, RJ)
  --start        Data de início no formato YYYY-MM-DD
  --end          Data de fim no formato YYYY-MM-DD (deve ser >= start)
  --output       Diretório para salvar os dados (padrão: ./)
  --rebuild      Ignora o cache e re-consulta todas as estações (padrão: False)
  --update_active
                 Re-consulta estações ativas mesmo que o intervalo já esteja
                 coberto (padrão: True)

Parâmetros avançados (shapefile customizado):
  --shapefile    Caminho para shapefile vetorial customizado
  --shape-column Coluna de atributo do shapefile para filtrar (padrão: acronym)
  --shape-id     Valor do ID na coluna de atributo do shapefile
  --station-type Tipo de estação: fluviometrica, pluviometrica, telemetric
"""

from __future__ import annotations

import argparse
import datetime
import logging
from pathlib import Path
from typing import Literal
from typing import get_args

import pandas as pd
from rich.console import Console

import pluvia

# Tipagem firme para siglas dos estados brasileiros
BrazilianState = Literal[
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
]

BRAZILIAN_STATES: tuple[str, ...] = get_args(BrazilianState)

pluvia.setup_logging(level=logging.INFO)

logger = logging.getLogger("pluvia.cli")


def _valid_date(value: str) -> datetime.date:
    """Parseia e valida uma data no formato YYYY-MM-DD."""
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Data inválida '{value}'. Use o formato YYYY-MM-DD."
        ) from exc


def _valid_state(value: str) -> str:
    """Converta o estado para caixa alta e valide."""
    upper = value.strip().upper()
    if upper not in BRAZILIAN_STATES:
        allowed = ", ".join(BRAZILIAN_STATES)
        raise argparse.ArgumentTypeError(
            f"Estado inválido '{value}'. Valores permitidos: {allowed}"
        )
    return upper


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Configura e retorna os argumentos da CLI."""
    parser = argparse.ArgumentParser(
        description="Cataloga e baixa dados hidrometeorológicos da ANA.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--state",
        type=_valid_state,
        default=None,
        help="Sigla do estado brasileiro (ex: CE, SP, RJ). "
        "Obrigatório se --shapefile não for informado.",
    )
    parser.add_argument(
        "--start",
        type=_valid_date,
        default=None,
        help="Data de início no formato YYYY-MM-DD (padrão: ontem).",
    )
    parser.add_argument(
        "--end",
        type=_valid_date,
        default=None,
        help="Data de fim no formato YYYY-MM-DD (padrão: hoje).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=".",
        help="Diretório para salvar os dados CSV (padrão: diretório atual).",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        default=False,
        help="Ignora o cache e re-consulta todas as estações.",
    )
    parser.add_argument(
        "--update-active",
        dest="update_active",
        action="store_true",
        default=True,
        help=("Re-consulta estações ativas mesmo que o intervalo já esteja coberto."),
    )
    parser.add_argument(
        "--shapefile",
        type=str,
        default=None,
        help="Caminho para shapefile vetorial customizado (.shp, .gpkg, .geojson).",
    )
    parser.add_argument(
        "--shape-column",
        type=str,
        default="acronym",
        help="Coluna de atributo do shapefile para filtrar (padrão: acronym).",
    )
    parser.add_argument(
        "--shape-id",
        type=str,
        default=None,
        help="Valor do ID na coluna de atributo do shapefile.",
    )
    parser.add_argument(
        "--station-type",
        type=str,
        default=None,
        choices=["fluviometrica", "pluviometrica", "telemetric"],
        help="Tipo de estação para filtrar.",
    )

    parsed = parser.parse_args(args)

    # --state é obrigatório se --shapefile não foi fornecido
    if parsed.shapefile is None and parsed.state is None:
        parser.error("--state é obrigatório quando --shapefile não é informado.")

    # --shape-id é obrigatório se --shapefile foi fornecido
    if parsed.shapefile is not None and parsed.shape_id is None:
        parser.error("--shape-id é obrigatório quando --shapefile é informado.")

    today = datetime.date.today()
    if parsed.end is None:
        parsed.end = today
    if parsed.start is None:
        parsed.start = today - datetime.timedelta(days=1)

    if parsed.end < parsed.start:
        end = parsed.end.isoformat()
        start = parsed.start.isoformat()
        parser.error(f"--end ({end}) não pode ser menor que --start ({start}).")

    return parsed


def _print_banner() -> None:
    """Imprime o banner ASCII do pluvia."""
    console = Console()
    console.print(
        "[bold cyan]\n"
        """
▐▀▀▀▀▀▀▀▀▀█▄▄   ▐▀▀▀▀█        ▀▀▀▀▀▀▀      ▀▀▀▀▀▀▀▀▀▀▀▀▀      █▀▀▀▀█▀▀▀▀▀▀▀▀     ▄▄███▄▄     
▐ ████████████▄ ▐ ████        ▀▀▀▀▀▀▀      ▀▀▀▀▀▀▀▀▀▀▀▀▀      ██████▀▀▀▀▀▀▀▀   ▄█▀▄▄▄▄▄██▄   
▐▀▀▀▀▀▀▀▀█▀████▌▐ ████        ▀▀▀▀▀▀▀      ▀▀▀▀▀▀▀▀▀▀▀▀▀      ██████▀▀▀▀▀▀▀▀  █▀▄██████████  
▐ █ █ ▄▄▄█ ████▌▐ ████        ▐█▀▀▀▀█      ██████▐▀▀▀▀▀█      ██████ █▀▀▀▀█  ▐▌▐███████████▌ 
▐ █ █ ██▄▄████▀ ▐ ████        ▐█ ████      █ ████▐ █████      █ ████ █ ████  █ ████▀  ▀▀▀▀▀▀ 
▐ █ █ ██████▀ ▄ ▐ ████        ▐█ ████      █ ████▐▄▀████▌    ▐█ ████ █ ████ ▐▌▐███▌ ▀▀▀▀▀▀▀▀ 
▐ █ █ ▀▀▀▀▀ ▄▀  ▐▄████        ▐█ ████▄    ▄█ ████ █▄▀████    ██████▌ █ ████ █ ████ ▀▀▀▀▀▀▀▀▀▀
▐ █ █ ▀▀▀▀▀▀    ▄▄▄▄▄▄▄▄▄▄▄▄▄▄ █▄▀█████████▄█████  █▄▀████▄▄█▀▄████  █ ████ █ ████ ▀▀▀▀▀▀▀▀▀▀
▐ █ █           ▄▄▄▄▄▄▄▄▄▄▄▄▄▄  ▀█▄▀▀██████████▀  ▄ ▀█▄▀███▄▄████▀ ▄ █ ████ █ ████ ▀▀▀ █▀████
▐ █ █           ▄▄▄▄▄▄▄▄▄▄▄▄▄▄ ▀▄ ▀▀████████▀▀ ▄▀  ▀▄ ▀▀██████▀▀ ▄▀  █▄████ █▄████     █▄████
▄ ▄ ▄           ▄▄▄▄▄▄▄▄▄▄▄▄▄▄   ▀▀▄▄▄▄▄▄▄▄▄▄▀▀      ▀▀▄▄▄▄▄▄▄▄▀▀    ▄▄▄▄▄▄ ▄▄▄▄▄▄     ▄▄▄▄▄▄
        """
        "\n"
        "Cliente para coleta de dados hidrometeorológicos do Brasil.\n"
        "[/bold cyan]",
        markup=True,
    )


def _resolve_shapefile_path() -> str:
    """Retorna o caminho real no sistema de arquivos para o shapefile de estados brasileiros.

    Usa ``importlib.resources`` para localizar os dados dentro do pacote,
    garantindo que funcione tanto em instalação editable quanto em wheel
    (zip). Se os arquivos estiverem dentro de um zip, extrai todos os
    componentes do shapefile para um diretório temporário.
    """
    import tempfile
    from importlib.resources import files

    shapes_dir = files("pluvia").joinpath("data", "shapes")
    shp_ref = shapes_dir.joinpath("uf.shp")

    # Se já é um Path real no sistema de arquivos (editable / sdist), usa direto
    if isinstance(shp_ref, Path):
        return str(shp_ref)

    # Se é um ZipPath (wheel instalado), extrai todos os componentes para temp
    tmp_dir = Path(tempfile.gettempdir()) / "pluvia_shapes"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for item in shapes_dir.iterdir():
        dest = tmp_dir / item.name
        if not dest.exists():
            dest.write_bytes(item.read_bytes())

    return str(tmp_dir / "uf.shp")


def _save_data(data: dict[str, pd.DataFrame], output_dir: Path) -> None:
    """Salva os dados coletados em arquivos CSV no diretório de saída."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for code, df in data.items():
        filepath = output_dir / f"{code}.csv"
        df.to_csv(filepath, index=False)

    logger.info("Dados salvos em: %s", output_dir)


def main(args: list[str] | None = None) -> None:
    """Entry point da CLI pluvia.

    Parameters
    ----------
    args : list of str or None
        Argumentos de linha de comando. Se ``None``, usa ``sys.argv``.
    """
    if args is None:
        _print_banner()

    parsed = parse_args(args)
    output_dir = Path(parsed.output)

    client = pluvia.ANA()

    if parsed.shapefile is not None:
        shapefile = parsed.shapefile
    else:
        shapefile = _resolve_shapefile_path()

    filter_value = parsed.shape_id if parsed.shape_id is not None else parsed.state
    stations = client.get_stations(
        contour=shapefile,
        column=parsed.shape_column,
        value=filter_value,
        station_type=parsed.station_type,
    )
    logger.info("Estações encontradas: %d", len(stations))

    data = client.fetch_data(
        stations=stations,
        start=parsed.start.isoformat(),
        end=parsed.end.isoformat(),
        variable="chuva",
        max_workers=5,
        rebuild=parsed.rebuild,
        update_active=parsed.update_active,
    )

    logger.info("Estações com dados: %d", len(data))
    for code, df in data.items():
        logger.info(
            "%s: %d registros [%s → %s]",
            code,
            len(df),
            df["datetime"].min(),
            df["datetime"].max(),
        )

    _save_data(data, output_dir)


if __name__ == "__main__":
    main()
