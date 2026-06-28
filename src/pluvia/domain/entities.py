"""Domain entities for pluvia."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Station:
    """Estação hidrometeorológica.

    Attributes
    ----------
    code : str
        Código identificador da estação.
    name : str
        Nome da estação.
    latitude : float
        Latitude em graus decimais.
    longitude : float
        Longitude em graus decimais.
    station_type : str
        ``"fluviometrica"``, ``"pluviometrica"`` ou ``"telemetric"``.
    state : str or None
        Estado brasileiro.
    municipality : str or None
        Nome do município.
    basin : str or None
        Código da bacia.
    subbasin : str or None
        Código da sub-bacia.
    river : str or None
        Nome do rio.
    responsible : str or None
        Órgão responsável.
    """

    code: str
    name: str
    latitude: float
    longitude: float
    station_type: str
    state: str | None = None
    municipality: str | None = None
    basin: str | None = None
    subbasin: str | None = None
    river: str | None = None
    responsible: str | None = None

    def __hash__(self) -> int:
        """Hash baseado no código da estação."""
        return hash(self.code)
