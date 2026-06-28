"""Testes para o módulo de álgebra de intervalos."""

import datetime

import pytest

from pluvia.infrastructure.cache.intervals import find_expired_empty_ranges
from pluvia.infrastructure.cache.intervals import find_fetch_targets
from pluvia.infrastructure.cache.intervals import find_unchecked_gaps
from pluvia.infrastructure.cache.intervals import merge_checked_ranges


class TestMergeCheckedRanges:
    def test_lista_vazia(self):
        assert merge_checked_ranges([]) == []

    def test_intervalo_unico(self):
        result = merge_checked_ranges([("2024-01-01", "2024-01-31", "has_data")])
        assert result == [("2024-01-01", "2024-01-31", "has_data")]

    def test_mescla_adjacentes_mesmo_tipo(self):
        ranges = [
            ("2024-01-01", "2024-01-31", "empty"),
            ("2024-02-01", "2024-02-28", "empty"),
        ]
        result = merge_checked_ranges(ranges)
        assert result == [("2024-01-01", "2024-02-28", "empty")]

    def test_mescla_sobrepostos_mesmo_tipo(self):
        ranges = [
            ("2024-01-01", "2024-03-31", "has_data"),
            ("2024-02-01", "2024-04-30", "has_data"),
        ]
        result = merge_checked_ranges(ranges)
        assert result == [("2024-01-01", "2024-04-30", "has_data")]

    def test_nao_mescla_tipos_diferentes(self):
        ranges = [
            ("2024-01-01", "2024-01-31", "has_data"),
            ("2024-02-01", "2024-02-28", "empty"),
        ]
        result = merge_checked_ranges(ranges)
        assert len(result) == 2
        kinds = {r[2] for r in result}
        assert kinds == {"has_data", "empty"}

    def test_mescla_varios_fragmentos(self):
        ranges = [
            ("2020-01-01", "2020-12-31", "empty"),
            ("2021-01-01", "2021-12-31", "empty"),
            ("2022-01-01", "2022-12-31", "empty"),
        ]
        result = merge_checked_ranges(ranges)
        assert result == [("2020-01-01", "2022-12-31", "empty")]

    def test_resultado_ordenado_por_data(self):
        ranges = [
            ("2024-06-01", "2024-06-30", "has_data"),
            ("2024-01-01", "2024-03-31", "empty"),
        ]
        result = merge_checked_ranges(ranges)
        starts = [r[0] for r in result]
        assert starts == sorted(starts)


class TestFindUncheckedGaps:
    def test_sem_historico_retorna_range_completo(self):
        gaps = find_unchecked_gaps([], "2024-01-01", "2024-12-31")
        assert gaps == [("2024-01-01", "2024-12-31")]

    def test_range_totalmente_coberto(self):
        ranges = [("2024-01-01", "2024-12-31", "has_data")]
        gaps = find_unchecked_gaps(ranges, "2024-03-01", "2024-06-30")
        assert gaps == []

    def test_gap_no_inicio(self):
        ranges = [("2024-06-01", "2024-12-31", "has_data")]
        gaps = find_unchecked_gaps(ranges, "2024-01-01", "2024-12-31")
        assert gaps == [("2024-01-01", "2024-05-31")]

    def test_gap_no_fim(self):
        ranges = [("2024-01-01", "2024-06-30", "has_data")]
        gaps = find_unchecked_gaps(ranges, "2024-01-01", "2024-12-31")
        assert gaps == [("2024-07-01", "2024-12-31")]

    def test_gap_no_meio(self):
        ranges = [
            ("2024-01-01", "2024-03-31", "has_data"),
            ("2024-07-01", "2024-12-31", "empty"),
        ]
        gaps = find_unchecked_gaps(ranges, "2024-01-01", "2024-12-31")
        assert gaps == [("2024-04-01", "2024-06-30")]

    def test_multiplos_gaps(self):
        ranges = [
            ("2024-03-01", "2024-03-31", "has_data"),
            ("2024-06-01", "2024-06-30", "has_data"),
        ]
        gaps = find_unchecked_gaps(ranges, "2024-01-01", "2024-08-31")
        assert gaps == [
            ("2024-01-01", "2024-02-29"),  # 2024 é ano bissexto
            ("2024-04-01", "2024-05-31"),
            ("2024-07-01", "2024-08-31"),
        ]

    def test_cobertura_ignora_tipo(self):
        """Qualquer tipo de cobertura (has_data ou empty) elimina o gap."""
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        gaps = find_unchecked_gaps(ranges, "2024-03-01", "2024-09-30")
        assert gaps == []

    def test_range_de_um_dia(self):
        ranges = [("2024-01-01", "2024-01-01", "has_data")]
        gaps = find_unchecked_gaps(ranges, "2024-01-01", "2024-01-01")
        assert gaps == []


