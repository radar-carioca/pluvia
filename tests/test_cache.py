"""Testes para StationCache — inventário, metadados e séries temporais."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from pluvia.domain.entities import Station
from pluvia.infrastructure.cache import StationCache
from pluvia.infrastructure.cache import StationMeta


def _make_station(code: str = "1", station_type: str = "fluviometrica") -> Station:
    return Station(
        code=code,
        name=f"Estação {code}",
        latitude=-23.0,
        longitude=-46.0,
        station_type=station_type,
    )


def _make_meta(
    code: str = "1",
    variable: str = "chuva",
    status: str = "unknown",
) -> StationMeta:
    return StationMeta.create(code, variable)


class TestInventario:
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            stations = [_make_station("1"), _make_station("2", "pluviometrica")]
            cache.save_inventory(stations)
            loaded = cache.load_inventory()
            assert loaded is not None
            assert len(loaded) == 2
            assert loaded[0].code == "1"
            assert loaded[1].station_type == "pluviometrica"

    def test_has_inventory_falso_sem_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            assert not cache.has_inventory()

    def test_has_inventory_verdadeiro_apos_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station()])
            assert cache.has_inventory()

    def test_inventory_age_days_none_sem_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            assert cache.inventory_age_days() is None

    def test_inventory_age_days_retorna_float(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station()])
            age = cache.inventory_age_days()
            assert age is not None
            assert age >= 0.0

    def test_save_atomico_cria_arquivo_temporario(self):
        """A gravação usa arquivo .tmp que é renomeado — não deixa lixo."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station()])
            tmp_files = list(Path(tmp).glob("*.tmp"))
            assert tmp_files == []


class TestMetadados:
    def test_load_meta_retorna_none_sem_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            assert cache.load_meta("chuva", "1") is None

    def test_save_e_load_meta_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            meta = StationMeta(
                code="1234",
                variable="chuva",
                status="active",
                known_data_start="2020-01-01",
                known_data_end="2024-12-31",
                checked_ranges=[("2020-01-01", "2024-12-31", "has_data")],
                last_checked="2026-06-01T10:00:00",
                consecutive_errors=0,
            )
            cache.save_meta(meta)
            loaded = cache.load_meta("chuva", "1234")
            assert loaded is not None
            assert loaded.code == "1234"
            assert loaded.status == "active"
            assert loaded.known_data_start == "2020-01-01"
            assert loaded.known_data_end == "2024-12-31"
            assert loaded.checked_ranges == [("2020-01-01", "2024-12-31", "has_data")]

    def test_save_meta_atomico_sem_arquivo_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_meta(_make_meta())
            tmp_files = list((Path(tmp) / "meta" / "chuva").glob("*.tmp"))
            assert tmp_files == []

    def test_has_meta_verdadeiro_apos_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            assert not cache.has_meta("chuva", "1")
            cache.save_meta(_make_meta("1", "chuva"))
            assert cache.has_meta("chuva", "1")

    def test_meta_escopado_por_variavel(self):
        """Metadados de variáveis diferentes são independentes."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            meta_chuva = _make_meta("1", "chuva")
            cache.save_meta(meta_chuva)
            assert cache.load_meta("nivel", "1") is None

    def test_load_meta_json_corrompido_retorna_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            path = cache._meta_path("chuva", "1")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{invalido json}")
            assert cache.load_meta("chuva", "1") is None

    def test_create_meta_estado_inicial(self):
        meta = StationMeta.create("abc", "nivel")
        assert meta.code == "abc"
        assert meta.variable == "nivel"
        assert meta.status == "unknown"
        assert meta.known_data_start is None
        assert meta.known_data_end is None
        assert meta.checked_ranges == []
        assert meta.consecutive_errors == 0

    def test_meta_to_dict_from_dict_roundtrip(self):
        meta = StationMeta(
            code="99",
            variable="vazao",
            status="inactive",
            known_data_start="2010-01-01",
            known_data_end="2015-12-31",
            checked_ranges=[
                ("2010-01-01", "2012-12-31", "has_data"),
                ("2013-01-01", "2015-12-31", "empty"),
            ],
            last_checked="2026-01-01T00:00:00",
            consecutive_errors=2,
        )
        restored = StationMeta.from_dict(meta.to_dict())
        assert restored.code == meta.code
        assert restored.status == meta.status
        assert restored.checked_ranges == meta.checked_ranges
        assert restored.consecutive_errors == meta.consecutive_errors


class TestDadosParquet:
    def _df(self, datetimes: list[str], value: float = 1.0) -> pd.DataFrame:
        return pd.DataFrame({"datetime": datetimes, "value": [value] * len(datetimes)})

    def test_save_e_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            df = self._df(["2024-01-01T00:00:00", "2024-01-02T00:00:00"])
            cache.save_station_data("chuva", "1", df)
            loaded = cache.load_station_data("chuva", "1")
            assert loaded is not None
            assert len(loaded) == 2
            assert "datetime" in loaded.columns
            assert "value" in loaded.columns

    def test_load_retorna_none_sem_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            assert cache.load_station_data("chuva", "999") is None

    def test_concat_appenda_novos_dados(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.concat_station_data("chuva", "1", self._df(["2024-01-01T00:00:00"]))
            cache.concat_station_data("chuva", "1", self._df(["2024-01-02T00:00:00"]))
            loaded = cache.load_station_data("chuva", "1")
            assert loaded is not None
            assert len(loaded) == 2

    def test_concat_sobrescreve_duplicatas(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.concat_station_data(
                "chuva", "1", self._df(["2024-01-01T00:00:00"], 1.0)
            )
            cache.concat_station_data(
                "chuva", "1", self._df(["2024-01-01T00:00:00"], 99.0)
            )
            loaded = cache.load_station_data("chuva", "1")
            assert loaded is not None
            assert len(loaded) == 1
            assert loaded.iloc[0]["value"] == pytest.approx(99.0)

    def test_concat_ordenado_por_datetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.concat_station_data("chuva", "1", self._df(["2024-03-01T00:00:00"]))
            cache.concat_station_data("chuva", "1", self._df(["2024-01-01T00:00:00"]))
            loaded = cache.load_station_data("chuva", "1")
            assert loaded is not None
            assert loaded["datetime"].tolist() == [
                "2024-01-01T00:00:00",
                "2024-03-01T00:00:00",
            ]


class TestLegadoStations:
    def test_roundtrip_stations(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_stations({"1": True, "2": False})
            loaded = cache.load_stations()
            assert loaded == {"1": True, "2": False}

    def test_update_station(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.update_station("1", True)
            cache.update_station("2", False)
            assert cache.load_stations() == {"1": True, "2": False}


class TestClear:
    def test_clear_remove_inventario_e_dados(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_inventory([_make_station()])
            cache.update_station("1", True)
            cache.clear()
            assert not cache.has_inventory()
            assert cache.load_stations() is None

    def test_clear_remove_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = StationCache(Path(tmp))
            cache.save_meta(_make_meta("1", "chuva"))
            cache.clear()
            assert not cache.has_meta("chuva", "1")
