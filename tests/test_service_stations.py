"""Testes para AnaService.get_stations."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from pluvia.application.ana_service import AnaService
from pluvia.domain.entities import Station
from pluvia.domain.ports import StationDataPort
from pluvia.domain.ports import StationInventoryPort
from pluvia.infrastructure.cache import StationCache


class _FakeProvider(StationInventoryPort, StationDataPort):
    def __init__(self, stations: list[Station] | None = None):
        self._stations = stations or []

    def fetch_inventory(self, station_type=None):
        return list(self._stations)

    def fetch_series(self, station, start, end, variable):
        from pluvia.domain.ports import FetchResult

        return FetchResult.EMPTY, None


def _make_station(
    code: str,
    station_type: str = "fluviometrica",
    lat: float = -23.0,
    lon: float = -46.0,
) -> Station:
    return Station(
        code=code,
        name=f"Estação {code}",
        latitude=lat,
        longitude=lon,
        station_type=station_type,
    )


class TestGetStations:
    def test_fetch_inventory_quando_sem_cache(self):
        provider = _FakeProvider([_make_station("1"), _make_station("2")])
        service = AnaService(inventory_port=provider, data_port=provider)
        stations = service.get_stations(force=True)
        assert len(stations) == 2

    def test_usa_cache_quando_disponivel(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station("1")])
            provider = _FakeProvider()
            service = AnaService(
                inventory_port=provider,
                data_port=provider,
                cache_dir=Path(tmp),
            )
            stations = service.get_stations()
            assert len(stations) == 1
            assert stations[0].code == "1"

    def test_force_ignora_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station("1")])
            provider = _FakeProvider([_make_station("2"), _make_station("3")])
            service = AnaService(
                inventory_port=provider,
                data_port=provider,
                cache_dir=Path(tmp),
            )
            stations = service.get_stations(force=True)
            assert len(stations) == 2

    def test_filtro_por_tipo(self):
        provider = _FakeProvider(
            [
                _make_station("1", "fluviometrica"),
                _make_station("2", "pluviometrica"),
                _make_station("3", "telemetric"),
            ]
        )
        service = AnaService(inventory_port=provider, data_port=provider)
        stations = service.get_stations(station_type="pluviometrica", force=True)
        assert len(stations) == 1
        assert stations[0].code == "2"

    def test_filtro_por_tipo_apos_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory(
                [
                    _make_station("1", "fluviometrica"),
                    _make_station("2", "pluviometrica"),
                ]
            )
            provider = _FakeProvider()
            service = AnaService(
                inventory_port=provider,
                data_port=provider,
                cache_dir=Path(tmp),
            )
            stations = service.get_stations(station_type="pluviometrica")
            assert len(stations) == 1
            assert stations[0].code == "2"

    def test_contour_filter(self):
        provider = _FakeProvider(
            [
                _make_station("1", lat=-23.0, lon=-46.0),
                _make_station("2", lat=-10.0, lon=-60.0),
            ]
        )
        service = AnaService(inventory_port=provider, data_port=provider)

        with patch("pluvia.infrastructure.spatial.SpatialExtent.from_file") as mock_ext:
            mock_extent = mock_ext.return_value
            mock_extent.filter.return_value = [provider._stations[0]]
            stations = service.get_stations(
                contour="fake.shp",
                column="acronym",
                value="SP",
                force=True,
            )
            assert len(stations) == 1
            assert stations[0].code == "1"

    def test_inventory_expired_rebusca(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station("1")])
            provider = _FakeProvider([_make_station("2")])
            service = AnaService(
                inventory_port=provider,
                data_port=provider,
                cache_dir=Path(tmp),
                inventory_ttl_days=0,  # Força expiração imediata
            )
            stations = service.get_stations()
            assert len(stations) == 1
            assert stations[0].code == "2"
