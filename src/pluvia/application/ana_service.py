"""Service layer for ANA hydrometeorological data operations.

Coordinates inventory discovery, caching, and time series fetching with
intelligent TTL scheduling, error cooldowns, and incremental persistence.
"""

from __future__ import annotations

import datetime
import logging
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from pathlib import Path

import pandas as pd
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import TaskProgressColumn
from rich.progress import TextColumn
from rich.progress import TimeRemainingColumn

from pluvia.domain.entities import Station
from pluvia.domain.ports import FetchResult
from pluvia.domain.ports import StationDataPort
from pluvia.domain.ports import StationInventoryPort
from pluvia.infrastructure.ana.client import _filter_date_range
from pluvia.infrastructure.cache import StationCache
from pluvia.infrastructure.cache import StationMeta
from pluvia.infrastructure.cache.intervals import find_fetch_targets
from pluvia.infrastructure.cache.intervals import merge_checked_ranges
from pluvia.infrastructure.logging import console as _console
from pluvia.infrastructure.spatial import SpatialExtent

logger = logging.getLogger("pluvia.service")

# TTL padrão: (dias desde último dado, dias de validade do cache negativo)
DEFAULT_TTL_SCHEDULE: list[tuple[int, int]] = [
    (30, 1),  # dado recente (< 30 dias): re-checar a cada 1 dia
    (365, 3),  # dado entre 30-365 dias: re-checar a cada 3 dias
    (99999, 7),  # dado antigo (> 1 ano): re-checar a cada 7 dias
]

# Número de erros consecutivos antes de colocar a estação em cooldown
MAX_CONSECUTIVE_ERRORS = 3

# Cooldown de estações em erro (segundos)
ERROR_COOLDOWN_SECONDS = 86400  # 1 dia


