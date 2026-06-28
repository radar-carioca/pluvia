"""SOAP client for ANA hydrometeorological web service.

Fetches station inventory and time series data via the ANA SOAP API,
with thread-safe connection pooling, rate limiting, and XML parsing.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import cast

import pandas as pd
from requests import Session
from zeep import Client
from zeep import Settings
from zeep.transports import Transport
from zeep.wsdl.wsdl import Document

from pluvia.domain.entities import Station
from pluvia.domain.ports import FetchResult
from pluvia.domain.ports import StationDataPort
from pluvia.domain.ports import StationInventoryPort
from pluvia.infrastructure.ana.constants import ANA_WSDL
from pluvia.infrastructure.ana.constants import STATION_TYPE_MAP
from pluvia.infrastructure.ana.constants import VARIABLE_MAP
from pluvia.infrastructure.ana.parser import parse_conventional
from pluvia.infrastructure.ana.parser import parse_inventory
from pluvia.infrastructure.ana.parser import parse_telemetric

logger = logging.getLogger("pluvia.ana")

# Zeep emite warnings de redirecionamento HTTPS sem valor operacional.
logging.getLogger("zeep.wsdl.bindings.soap").setLevel(logging.ERROR)
logging.getLogger("zeep.wsdl.bindings.http").setLevel(logging.ERROR)

_RATE_LIMIT = 0.3
_thread_local = threading.local()

_wsdl_doc: Document | None = None
_wsdl_lock = threading.Lock()


def _get_wsdl_document(timeout: int = 120) -> Document:
    global _wsdl_doc
    if _wsdl_doc is not None:
        return _wsdl_doc
    with _wsdl_lock:
        if _wsdl_doc is not None:
            return _wsdl_doc
        settings = Settings(raw_response=True)
        session = Session()
        transport = Transport(
            session=session, timeout=timeout, operation_timeout=timeout
        )
        for attempt in range(1, 4):
            try:
                _wsdl_doc = Document(ANA_WSDL, transport, settings=settings)
                return _wsdl_doc
            except Exception:
                if attempt < 3:
                    time.sleep(5 * attempt)
                else:
                    raise
    raise RuntimeError("Não foi possível carregar o documento WSDL")  # pragma: no cover


def _get_soap_client(timeout: int = 120) -> Client:
    try:
        return _thread_local.soap_client  # type: ignore[attr-defined]
    except AttributeError:
        doc = _get_wsdl_document(timeout)
        settings = Settings(raw_response=True)
        session = Session()
        transport = Transport(
            session=session, timeout=timeout, operation_timeout=timeout
        )
        _thread_local.soap_client = Client(
            wsdl=doc, settings=settings, transport=transport
        )
        return _thread_local.soap_client  # type: ignore[attr-defined]


def _to_parquet_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza um DataFrame para o schema padrão de parquet.

    Converte DataFrames com índice DatetimeIndex e coluna de variável
    para o formato canônico com duas colunas: ``"datetime"`` (ISO string)
    e ``"value"`` (float).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame com índice DatetimeIndex e uma coluna de dados.

    Returns
    -------
    pd.DataFrame
        DataFrame com colunas ``["datetime", "value"]`` e índice inteiro.
    """
    return pd.DataFrame(
        {
            "datetime": cast(pd.DatetimeIndex, df.index).strftime("%Y-%m-%dT%H:%M:%S"),
            "value": df.iloc[:, 0].to_numpy(dtype=float, na_value=float("nan")),
        }
    )


