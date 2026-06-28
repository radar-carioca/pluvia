"""Core domain types: Station entity, exceptions, and provider interfaces."""

from pluvia.domain.entities import Station
from pluvia.domain.exceptions import PluviaError
from pluvia.domain.ports import FetchResult
from pluvia.domain.ports import StationDataPort
from pluvia.domain.ports import StationInventoryPort

__all__ = [
    "Station",
    "PluviaError",
    "FetchResult",
    "StationInventoryPort",
    "StationDataPort",
]
