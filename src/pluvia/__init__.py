"""pluvia - Catalogação de estações hidrometeorológicas da ANA."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pluvia.application.ana_service import DEFAULT_TTL_SCHEDULE
from pluvia.application.ana_service import AnaService
from pluvia.domain.entities import Station
from pluvia.domain.exceptions import PluviaError
from pluvia.infrastructure.ana.client import AnaClient
from pluvia.infrastructure.cache import StationMeta
from pluvia.infrastructure.logging import setup_logging

__version__ = "0.1.1"


class ANA:
    """Cliente para o serviço de dados hidrometeorológicos da ANA.

    Parameters
    ----------
    cache_dir : Path or None, optional
        Diretório para cache em disco. Se ``None``, o cache é desabilitado.
    inactive_ttl_schedule : list of tuple, optional
        Escalonamento de TTL para cache negativo. Cada entrada é
        ``(dias_desde_ultimo_dado, ttl_dias)``. Controla com que frequência
        estações inativas são re-consultadas com base em quando tiveram dados
        pela última vez. Padrão::

            [(30, 1), (365, 3), (99999, 7)]

        Interpretação: estações com dado recente (< 30 dias) são re-checadas
        diariamente; com dado entre 30–365 dias, a cada 3 dias; mais antigas,
        semanalmente.
    unknown_ttl_days : int, optional
        TTL para estações que nunca tiveram dados confirmados. Padrão: 30 dias.
    inventory_ttl_days : int, optional
        Validade do inventário em cache em dias. Após este período, o inventário
        é re-buscado automaticamente. Padrão: 7 dias.
    timeout : int, optional
        Timeout das requisições SOAP em segundos. Padrão: 120.
    """

    def __init__(
        self,
        cache_dir: Path = Path(".cache/ana"),
        inactive_ttl_schedule: list[tuple[int, int]] | None = None,
        unknown_ttl_days: int = 30,
        inventory_ttl_days: int = 7,
        timeout: int = 120,
    ) -> None:
        provider = AnaClient(timeout=timeout)
        self._service = AnaService(
            inventory_port=provider,
            data_port=provider,
            cache_dir=cache_dir,
            inactive_ttl_schedule=inactive_ttl_schedule or DEFAULT_TTL_SCHEDULE,
            unknown_ttl_days=unknown_ttl_days,
            inventory_ttl_days=inventory_ttl_days,
        )

    def get_stations(
        self,
        contour: str | None = None,
        column: str | None = None,
        value: str | None = None,
        station_type: str | None = None,
        force: bool = False,
    ) -> list[Station]:
        """Busca e filtra o inventário de estações da ANA.

        Parameters
        ----------
        contour : str or None, optional
            Caminho para arquivo vetorial (.shp, .gpkg, .geojson).
        column : str or None, optional
            Coluna de atributo para filtrar o arquivo vetorial.
        value : str or None, optional
            Valor desejado para a coluna de filtro.
        station_type : str or None, optional
            ``"fluviometrica"``, ``"pluviometrica"`` ou ``"telemetric"``.
        force : bool, optional
            Ignora o cache e re-busca da ANA.

        Returns
        -------
        list[Station]
        """
        return self._service.get_stations(
            contour=contour,
            column=column,
            value=value,
            station_type=station_type,
            force=force,
        )

    def fetch_data(
        self,
        stations: list[Station],
        start: str,
        end: str,
        variable: str,
        max_workers: int = 5,
        rebuild: bool = False,
        update_active: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """Baixa séries temporais para as estações fornecidas.

        Parameters
        ----------
        stations : list[Station]
        start : str
            Data de início no formato ``YYYY-MM-DD``.
        end : str
            Data de fim no formato ``YYYY-MM-DD``.
        variable : str
            ``"chuva"``, ``"nivel"``, ``"vazao"`` ou ``"cota"``.
        max_workers : int, optional
        rebuild : bool, optional
            Se ``True``, ignora todo o cache e re-consulta todas as estações.
        update_active : bool, optional
            Se ``True``, re-consulta estações com ``status="active"`` mesmo
            que o intervalo já esteja coberto.

        Returns
        -------
        dict[str, pd.DataFrame]
        """
        return self._service.fetch_data(
            stations=stations,
            start=start,
            end=end,
            variable=variable,
            max_workers=max_workers,
            rebuild=rebuild,
            update_active=update_active,
        )

    def scan_catalog(
        self,
        stations: list[Station],
        variable: str,
        max_workers: int = 20,
        probe_days: int = 30,
    ) -> dict[str, StationMeta]:
        """Sonda o catálogo completo para identificar estações com dados recentes.

        Parameters
        ----------
        stations : list[Station]
        variable : str
        max_workers : int, optional
        probe_days : int, optional
            Número de dias recentes a sondar. Padrão: 30.

        Returns
        -------
        dict[str, StationMeta]
        """
        return self._service.scan_catalog(
            stations=stations,
            variable=variable,
            max_workers=max_workers,
            probe_days=probe_days,
        )


__all__ = [
    "ANA",
    "Station",
    "StationMeta",
    "PluviaError",
    "setup_logging",
]
