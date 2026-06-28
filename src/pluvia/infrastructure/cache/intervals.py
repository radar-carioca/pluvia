"""Álgebra de intervalos de datas para o cache de séries temporais.

Fornece funções para manipular listas de intervalos verificados,
encontrar lacunas ainda não consultadas e identificar intervalos
com cache negativo expirado.
"""

from __future__ import annotations

import datetime

# (início, fim, tipo) — tipo é "has_data" ou "empty"
CheckedRange = tuple[str, str, str]
DateRange = tuple[str, str]

_ONE_DAY = datetime.timedelta(days=1)


def _to_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])


def _from_date(d: datetime.date) -> str:
    return d.isoformat()


def _merge_pairs(
    pairs: list[tuple[datetime.date, datetime.date]],
) -> list[tuple[datetime.date, datetime.date]]:
    """Mescla pares de datas sobrepostos ou adjacentes."""
    if not pairs:
        return []
    sorted_pairs = sorted(pairs)
    merged = [sorted_pairs[0]]
    for start, end in sorted_pairs[1:]:
        if start <= merged[-1][1] + _ONE_DAY:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def merge_checked_ranges(ranges: list[CheckedRange]) -> list[CheckedRange]:
    """Compacta intervalos adjacentes ou sobrepostos do mesmo tipo.

    Mantém a lista de ``checked_ranges`` compacta após cada inserção,
    evitando crescimento ilimitado ao longo de muitas execuções.

    Parameters
    ----------
    ranges : list of CheckedRange
        Lista de ``(start, end, kind)`` onde *kind* é ``"has_data"``
        ou ``"empty"``.

    Returns
    -------
    list of CheckedRange
        Lista compactada, ordenada por data de início.
    """
    if not ranges:
        return []

    by_kind: dict[str, list[tuple[datetime.date, datetime.date]]] = {}
    for start, end, kind in ranges:
        by_kind.setdefault(kind, []).append((_to_date(start), _to_date(end)))

    result: list[CheckedRange] = []
    for kind, pairs in by_kind.items():
        for s, e in _merge_pairs(pairs):
            result.append((_from_date(s), _from_date(e), kind))

    return sorted(result, key=lambda x: x[0])


def find_unchecked_gaps(
    checked_ranges: list[CheckedRange],
    start: str,
    end: str,
) -> list[DateRange]:
    """Retorna sub-intervalos de ``[start, end]`` nunca consultados na API.

    Ignora o tipo (``"has_data"`` ou ``"empty"``) — qualquer cobertura
    anterior elimina o gap, independentemente do resultado.

    Parameters
    ----------
    checked_ranges : list of CheckedRange
        Intervalos já consultados.
    start : str
        Início do intervalo de interesse (``YYYY-MM-DD``).
    end : str
        Fim do intervalo de interesse (``YYYY-MM-DD``).

    Returns
    -------
    list of DateRange
        Sub-intervalos ``(start, end)`` sem cobertura.
    """
    if not checked_ranges:
        return [(start, end)]

    req_start = _to_date(start)
    req_end = _to_date(end)

    covered: list[tuple[datetime.date, datetime.date]] = []
    for s, e, _ in checked_ranges:
        cs = max(_to_date(s), req_start)
        ce = min(_to_date(e), req_end)
        if cs <= ce:
            covered.append((cs, ce))

    if not covered:
        return [(start, end)]

    gaps: list[DateRange] = []
    cursor = req_start
    for cs, ce in _merge_pairs(covered):
        if cursor < cs:
            gaps.append((_from_date(cursor), _from_date(cs - _ONE_DAY)))
        cursor = ce + _ONE_DAY

    if cursor <= req_end:
        gaps.append((_from_date(cursor), _from_date(req_end)))

    return gaps


def find_expired_empty_ranges(
    checked_ranges: list[CheckedRange],
    start: str,
    end: str,
    last_checked: str | None,
    ttl_days: int,
) -> list[DateRange]:
    """Retorna intervalos ``"empty"`` dentro de ``[start, end]`` com TTL expirado.

    Quando o TTL expira, intervalos anteriormente confirmados como vazios
    devem ser re-consultados para detectar possíveis reativações de estações.

    Parameters
    ----------
    checked_ranges : list of CheckedRange
        Intervalos já consultados.
    start : str
        Início do intervalo de interesse.
    end : str
        Fim do intervalo de interesse.
    last_checked : str or None
        Timestamp da última consulta (ISO format). ``None`` retorna lista vazia.
    ttl_days : int
        Validade do cache negativo em dias.

    Returns
    -------
    list of DateRange
        Intervalos ``"empty"`` cujo TTL expirou e devem ser re-consultados.
    """
    if last_checked is None or ttl_days <= 0:
        return []

    last_dt = datetime.datetime.fromisoformat(last_checked)
    age_days = (datetime.datetime.now() - last_dt).days
    if age_days < ttl_days:
        return []

    req_start = _to_date(start)
    req_end = _to_date(end)

    expired: list[tuple[datetime.date, datetime.date]] = []
    for s, e, kind in checked_ranges:
        if kind != "empty":
            continue
        cs = max(_to_date(s), req_start)
        ce = min(_to_date(e), req_end)
        if cs <= ce:
            expired.append((cs, ce))

    return [(_from_date(s), _from_date(e)) for s, e in _merge_pairs(expired)]


def find_fetch_targets(
    checked_ranges: list[CheckedRange],
    start: str,
    end: str,
    last_checked: str | None,
    ttl_days: int,
) -> list[DateRange]:
    """Combina gaps não consultados com intervalos ``"empty"`` com TTL expirado.

    É o ponto de entrada principal para decidir o que precisa ser (re-)consultado
    na API para um dado intervalo de interesse.

    Parameters
    ----------
    checked_ranges : list of CheckedRange
        Intervalos já consultados.
    start : str
        Início do intervalo de interesse.
    end : str
        Fim do intervalo de interesse.
    last_checked : str or None
        Timestamp da última consulta.
    ttl_days : int
        Validade do cache negativo em dias.

    Returns
    -------
    list of DateRange
        Sub-intervalos que precisam ser (re-)consultados na API,
        mesclados e ordenados.
    """
    unchecked = find_unchecked_gaps(checked_ranges, start, end)
    expired = find_expired_empty_ranges(
        checked_ranges, start, end, last_checked, ttl_days
    )

    all_pairs = [(_to_date(s), _to_date(e)) for s, e in unchecked + expired]
    if not all_pairs:
        return []

    return [(_from_date(s), _from_date(e)) for s, e in _merge_pairs(all_pairs)]
