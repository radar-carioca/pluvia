"""XML parsers for ANA SOAP responses."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pandas as pd

from pluvia.domain.entities import Station
from pluvia.infrastructure.ana.constants import DIFFGRAM_PATH
from pluvia.infrastructure.ana.constants import SOAP_NAMESPACES
from pluvia.infrastructure.ana.constants import TELEMETRIC_VARS

INVENTORY_RE = re.compile(
    r'<Table diffgr:id="Table[0-9]+" '
    r'msdata:rowOrder="[0-9]+">(.*?)</Table>',
    re.DOTALL,
)
TAG_RE = re.compile(r"<([a-zA-Z0-9]+)>(.*?)</[a-zA-Z0-9]+>")


def parse_inventory(xml_bytes: bytes) -> list[Station]:
    """Parse ANA HidroInventario XML response into Station objects.

    Parameters
    ----------
    xml_bytes : bytes
        Raw XML response from the ANA web service.

    Returns
    -------
    list[Station]
    """
    xml_text = xml_bytes.decode("utf-8")
    stations = []
    for table in INVENTORY_RE.findall(xml_text):
        row = dict(TAG_RE.findall(table))
        code = row.get("Codigo", "").strip()
        if not code:
            continue
        is_telemetric = row.get("TipoEstacaoTelemetrica", "0") == "1"
        if is_telemetric:
            st_type = "telemetric"
        else:
            st_type = row.get("TipoEstacao", "2")
            st_type = {"1": "fluviometrica", "2": "pluviometrica"}.get(st_type, st_type)

        stations.append(
            Station(
                code=code,
                name=row.get("Nome", ""),
                latitude=float(row.get("Latitude", 0)),
                longitude=float(row.get("Longitude", 0)),
                station_type=st_type,
                state=row.get("nmEstado"),
                municipality=row.get("nmMunicipio"),
                basin=row.get("BaciaCodigo"),
                subbasin=row.get("SubBaciaCodigo"),
                river=row.get("RioNome"),
                responsible=row.get("ResponsavelSigla"),
            )
        )
    return stations


def parse_telemetric(xml_bytes: bytes) -> pd.DataFrame | None:
    """Parse a DadosHidrometeorologicos response into a DataFrame.

    Parameters
    ----------
    xml_bytes : bytes
        Raw XML response.

    Returns
    -------
    pd.DataFrame or None
        Indexed by DataHora, or None if no data.
    """
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    result_node = root.find(".//mrcs:DadosHidrometeorologicosResult", SOAP_NAMESPACES)
    if result_node is None:
        return None
    diffgram_node = result_node.find(DIFFGRAM_PATH)
    if diffgram_node is None:
        return None
    records = []
    for elem in diffgram_node.findall(".//DocumentElement/*"):
        record = {child.tag: child.text for child in elem}
        records.append(record)
    if not records:
        return None
    df = pd.DataFrame(records)
    if "DataHora" not in df.columns:
        return None
    df["DataHora"] = pd.to_datetime(df["DataHora"])
    for var in TELEMETRIC_VARS & set(df.columns):
        df[var] = pd.to_numeric(df[var], errors="coerce")
    return df.set_index("DataHora").sort_index()


def parse_conventional(xml_bytes: bytes, tipo: str) -> pd.DataFrame | None:
    """Parse a HidroSerieHistorica response into a daily DataFrame.

    Parameters
    ----------
    xml_bytes : bytes
        Raw XML response.
    tipo : str
        Data type code (``"1"`` = Cota, ``"2"`` = Chuva, ``"3"`` = Vazao).

    Returns
    -------
    pd.DataFrame or None
        Indexed by date, or None if no data.
    """
    xml_text = xml_bytes.decode("utf-8")
    serie_re = re.compile(
        r'<SerieHistorica diffgr:id="SerieHistorica[0-9]+" '
        r'msdata:rowOrder="[0-9]+">(.*?)</SerieHistorica>',
        re.DOTALL,
    )
    tables = serie_re.findall(xml_text)
    if not tables:
        return None
    df = pd.DataFrame(dict(TAG_RE.findall(table)) for table in tables)
    if len(df) == 0:
        return None

    var_map = {"1": "Cota", "2": "Chuva", "3": "Vazao"}
    var = var_map.get(tipo, "Chuva")

    df["DataHora"] = pd.to_datetime(df["DataHora"])
    colunas_dado = [
        c for c in df.columns if c.startswith(var) and not c.endswith("Status")
    ]
    if not colunas_dado:
        return None

    df_melt = df.melt(
        id_vars=["DataHora", "NivelConsistencia"],
        value_vars=colunas_dado,
        var_name="Dia",
        value_name=var,
    )
    df_melt["Dia"] = df_melt["Dia"].str.extract(r"(\d+)", expand=False).astype(int)
    df_melt["Data"] = df_melt["DataHora"] + pd.to_timedelta(
        df_melt["Dia"] - 1, unit="D"
    )
    df_melt = df_melt.sort_values(
        ["Data", "NivelConsistencia"], ascending=[True, False]
    )
    df_melt = df_melt.drop_duplicates(subset="Data", keep="first")

    if len(df_melt) == 0:
        return None

    result = df_melt[["Data", var]].sort_values("Data").reset_index(drop=True)
    result[var] = pd.to_numeric(result[var], errors="coerce")
    return result.set_index("Data")
