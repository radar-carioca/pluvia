"""Testes para a API pública pluvia.ANA."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pandas as pd

from pluvia import ANA
from pluvia.domain.entities import Station


class TestANACreation:
    def test_default_init(self):
        client = ANA()
        assert client is not None

    def test_init_with_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ANA(cache_dir=Path(tmp))
            assert client is not None

    def test_init_custom_ttl(self):
        client = ANA(
            inactive_ttl_schedule=[(10, 1), (30, 3)],
            unknown_ttl_days=15,
        )
        assert client is not None


class TestANAGetStations:
    @patch("pluvia.infrastructure.ana.client.AnaClient.fetch_inventory")
    def test_get_stations_mock(self, mock_fetch):
        mock_fetch.return_value = [
            Station(
                code="123",
                name="Test",
                latitude=-23.0,
                longitude=-46.0,
                station_type="fluviometrica",
            )
        ]
        client = ANA()
        stations = client.get_stations(force=True)
        assert len(stations) == 1
        assert stations[0].code == "123"

    @patch("pluvia.infrastructure.ana.client.AnaClient.fetch_inventory")
    def test_get_stations_with_type_filter(self, mock_fetch):
        mock_fetch.return_value = [
            Station(
                code="1",
                name="Flu",
                latitude=-23.0,
                longitude=-46.0,
                station_type="fluviometrica",
            ),
            Station(
                code="2",
                name="Plu",
                latitude=-23.0,
                longitude=-46.0,
                station_type="pluviometrica",
            ),
        ]
        client = ANA()
        stations = client.get_stations(station_type="pluviometrica", force=True)
        assert len(stations) == 1
        assert stations[0].code == "2"


class TestANAFetchData:
    @patch("pluvia.infrastructure.ana.client.AnaClient.fetch_series")
    def test_fetch_data_with_mock(self, mock_fetch):
        mock_fetch.return_value = (
            MagicMock(),  # FetchResult
            pd.DataFrame({"datetime": ["2024-01-01T00:00:00"], "value": [10.0]}),
        )
        client = ANA()
        station = Station(
            code="999",
            name="Test",
            latitude=-23.0,
            longitude=-46.0,
            station_type="fluviometrica",
        )
        data = client.fetch_data(
            stations=[station],
            start="2024-01-01",
            end="2024-01-31",
            variable="chuva",
            rebuild=True,
        )
        assert isinstance(data, dict)

    @patch("pluvia.infrastructure.ana.client.AnaClient.fetch_series")
    def test_fetch_data_empty(self, mock_fetch):
        mock_fetch.return_value = (MagicMock(), None)
        client = ANA()
        station = Station(
            code="999",
            name="Test",
            latitude=-23.0,
            longitude=-46.0,
            station_type="fluviometrica",
        )
        data = client.fetch_data(
            stations=[station],
            start="2024-01-01",
            end="2024-01-31",
            variable="chuva",
            rebuild=True,
        )
        assert data == {}


class TestANAScanCatalog:
    @patch("pluvia.infrastructure.ana.client.AnaClient.fetch_series")
    def test_scan_catalog(self, mock_fetch):
        mock_fetch.return_value = (
            MagicMock(),
            pd.DataFrame({"datetime": ["2024-01-01T00:00:00"], "value": [5.0]}),
        )
        client = ANA()
        station = Station(
            code="111",
            name="Test",
            latitude=-23.0,
            longitude=-46.0,
            station_type="telemetric",
        )
        metas = client.scan_catalog(
            stations=[station],
            variable="chuva",
            probe_days=7,
        )
        assert isinstance(metas, dict)
        assert "111" in metas

    @patch("pluvia.infrastructure.ana.client.AnaClient.fetch_series")
    def test_scan_catalog_no_cache(self, mock_fetch):
        mock_fetch.return_value = (MagicMock(), None)
        client = ANA(cache_dir=None)
        station = Station(
            code="222",
            name="Test",
            latitude=-23.0,
            longitude=-46.0,
            station_type="fluviometrica",
        )
        metas = client.scan_catalog(
            stations=[station],
            variable="chuva",
            probe_days=7,
        )
        assert isinstance(metas, dict)
        assert "222" in metas
