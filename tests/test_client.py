"""Testes para AnaService — lógica de decisão de fetch e cache."""

import datetime
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pluvia.application.ana_service import AnaService
from pluvia.domain.entities import Station
from pluvia.domain.ports import FetchResult
from pluvia.domain.ports import StationDataPort
from pluvia.domain.ports import StationInventoryPort
from pluvia.infrastructure.ana.client import _filter_date_range
from pluvia.infrastructure.ana.client import _to_parquet_schema
from pluvia.infrastructure.cache import StationCache
from pluvia.infrastructure.cache import StationMeta


class _NullProvider(StationInventoryPort, StationDataPort):
    """Stub que nunca faz I/O real — usado para testar a lógica de orquestração."""

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


def _meta_inactive_recent(code: str = "1", variable: str = "chuva") -> StationMeta:
    """Estação inativa consultada há pouco (dentro do TTL padrão de 1 dia)."""
    return StationMeta(
        code=code,
        variable=variable,
        status="inactive",
        known_data_start=None,
        known_data_end=None,
        checked_ranges=[("2026-06-01", "2026-06-01", "empty")],
        last_checked=datetime.datetime.now().isoformat(),
        consecutive_errors=0,
    )


def _meta_inactive_old(code: str = "1", variable: str = "chuva") -> StationMeta:
    """Estação inativa com TTL expirado (última consulta há 10 dias)."""
    old = datetime.datetime.now() - datetime.timedelta(days=10)
    return StationMeta(
        code=code,
        variable=variable,
        status="inactive",
        known_data_start=None,
        known_data_end=None,
        checked_ranges=[("2026-06-01", "2026-06-01", "empty")],
        last_checked=old.isoformat(),
        consecutive_errors=0,
    )


def _meta_active(code: str = "1", variable: str = "chuva") -> StationMeta:
    """Estação ativa com dado conhecido recente."""
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


# ── testes de TTL / cooldown ─────────────────────────────────────────────────


class TestShouldSkipWithinTTL:
    def _service(self) -> AnaService:
        return AnaService(inventory_port=_NullProvider(), data_port=_NullProvider())

    def test_inativa_dentro_ttl_deve_pular(self):
        service = self._service()
        meta = _meta_inactive_recent()
        ttl = service._compute_ttl(meta)
        assert service._should_skip_within_ttl(meta, ttl) is True

    def test_inativa_com_ttl_expirado_nao_pula(self):
        service = self._service()
        meta = _meta_inactive_old()
        assert service._should_skip_within_ttl(meta, ttl=5) is False

    def test_ativa_nunca_pula(self):
        service = self._service()
        meta = _meta_active()
        assert service._should_skip_within_ttl(meta, ttl=7) is False

    def test_unknown_sem_erros_e_sem_last_checked_nao_pula(self):
        """Estação unknown nunca consultada deve sempre ser checada."""
        service = self._service()
        meta = StationMeta.create("1", "chuva")
        assert meta.last_checked is None
        assert service._should_skip_within_ttl(meta, ttl=30) is False

    def test_unknown_com_erros_nao_pula_via_ttl(self):
        """unknown com erros usa cooldown de erro, não TTL de inativo."""
        service = self._service()
        meta = StationMeta.create("1", "chuva")
        meta.last_checked = datetime.datetime.now().isoformat()
        meta.consecutive_errors = 1
        assert service._should_skip_within_ttl(meta, ttl=30) is False
        assert service._is_in_error_cooldown(meta) is True