class AnaService:
    """Serviço de aplicação para catalogação e download de dados da ANA.

    Coordena o inventário de estações, o cache em disco e o fetch de séries
    temporais, delegando todo o I/O externo aos ports injetados.

    Parameters
    ----------
    inventory_port : StationInventoryPort
        Provedor do inventário de estações.
    data_port : StationDataPort
        Provedor de séries temporais.
    cache_dir : Path or None, optional
        Diretório para cache em disco. Se ``None``, o cache é desabilitado.
    inactive_ttl_schedule : list of tuple, optional
        Escalonamento de TTL para cache negativo. Cada entrada é
        ``(dias_desde_ultimo_dado, ttl_dias)``. Padrão: ``DEFAULT_TTL_SCHEDULE``.
    unknown_ttl_days : int, optional
        TTL para estações que nunca tiveram dados confirmados. Padrão: 30 dias.
    inventory_ttl_days : int, optional
        Validade do inventário em cache em dias. Padrão: 7 dias.
    """

    def __init__(
        self,
        inventory_port: StationInventoryPort,
        data_port: StationDataPort,
        cache_dir: Path | None = None,
        inactive_ttl_schedule: list[tuple[int, int]] | None = None,
        unknown_ttl_days: int = 30,
        inventory_ttl_days: int = 7,
    ) -> None:
        self._inventory_port = inventory_port
        self._data_port = data_port
        self._cache = StationCache(cache_dir) if cache_dir else None
        self._ttl_schedule = inactive_ttl_schedule or DEFAULT_TTL_SCHEDULE
        self._unknown_ttl_days = unknown_ttl_days
        self._inventory_ttl_days = inventory_ttl_days

    def get_stations(
        self,
        contour: str | None = None,
        column: str | None = None,
        value: str | None = None,
        station_type: str | None = None,
        force: bool = False,
    ) -> list[Station]:
        """Busca e filtra o inventário de estações da ANA.

        O inventário é re-buscado quando o cache está ausente, quando
        *force=True*, ou quando o inventário em cache é mais antigo que
        *inventory_ttl_days* dias.

        Parameters
        ----------
        contour : str or None, optional
            Caminho para arquivo vetorial (.shp, .gpkg, .geojson).
        column : str or None, optional
            Coluna de atributo para filtrar o arquivo vetorial.
        value : str or None, optional
            Valor desejado para a coluna de filtro.
        station_type : str or None, optional
            ``"fluviometrica"``, ``"pluviometrica"`` ou ``"telemetric"``.
        force : bool, optional
            Se ``True``, ignora o cache e re-busca da ANA.

        Returns
        -------
        list[Station]
        """
        inventory_expired = (
            self._cache is not None
            and self._cache.inventory_age_days() is not None
            and (self._cache.inventory_age_days() or 0) > self._inventory_ttl_days
        )

        if (
            not force
            and not inventory_expired
            and self._cache
            and self._cache.has_inventory()
        ):
            stations = self._cache.load_inventory() or []
        else:
            stations = self._inventory_port.fetch_inventory(station_type)
            if self._cache:
                self._cache.save_inventory(stations)

        # Aplica filtro por tipo após carregar do cache (corrige bug legado)
        if station_type is not None:
            stations = [s for s in stations if s.station_type == station_type]

        if contour is not None:
            extent = SpatialExtent.from_file(contour, column=column, value=value)
            stations = extent.filter(stations)

        return stations

    def _compute_ttl(self, meta: StationMeta) -> int:
        """Calcula o TTL de re-checagem com base na recência do último dado."""
        if meta.known_data_end is None:
            return self._unknown_ttl_days
        last_data = datetime.date.fromisoformat(meta.known_data_end)
        days_ago = (datetime.date.today() - last_data).days
        for threshold, ttl in sorted(self._ttl_schedule):
            if days_ago <= threshold:
                return ttl
        return (
            self._ttl_schedule[-1][1] if self._ttl_schedule else self._unknown_ttl_days
        )

    def _is_in_error_cooldown(self, meta: StationMeta) -> bool:
        """Verifica se a estação está em cooldown por erros de rede.

        Aplica-se a qualquer estação com pelo menos um erro consecutivo não
        resolvido, independentemente do status.
        """
        if meta.consecutive_errors == 0 or meta.last_checked is None:
            return False
        last = datetime.datetime.fromisoformat(meta.last_checked)
        return (datetime.datetime.now() - last).total_seconds() < ERROR_COOLDOWN_SECONDS

    def _should_skip_within_ttl(self, meta: StationMeta, ttl: int) -> bool:
        """Verifica se uma estação inativa deve ser ignorada pelo TTL.

        Aplica-se exclusivamente a estações com ``status="inactive"``. O TTL
        garante que não re-consultemos estações que sabidamente não têm dados
        até que o período de validade expire.

        Parameters
        ----------
        meta : StationMeta
        ttl : int
            Validade do cache negativo em dias.

        Returns
        -------
        bool
        """
        if meta.status != "inactive":
            return False
        if meta.last_checked is None:
            return False
        last = datetime.datetime.fromisoformat(meta.last_checked)
        age_days = (datetime.datetime.now() - last).total_seconds() / 86400
        return age_days < ttl

    def _update_meta_after_fetch(
        self,
        meta: StationMeta,
        result: FetchResult,
        df_new: pd.DataFrame | None,
        fetch_start: str,
        fetch_end: str,
    ) -> StationMeta:
        """Atualiza o metadado com base no resultado de uma consulta.

        Parameters
        ----------
        meta : StationMeta
        result : FetchResult
        df_new : pd.DataFrame or None
        fetch_start : str
        fetch_end : str

        Returns
        -------
        StationMeta
        """
        now = datetime.datetime.now().isoformat()

        if result == FetchResult.HAS_DATA and df_new is not None:
            data_start = df_new["datetime"].min()[:10]
            data_end = df_new["datetime"].max()[:10]

            meta.status = "active"
            meta.consecutive_errors = 0
            meta.last_checked = now

            if meta.known_data_start is None or data_start < meta.known_data_start:
                meta.known_data_start = data_start
            if meta.known_data_end is None or data_end > meta.known_data_end:
                meta.known_data_end = data_end

            meta.checked_ranges.append((fetch_start, fetch_end, "has_data"))
            meta.checked_ranges = merge_checked_ranges(meta.checked_ranges)

        elif result == FetchResult.EMPTY:
            if meta.status == "active":
                logger.info(
                    "Estação %s (%s) não retornou dados para %s–%s — "
                    "possivelmente inativada",
                    meta.code,
                    meta.variable,
                    fetch_start,
                    fetch_end,
                )
            meta.status = "inactive"
            meta.consecutive_errors = 0
            meta.last_checked = now
            meta.checked_ranges.append((fetch_start, fetch_end, "empty"))
            meta.checked_ranges = merge_checked_ranges(meta.checked_ranges)

        else:  # ERROR
            meta.consecutive_errors += 1
            if meta.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                meta.status = "error"
            meta.last_checked = now

        return meta

    def fetch_data(
        self,
        stations: list[Station],
        start: str,
        end: str,
        variable: str,
        max_workers: int = 5,
        rebuild: bool = False,
        update_active: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """Baixa séries temporais para as estações fornecidas.

        Usa metadados de cache para:

        - Servir dados diretamente do parquet quando o intervalo já está coberto.
        - Pular estações cujo cache negativo ainda está dentro do TTL.
        - Buscar apenas os sub-intervalos ainda não consultados (gaps).
        - Detectar reativações ao re-consultar intervalos ``"empty"`` com TTL expirado.

        Cada resultado é salvo incrementalmente no disco imediatamente após
        ser recebido, garantindo que um crash não perca o progresso acumulado.

        Parameters
        ----------
        stations : list[Station]
        start : str
            Data de início no formato ``YYYY-MM-DD``.
        end : str
            Data de fim no formato ``YYYY-MM-DD``.
        variable : str
            ``"chuva"``, ``"nivel"``, ``"vazao"`` ou ``"cota"``.
        max_workers : int, optional
        rebuild : bool, optional
            Se ``True``, ignora todo o cache e re-consulta todas as estações.
        update_active : bool, optional
            Se ``True``, re-consulta estações com ``status="active"`` mesmo
            que o intervalo já esteja coberto.

        Returns
        -------
        dict[str, pd.DataFrame]
        """
        results: dict[str, pd.DataFrame] = {}
        tasks: list[tuple[Station, str, str]] = []

        for st in stations:
            if self._cache is None or rebuild:
                tasks.append((st, start, end))
                continue

            meta = self._cache.load_meta(variable, st.code) or StationMeta.create(
                st.code, variable
            )

            if self._is_in_error_cooldown(meta):
                logger.debug("Estação %s em cooldown de erro — ignorada", st.code)
                continue

            # update_active: força re-consulta de estações ativas sem verificar gaps
            if update_active and meta.status == "active":
                tasks.append((st, start, end))
                continue

            ttl = self._compute_ttl(meta)
            targets = find_fetch_targets(
                meta.checked_ranges, start, end, meta.last_checked, ttl
            )

            if not targets:
                df = self._cache.load_station_data(variable, st.code)
                if df is not None:
                    subset = _filter_date_range(df, start, end)
                    if len(subset) > 0:
                        results[st.code] = subset
                continue

            if self._should_skip_within_ttl(meta, ttl):
                logger.debug(
                    "Estação %s (%s) inativa dentro do TTL — ignorada para %s–%s",
                    st.code,
                    variable,
                    start,
                    end,
                )
                continue

            # Busca o span mínimo que cobre todos os targets
            fetch_start = min(t[0] for t in targets)
            fetch_end = max(t[1] for t in targets)
            tasks.append((st, fetch_start, fetch_end))

        if tasks:
            self._run_fetch_tasks(
                tasks,
                variable,
                start,
                end,
                rebuild,
                results,
                max_workers=max_workers,
            )

        return results

    def _run_fetch_tasks(
        self,
        tasks: list[tuple[Station, str, str]],
        variable: str,
        result_start: str,
        result_end: str,
        rebuild: bool,
        results: dict[str, pd.DataFrame],
        max_workers: int = 5,
    ) -> None:
        """Executa as tarefas de fetch em paralelo e persiste os resultados.

        Parameters
        ----------
        tasks : list of tuple
            Lista de ``(station, fetch_start, fetch_end)``.
        variable : str
        result_start : str
            Início do período solicitado pelo usuário (para filtro final).
        result_end : str
            Fim do período solicitado pelo usuário (para filtro final).
        rebuild : bool
        results : dict
            Dicionário de resultados a ser preenchido in-place.
        max_workers : int, optional
        """
        prefix = "[yellow]Rebuild[/] " if rebuild else ""
        desc = f"{prefix}Baixando {variable}"

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[bold]{task.completed}/{task.total}[/]"),
            TaskProgressColumn(),
            TextColumn("{task.fields[status]}"),
            TimeRemainingColumn(),
            console=_console,
            transient=True,
        ) as progress:
            task_id = progress.add_task(desc, total=len(tasks), status="")

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                fut_map: dict[
                    Future[tuple[FetchResult, pd.DataFrame | None]],
                    tuple[Station, str, str],
                ] = {
                    pool.submit(
                        self._data_port.fetch_series,
                        st,
                        fetch_start,
                        fetch_end,
                        variable,
                    ): (st, fetch_start, fetch_end)
                    for st, fetch_start, fetch_end in tasks
                }

                for future in as_completed(fut_map):
                    st, fetch_start, fetch_end = fut_map[future]
                    try:
                        fetch_result, df_new = future.result()
                    except Exception as exc:
                        logger.warning(
                            "Erro inesperado na future de %s: %s", st.code, exc
                        )
                        fetch_result, df_new = FetchResult.ERROR, None

                    self._process_fetch_result(
                        st,
                        fetch_result,
                        df_new,
                        fetch_start,
                        fetch_end,
                        variable,
                        result_start,
                        result_end,
                        results,
                    )

                    progress.update(
                        task_id,
                        advance=1,
                        status=f"[cyan]{st.code} {st.name}[/]",
                    )
                    if fetch_result == FetchResult.HAS_DATA:
                        logger.info("Estação %s (%s) — dados ok", st.code, st.name)
                    elif fetch_result == FetchResult.EMPTY:
                        logger.warning("Estação %s (%s) — sem dados", st.code, st.name)
                    else:
                        logger.error("Estação %s (%s) — erro de rede", st.code, st.name)

    def _process_fetch_result(
        self,
        st: Station,
        fetch_result: FetchResult,
        df_new: pd.DataFrame | None,
        fetch_start: str,
        fetch_end: str,
        variable: str,
        result_start: str,
        result_end: str,
        results: dict[str, pd.DataFrame],
    ) -> None:
        """Salva dados e metadados de um resultado e popula *results*.

        Chamado imediatamente após cada future completar, garantindo
        persistência incremental independentemente de crashes posteriores.
        """
        if self._cache:
            meta = self._cache.load_meta(variable, st.code) or StationMeta.create(
                st.code, variable
            )
            meta = self._update_meta_after_fetch(
                meta, fetch_result, df_new, fetch_start, fetch_end
            )

            if fetch_result == FetchResult.HAS_DATA and df_new is not None:
                self._cache.concat_station_data(variable, st.code, df_new)

            self._cache.save_meta(meta)

        if fetch_result == FetchResult.HAS_DATA:
            source = (
                self._cache.load_station_data(variable, st.code)
                if self._cache
                else df_new
            )
            if source is not None:
                subset = _filter_date_range(source, result_start, result_end)
                if len(subset) > 0:
                    results[st.code] = subset

    def scan_catalog(
        self,
        stations: list[Station],
        variable: str,
        max_workers: int = 20,
        probe_days: int = 30,
    ) -> dict[str, StationMeta]:
        """Sonda o catálogo completo para identificar estações com dados recentes.

        Consulta apenas estações cujos metadados estão ausentes ou com TTL
        expirado para o intervalo de sondagem. Atualiza metadados e persiste
        dados do período de sondagem — não baixa séries históricas completas.

        Use este método periodicamente (ex: semanalmente) para manter o
        mapa de estações ativas atualizado, de forma independente de
        ``fetch_data``.

        Parameters
        ----------
        stations : list[Station]
        variable : str
        max_workers : int, optional
        probe_days : int, optional
            Número de dias recentes a sondar. Padrão: 30.

        Returns
        -------
        dict[str, StationMeta]
        """
        today = datetime.date.today()
        probe_end = today.isoformat()
        probe_start = (today - datetime.timedelta(days=probe_days)).isoformat()

        metas: dict[str, StationMeta] = {}
        to_scan: list[tuple[Station, str, str]] = []

        for st in stations:
            meta = (
                self._cache.load_meta(variable, st.code)
                if self._cache
                else StationMeta.create(st.code, variable)
            ) or StationMeta.create(st.code, variable)
            metas[st.code] = meta

            if self._cache is None:
                to_scan.append((st, probe_start, probe_end))
                continue

            if self._is_in_error_cooldown(meta):
                continue

            ttl = self._compute_ttl(meta)
            targets = find_fetch_targets(
                meta.checked_ranges, probe_start, probe_end, meta.last_checked, ttl
            )
            if targets:
                to_scan.append((st, probe_start, probe_end))

        if not to_scan:
            return metas

        scan_results: dict[str, pd.DataFrame] = {}
        self._run_fetch_tasks(
            to_scan,
            variable,
            probe_start,
            probe_end,
            False,
            scan_results,
            max_workers=max_workers,
        )

        if self._cache:
            for st in stations:
                loaded = self._cache.load_meta(variable, st.code)
                if loaded is not None:
                    metas[st.code] = loaded

        return metas