class TestFindExpiredEmptyRanges:
    def _last_checked(self, days_ago: int) -> str:
        dt = datetime.datetime.now() - datetime.timedelta(days=days_ago)
        return dt.isoformat()

    def test_sem_last_checked_retorna_vazio(self):
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        result = find_expired_empty_ranges(ranges, "2024-01-01", "2024-12-31", None, 1)
        assert result == []

    def test_dentro_do_ttl_retorna_vazio(self):
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        last = self._last_checked(0)
        result = find_expired_empty_ranges(ranges, "2024-01-01", "2024-12-31", last, 7)
        assert result == []

    def test_ttl_expirado_retorna_empty_ranges(self):
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        last = self._last_checked(10)
        result = find_expired_empty_ranges(ranges, "2024-01-01", "2024-12-31", last, 7)
        assert result == [("2024-01-01", "2024-12-31")]

    def test_ignora_has_data_expirado(self):
        """Intervalos 'has_data' não são marcados para re-fetch por TTL."""
        ranges = [("2024-01-01", "2024-12-31", "has_data")]
        last = self._last_checked(30)
        result = find_expired_empty_ranges(ranges, "2024-01-01", "2024-12-31", last, 1)
        assert result == []

    def test_intersecta_com_range_pedido(self):
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        last = self._last_checked(10)
        result = find_expired_empty_ranges(ranges, "2024-06-01", "2024-08-31", last, 7)
        assert result == [("2024-06-01", "2024-08-31")]


class TestFindFetchTargets:
    def _old_timestamp(self) -> str:
        dt = datetime.datetime.now() - datetime.timedelta(days=30)
        return dt.isoformat()

    def _fresh_timestamp(self) -> str:
        return datetime.datetime.now().isoformat()

    def test_sem_historico_retorna_range_completo(self):
        targets = find_fetch_targets([], "2024-01-01", "2024-12-31", None, 7)
        assert targets == [("2024-01-01", "2024-12-31")]

    def test_totalmente_coberto_dentro_ttl_retorna_vazio(self):
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        last = self._fresh_timestamp()
        targets = find_fetch_targets(ranges, "2024-01-01", "2024-12-31", last, 7)
        assert targets == []

    def test_totalmente_coberto_has_data_retorna_vazio(self):
        ranges = [("2024-01-01", "2024-12-31", "has_data")]
        last = self._fresh_timestamp()
        targets = find_fetch_targets(ranges, "2024-01-01", "2024-12-31", last, 7)
        assert targets == []

    def test_gap_mais_empty_expirado_sao_mesclados(self):
        """Gap não consultado + empty expirado adjacente devem formar um único target."""
        ranges = [("2024-01-01", "2024-06-30", "empty")]
        last = self._old_timestamp()
        targets = find_fetch_targets(ranges, "2024-01-01", "2024-12-31", last, 7)
        assert targets == [("2024-01-01", "2024-12-31")]

    def test_has_data_nao_e_re_fetch(self):
        """Intervalos 'has_data' nunca são adicionados aos targets."""
        ranges = [
            ("2024-01-01", "2024-06-30", "has_data"),
            ("2024-07-01", "2024-12-31", "empty"),
        ]
        last = self._old_timestamp()
        targets = find_fetch_targets(ranges, "2024-01-01", "2024-12-31", last, 7)
        assert targets == [("2024-07-01", "2024-12-31")]

    @pytest.mark.parametrize("ttl_days", [0, -1])
    def test_ttl_zero_ou_negativo_nao_expira(self, ttl_days: int):
        ranges = [("2024-01-01", "2024-12-31", "empty")]
        last = self._old_timestamp()
        targets = find_fetch_targets(ranges, "2024-01-01", "2024-12-31", last, ttl_days)
        assert targets == []