def _filter_date_range(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Filtra um DataFrame pelo intervalo de datas.

    Suporta o schema atual (colunas ``"datetime"`` e ``"value"``) e o
    schema legado (índice DatetimeIndex com coluna de variável).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame a filtrar.
    start : str
        Data de início no formato ``YYYY-MM-DD``.
    end : str
        Data de fim no formato ``YYYY-MM-DD``.

    Returns
    -------
    pd.DataFrame
        Subconjunto filtrado.
    """
    import datetime as dt

    if "datetime" in df.columns:
        # Schema atual: datetime como coluna de string ISO
        # Usa o próximo dia como limite exclusivo para capturar todos os
        # timestamps do dia final (ex: 2026-06-09T23:00:00 ≤ fim)
        end_exclusive = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
        mask = (df["datetime"] >= start) & (df["datetime"] < end_exclusive)
        return df.loc[mask].reset_index(drop=True)

    # Schema legado: índice DatetimeIndex — mantido para compatibilidade
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    mask = (df.index >= start_ts) & (df.index <= end_ts)
    return df.loc[mask]


_HIDRO_INVENTARIO_PARAMS = [
    "codEstDE",
    "codEstATE",
    "tpEst",
    "nmEst",
    "nmRio",
    "codSubBacia",
    "codBacia",
    "nmMunicipio",
    "nmEstado",
    "sgResp",
    "sgOper",
    "telemetrica",
]


class AnaClient(StationInventoryPort, StationDataPort):
    """Adaptador SOAP para o serviço de dados hidrometeorológicos da ANA.

    Implementa ``StationInventoryPort`` e ``StationDataPort``. Encapsula
    toda a lógica de comunicação com o serviço SOAP da ANA: pool de
    clientes por thread, rate limiting e parsing de respostas XML.

    A orquestração de cache, TTL, retentativas e paralelismo é
    responsabilidade da camada de aplicação.

    Parameters
    ----------
    timeout : int, optional
        Timeout das requisições SOAP em segundos. Padrão: 120.
    """

    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout

    def _rate_limit(self) -> None:
        last = getattr(_thread_local, "last_call", 0.0)
        elapsed = time.monotonic() - last
        if elapsed < _RATE_LIMIT:
            time.sleep(_RATE_LIMIT - elapsed)
        _thread_local.last_call = time.monotonic()

    def _call(self, method: str, **kwargs: str) -> bytes:
        self._rate_limit()
        client = _get_soap_client(self._timeout)
        try:
            resp = getattr(client.service, method)(**kwargs)
            return resp.content  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning("Chamada ANA %s falhou: %s", method, exc)
            raise

    def fetch_inventory(self, station_type: str | None = None) -> list[Station]:
        """Busca o inventário completo de estações via SOAP.

        Parameters
        ----------
        station_type : str or None, optional
            ``"fluviometrica"``, ``"pluviometrica"`` ou ``"telemetric"``.

        Returns
        -------
        list[Station]
        """
        params: dict[str, str] = dict.fromkeys(_HIDRO_INVENTARIO_PARAMS, "")
        if station_type and station_type in STATION_TYPE_MAP:
            tp = STATION_TYPE_MAP[station_type]
            if tp is not None:
                params["tpEst"] = tp
        xml = self._call("HidroInventario", **params)
        return parse_inventory(xml)

    def fetch_series(
        self,
        station: Station,
        start: str,
        end: str,
        variable: str,
    ) -> tuple[FetchResult, pd.DataFrame | None]:
        """Busca a série temporal de uma estação via SOAP.

        Distingue erros de rede (``FetchResult.ERROR``) de respostas
        genuinamente vazias (``FetchResult.EMPTY``), permitindo que a
        camada de aplicação trate os dois casos de forma diferente.

        Parameters
        ----------
        station : Station
            Estação a consultar.
        start : str
            Início do período (``YYYY-MM-DD``).
        end : str
            Fim do período (``YYYY-MM-DD``).
        variable : str
            Variável a buscar.

        Returns
        -------
        tuple[FetchResult, pd.DataFrame or None]
        """
        var_info = VARIABLE_MAP.get(variable)
        if var_info is None:
            raise ValueError(
                f"Variável desconhecida: {variable}. Use: chuva, nivel, vazao, cota"
            )
        var_name, tipo_dado, _ = var_info

        code = station.code
        station_type = station.station_type

        try:
            if variable == "cota" or (
                variable in ("nivel", "vazao") and station_type != "telemetric"
            ):
                xml = self._call(
                    "HidroSerieHistorica",
                    codEstacao=code,
                    dataInicio=start,
                    dataFim=end,
                    tipoDados=tipo_dado,
                )
                df = parse_conventional(xml, tipo_dado)
            else:
                xml = self._call(
                    "DadosHidrometeorologicos",
                    codEstacao=code,
                    dataInicio=start,
                    dataFim=end,
                )
                df = parse_telemetric(xml)
                if df is not None and var_name in df.columns:
                    df = df[[var_name]]
                elif df is not None:
                    return FetchResult.EMPTY, None

            if df is None or len(df) == 0:
                return FetchResult.EMPTY, None

            # Estação com todas as leituras nulas não está operante
            if df.iloc[:, 0].isna().all():
                return FetchResult.EMPTY, None

            return FetchResult.HAS_DATA, _to_parquet_schema(df)

        except Exception:
            return FetchResult.ERROR, None
