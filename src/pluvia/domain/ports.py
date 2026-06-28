"""Abstract interfaces for external data providers.

Defines contracts for discovering station inventories and fetching time series data.
Implementations provide SOAP, REST, or other protocols without coupling to specifics.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from enum import Enum
from enum import auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from pluvia.domain.entities import Station


class FetchResult(Enum):
    """Resultado de uma consulta individual a uma estação."""

    HAS_DATA = auto()
    EMPTY = auto()
    ERROR = auto()


class StationInventoryPort(ABC):
    """Contrato para provedores do inventário de estações."""

    @abstractmethod
    def fetch_inventory(
        self,
        station_type: str | None = None,
    ) -> list[Station]:
        """Busca o inventário completo de estações.

        Parameters
        ----------
        station_type : str or None, optional
            Filtra por tipo de estação (``"fluviometrica"``,
            ``"pluviometrica"`` ou ``"telemetric"``).

        Returns
        -------
        list[Station]
        """


class StationDataPort(ABC):
    """Contrato para provedores de séries temporais de estações."""

    @abstractmethod
    def fetch_series(
        self,
        station: Station,
        start: str,
        end: str,
        variable: str,
    ) -> tuple[FetchResult, pd.DataFrame | None]:
        """Busca a série temporal de uma estação num intervalo.

        Parameters
        ----------
        station : Station
            Estação a consultar.
        start : str
            Data de início no formato ``YYYY-MM-DD``.
        end : str
            Data de fim no formato ``YYYY-MM-DD``.
        variable : str
            Variável a buscar (``"chuva"``, ``"nivel"``, ``"vazao"``
            ou ``"cota"``).

        Returns
        -------
        tuple[FetchResult, pd.DataFrame or None]
            O resultado da consulta e, quando ``FetchResult.HAS_DATA``,
            um DataFrame com colunas ``"datetime"`` (ISO string) e
            ``"value"`` (float). Retorna ``None`` nos outros casos.
        """