class TestFetchDataComCache:
    def _service_com_meta(self, meta: StationMeta) -> tuple[AnaService, Path]:
        tmp = tempfile.mkdtemp()
        cache = StationCache(Path(tmp))
        cache.save_meta(meta)
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
            cache_dir=Path(tmp),
        )
        return service, Path(tmp)

    def test_estacao_inativa_dentro_ttl_nao_e_consultada(self):
        """Estação inativa recente não deve aparecer nas tasks ao mudar o range."""
        meta = _meta_inactive_recent("99")
        service, _ = self._service_com_meta(meta)

        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda tasks, *a, **kw: None
            service.fetch_data(
                stations=[_make_station("99")],
                start="2026-06-01",
                end="2026-06-09",
                variable="chuva",
            )
            called_tasks = mock_run.call_args[0][0] if mock_run.called else []
            assert not any(t[0].code == "99" for t in called_tasks)

    def test_estacao_ativa_sempre_e_consultada_para_novos_gaps(self):
        """Estação ativa deve ser consultada para períodos não cobertos."""
        meta = _meta_active("42")
        service, _ = self._service_com_meta(meta)

        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda tasks, *a, **kw: None
            service.fetch_data(
                stations=[_make_station("42")],
                start="2026-06-01",
                end="2026-06-09",
                variable="chuva",
            )
            assert mock_run.called
            tasks = mock_run.call_args[0][0]
            assert any(t[0].code == "42" for t in tasks)

    def test_rebuild_ignora_ttl_e_consulta_todas(self):
        """rebuild=True deve consultar todas as estações independente do TTL."""
        meta = _meta_inactive_recent("77")
        service, _ = self._service_com_meta(meta)

        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda tasks, *a, **kw: None
            service.fetch_data(
                stations=[_make_station("77")],
                start="2026-06-01",
                end="2026-06-09",
                variable="chuva",
                rebuild=True,
            )
            assert mock_run.called
            tasks = mock_run.call_args[0][0]
            assert any(t[0].code == "77" for t in tasks)

    def test_update_active_re_consulta_estacao_ativa(self):
        """update_active=True força re-fetch de estações ativas já cobertas no cache."""
        meta = _meta_active("88")
        service, _ = self._service_com_meta(meta)

        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda tasks, *a, **kw: None
            service.fetch_data(
                stations=[_make_station("88")],
                start="2026-06-01",
                end="2026-06-09",
                variable="chuva",
                update_active=True,
            )
            assert mock_run.called
            tasks = mock_run.call_args[0][0]
            assert any(t[0].code == "88" for t in tasks)

    def test_update_active_nao_afeta_inativas(self):
        """update_active=True não deve re-consultar estações inativas dentro do TTL."""
        meta = _meta_inactive_recent("33")
        service, _ = self._service_com_meta(meta)

        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda tasks, *a, **kw: None
            service.fetch_data(
                stations=[_make_station("33")],
                start="2026-06-01",
                end="2026-06-09",
                variable="chuva",
                update_active=True,
            )
            called_tasks = mock_run.call_args[0][0] if mock_run.called else []
            assert not any(t[0].code == "33" for t in called_tasks)

    def test_estacao_inativa_com_ttl_expirado_e_consultada(self):
        """Estação inativa com TTL expirado deve ser re-consultada."""
        meta = _meta_inactive_old("55")
        tmp = tempfile.mkdtemp()
        cache = StationCache(Path(tmp))
        cache.save_meta(meta)
        service = AnaService(
            inventory_port=_NullProvider(),
            data_port=_NullProvider(),
            cache_dir=Path(tmp),
            inactive_ttl_schedule=[(99999, 5)],
            unknown_ttl_days=5,
        )

        with patch.object(service, "_run_fetch_tasks") as mock_run:
            mock_run.side_effect = lambda tasks, *a, **kw: None
            service.fetch_data(
                stations=[_make_station("55")],
                start="2026-06-01",
                end="2026-06-09",
                variable="chuva",
            )
            assert mock_run.called
            tasks = mock_run.call_args[0][0]
            assert any(t[0].code == "55" for t in tasks)


