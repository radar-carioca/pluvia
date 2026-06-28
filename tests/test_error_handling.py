"""Testes para lógica de erro, cooldown e retries."""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path

from pluvia.application.ana_service import ERROR_COOLDOWN_SECONDS
from pluvia.application.ana_service import MAX_CONSECUTIVE_ERRORS
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
        return FetchResult.ERROR, None


def _make_station(code: str = "1") -> Station:
    return Station(
        code=code,
        name=f"Estação {code}",
        latitude=-23.0,
        longitude=-46.0,
        station_type="fluviometrica",
    )


class TestErrorCooldown:
    def test_is_in_error_cooldown_zero_errors(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        assert service._is_in_error_cooldown(meta) is False

    def test_is_in_error_cooldown_recent(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        meta.consecutive_errors = 1
        meta.last_checked = datetime.datetime.now().isoformat()
        assert service._is_in_error_cooldown(meta) is True

    def test_is_in_error_cooldown_expired(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        meta.consecutive_errors = 1
        meta.last_checked = (
            datetime.datetime.now()
            - datetime.timedelta(seconds=ERROR_COOLDOWN_SECONDS + 1)
        ).isoformat()
        assert service._is_in_error_cooldown(meta) is False

    def test_is_in_error_cooldown_none_last_checked(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        meta.consecutive_errors = 1
        meta.last_checked = None
        assert service._is_in_error_cooldown(meta) is False


class TestConsecutiveErrors:
    def test_erro_incrementa_consecutive_errors(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        updated = service._update_meta_after_fetch(
            meta,
            FetchResult.ERROR,
            None,
            "2024-01-01",
            "2024-01-31",
        )
        assert updated.consecutive_errors == 1

    def test_max_consecutive_errors_muda_status(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        meta.consecutive_errors = MAX_CONSECUTIVE_ERRORS - 1
        updated = service._update_meta_after_fetch(
            meta,
            FetchResult.ERROR,
            None,
            "2024-01-01",
            "2024-01-31",
        )
        assert updated.status == "error"
        assert updated.consecutive_errors == MAX_CONSECUTIVE_ERRORS

    def test_sucesso_reseta_consecutive_errors(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        meta.consecutive_errors = 3
        meta.status = "error"

        import pandas as pd

        df = pd.DataFrame({"datetime": ["2024-01-01T00:00:00"], "value": [1.0]})
        updated = service._update_meta_after_fetch(
            meta,
            FetchResult.HAS_DATA,
            df,
            "2024-01-01",
            "2024-01-01",
        )
        assert updated.consecutive_errors == 0
        assert updated.status == "active"

    def test_empty_nao_incrementa_erro(self):
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
        )
        meta = StationMeta.create("1", "chuva")
        meta.consecutive_errors = 2
        updated = service._update_meta_after_fetch(
            meta,
            FetchResult.EMPTY,
            None,
            "2024-01-01",
            "2024-01-31",
        )
        assert updated.consecutive_errors == 0
        assert updated.status == "inactive"


class TestFetchDataWithErrors:
    def test_estacao_em_cooldown_e_ignorada(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            service = AnaService(
                inventory_port=_NullProvider(),
                data_port=_NullProvider(),
                cache_dir=Path(tmp),
            )
            meta = StationMeta.create("1", "chuva")
            meta.consecutive_errors = 1
            meta.last_checked = datetime.datetime.now().isoformat()
            cache.save_meta(meta)

            data = service.fetch_data(
                stations=[_make_station("1")],
                start="2024-01-01",
                end="2024-01-31",
                variable="chuva",
            )
            assert data == {}

    def test_estacao_em_cooldown_expirado_e_consultada(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            service = AnaService(
                inventory_port=_NullProvider(),
                data_port=_NullProvider(),
                cache_dir=Path(tmp),
            )
            meta = StationMeta.create("1", "chuva")
            meta.consecutive_errors = 1
            meta.last_checked = (
                datetime.datetime.now()
                - datetime.timedelta(seconds=ERROR_COOLDOWN_SECONDS + 1)
            ).isoformat()
            cache.save_meta(meta)

            data = service.fetch_data(
                stations=[_make_station("1")],
                start="2024-01-01",
                end="2024-01-31",
                variable="chuva",
            )
            # Ainda retorna vazio porque o provider retorna ERROR, mas
            # a estação não é ignorada pelo cooldown
            assert data == {}
