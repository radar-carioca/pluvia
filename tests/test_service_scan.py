"""Testes para AnaService.scan_catalog."""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path
from unittest.mock import patch

from pluvia.application.ana_service import AnaService
from pluvia.domain.entities import Station
from pluvia.domain.ports import FetchResult
from pluvia.domain.ports import StationDataPort
from pluvia.domain.ports import StationInventoryPort
from pluvia.infrastructure.cache import StationCache
from pluvia.infrastructure.cache import StationMeta


class _NullProvider(StationInventoryPort, StationDataPort):
    def fetch_inventory(self, station_type=None):
        return []

    def fetch_series(self, station, start, end, variable):
        return FetchResult.EMPTY, None


def _make_station(code: str = "1") -> Station:
    return Station(
        code=code,
        name=f"Estação {code}",
        latitude=-23.0,
        longitude=-46.0,
        station_type="telemetric",
    )


def _make_meta_active(code: str = "1", variable: str = "chuva") -> StationMeta:
    recent = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    return StationMeta(
        code=code,
        variable=variable,
        status="active",
        known_data_start="2020-01-01",
        known_data_end=recent,
        checked_ranges=[("2020-01-01", recent, "has_data")],
        last_checked=datetime.datetime.now().isoformat(),
        consecutive_errors=0,
    )


def _make_meta_inactive(code: str = "1", variable: str = "chuva") -> StationMeta:
    return StationMeta(
        code=code,
        variable=variable,
        status="inactive",
        known_data_start=None,
        known_data_end=None,
        checked_ranges=[],
        last_checked=datetime.datetime.now().isoformat(),
        consecutive_errors=0,
    )


class TestScanCatalog:
    def _service(self, cache_dir: Path | None = None) -> AnaService:
        return AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
            cache_dir=cache_dir,
        )

    def test_sem_cache_sonda_todas(self):
        service = self._service()
        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda *a, **kw: None
            metas = service.scan_catalog(
                stations=[_make_station("1"), _make_station("2")],
                variable="chuva",
                probe_days=7,
            )
            assert mock_run.called
            assert len(metas) == 2
            assert "1" in metas
            assert "2" in metas

    def test_com_cache_inativa_dentro_ttl_nao_sonda(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            today = datetime.date.today()
            probe_end = today.isoformat()
            probe_start = (today - datetime.timedelta(days=7)).isoformat()
            meta = _make_meta_inactive("1")
            # Marca o range como já consultado (empty) e recente
            meta.checked_ranges = [(probe_start, probe_end, "empty")]
            meta.last_checked = datetime.datetime.now().isoformat()
            cache.save_meta(meta)
            service = self._service(cache_dir=Path(tmp))

            with patch.object(service, "_run_fetch_tasks") as mock_run:
                mock_run.side_effect = lambda *a, **kw: None
                metas = service.scan_catalog(
                    stations=[_make_station("1")],
                    variable="chuva",
                    probe_days=7,
                )
                assert not mock_run.called
                assert metas["1"].status == "inactive"

    def test_com_cache_ativa_sonda_para_novos_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            meta = _make_meta_active("1")
            # Set last_checked to old so TTL is expired for new probe range
            old = datetime.datetime.now() - datetime.timedelta(days=10)
            meta.last_checked = old.isoformat()
            cache.save_meta(meta)
            service = self._service(cache_dir=Path(tmp))

            with patch.object(service, "_run_fetch_tasks") as mock_run:
                mock_run.side_effect = lambda *a, **kw: None
                service.scan_catalog(
                    stations=[_make_station("1")],
                    variable="chuva",
                    probe_days=30,
                )
                assert mock_run.called

    def test_probe_days_respeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(cache_dir=Path(tmp))

            with patch.object(service, "_run_fetch_tasks") as mock_run:
                mock_run.side_effect = lambda *a, **kw: None
                service.scan_catalog(
                    stations=[_make_station("1")],
                    variable="chuva",
                    probe_days=7,
                )
                tasks = mock_run.call_args[0][0]
                for _st, start, end in tasks:
                    start_dt = datetime.date.fromisoformat(start)
                    end_dt = datetime.date.fromisoformat(end)
                    assert (end_dt - start_dt).days <= 7

    def test_retorna_metas_atualizadas(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(cache_dir=Path(tmp))

            with patch.object(service, "_run_fetch_tasks") as mock_run:
                mock_run.side_effect = lambda *a, **kw: None
                metas = service.scan_catalog(
                    stations=[_make_station("1")],
                    variable="chuva",
                )
                assert "1" in metas
                assert metas["1"].code == "1"