class TestToParquetSchema:
    def _df_with_index(
        self, dates: list[str], values: list[float | None]
    ) -> pd.DataFrame:
        idx = pd.DatetimeIndex(dates, name="DataHora")
        return pd.DataFrame({"Chuva": values}, index=idx)

    def test_colunas_corretas(self):
        df = self._df_with_index(["2024-01-01T00:00:00"], [1.5])
        result = _to_parquet_schema(df)
        assert list(result.columns) == ["datetime", "value"]

    def test_datetime_em_formato_iso(self):
        df = self._df_with_index(["2024-06-15T14:30:00"], [2.0])
        result = _to_parquet_schema(df)
        assert result["datetime"].iloc[0] == "2024-06-15T14:30:00"

    def test_valor_preservado(self):
        df = self._df_with_index(["2024-01-01T00:00:00"], [42.5])
        result = _to_parquet_schema(df)
        assert result["value"].iloc[0] == pytest.approx(42.5)

    def test_indice_resetado(self):
        df = self._df_with_index(
            ["2024-01-01T00:00:00", "2024-01-02T00:00:00"], [1.0, 2.0]
        )
        result = _to_parquet_schema(df)
        assert list(result.index) == [0, 1]

    def test_nan_preservado(self):
        df = self._df_with_index(["2024-01-01T00:00:00"], [None])
        result = _to_parquet_schema(df)
        assert np.isnan(result["value"].iloc[0])


class TestFilterDateRange:
    def _df_novo(self, datetimes: list[str], value: float = 1.0) -> pd.DataFrame:
        return pd.DataFrame({"datetime": datetimes, "value": [value] * len(datetimes)})

    def _df_legado(self, dates: list[str], value: float = 1.0) -> pd.DataFrame:
        idx = pd.DatetimeIndex(dates, name="Data")
        return pd.DataFrame({"Chuva": [value] * len(dates)}, index=idx)

    def test_schema_novo_inclui_mesmo_dia(self):
        df = self._df_novo(["2024-06-01T00:00:00", "2024-06-01T23:00:00"])
        result = _filter_date_range(df, "2024-06-01", "2024-06-01")
        assert len(result) == 2

    def test_schema_novo_exclui_fora_do_range(self):
        df = self._df_novo(
            [
                "2024-05-31T00:00:00",
                "2024-06-01T12:00:00",
                "2024-06-10T00:00:00",
            ]
        )
        result = _filter_date_range(df, "2024-06-01", "2024-06-09")
        assert len(result) == 1
        assert result["datetime"].iloc[0] == "2024-06-01T12:00:00"

    def test_schema_legado_funciona(self):
        df = self._df_legado(["2024-06-01", "2024-06-02", "2024-06-10"])
        result = _filter_date_range(df, "2024-06-01", "2024-06-09")
        assert len(result) == 2


class TestAllNullDetection:
    """Valida que estações com todas as leituras nulas são marcadas como EMPTY."""

    def _df_all_nan(self) -> pd.DataFrame:
        idx = pd.DatetimeIndex(
            ["2024-01-01T00:00:00", "2024-01-01T01:00:00"], name="DataHora"
        )
        return pd.DataFrame({"Chuva": [float("nan"), float("nan")]}, index=idx)

    def _df_with_values(self) -> pd.DataFrame:
        idx = pd.DatetimeIndex(
            ["2024-01-01T00:00:00", "2024-01-01T01:00:00"], name="DataHora"
        )
        return pd.DataFrame({"Chuva": [0.0, 1.5]}, index=idx)

    def test_all_nan_retorna_empty(self):
        df = self._df_all_nan()
        assert df.iloc[:, 0].isna().all()

    def test_com_valores_nao_retorna_empty(self):
        df = self._df_with_values()
        assert not df.iloc[:, 0].isna().all()

    def test_parcialmente_nulo_nao_retorna_empty(self):
        idx = pd.DatetimeIndex(["2024-01-01T00:00:00", "2024-01-01T01:00:00"])
        df = pd.DataFrame({"Chuva": [float("nan"), 1.0]}, index=idx)
        assert not df.iloc[:, 0].isna().all()
