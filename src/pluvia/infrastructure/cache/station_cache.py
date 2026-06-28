"""Cache em disco para inventário, metadados e séries temporais de estações."""

from __future__ import annotations

import dataclasses
import datetime
import json
import threading
from dataclasses import field
from pathlib import Path

import pandas as pd

from pluvia.domain.entities import Station


@dataclasses.dataclass
class StationMeta:
    """Metadados de cache para uma estação e variável específicas.

    Armazena o histórico de consultas à API, permitindo decisões de cache
    baseadas em intervalos de datas em vez de um estado binário global.
    Pertence à camada de infraestrutura pois modela o estado interno do
    cache, não um conceito do domínio hidrometeorológico.

    Attributes
    ----------
    code : str
        Código da estação.
    variable : str
        Variável monitorada (ex: ``"chuva"``).
    status : str
        Estado atual: ``"active"``, ``"inactive"``, ``"unknown"`` ou ``"error"``.
    known_data_start : str or None
        Primeira data com dado confirmado (formato ISO YYYY-MM-DD).
    known_data_end : str or None
        Última data com dado confirmado (formato ISO YYYY-MM-DD).
    checked_ranges : list of tuple
        Intervalos já consultados na API: cada entrada é
        ``(start, end, kind)`` onde *kind* é ``"has_data"`` ou ``"empty"``.
    last_checked : str or None
        Timestamp da última consulta bem-sucedida (ISO format).
    consecutive_errors : int
        Contagem de erros de rede consecutivos sem resposta válida.
    """

    code: str
    variable: str
    status: str
    known_data_start: str | None
    known_data_end: str | None
    checked_ranges: list[tuple[str, str, str]]
    last_checked: str | None
    consecutive_errors: int = field(default=0)

    @classmethod
    def create(cls, code: str, variable: str) -> StationMeta:
        """Cria um novo metadado no estado inicial ``"unknown"``.

        Parameters
        ----------
        code : str
            Código da estação.
        variable : str
            Variável monitorada.

        Returns
        -------
        StationMeta
        """
        return cls(
            code=code,
            variable=variable,
            status="unknown",
            known_data_start=None,
            known_data_end=None,
            checked_ranges=[],
            last_checked=None,
            consecutive_errors=0,
        )

    def to_dict(self) -> dict:
        """Serializa o metadado para um dicionário JSON-serializável."""
        return {
            "code": self.code,
            "variable": self.variable,
            "status": self.status,
            "known_data_start": self.known_data_start,
            "known_data_end": self.known_data_end,
            "checked_ranges": [list(r) for r in self.checked_ranges],
            "last_checked": self.last_checked,
            "consecutive_errors": self.consecutive_errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StationMeta:
        """Desserializa um metadado a partir de um dicionário.

        Parameters
        ----------
        data : dict
            Dicionário com os campos do metadado.

        Returns
        -------
        StationMeta
        """
        return cls(
            code=data["code"],
            variable=data["variable"],
            status=data.get("status", "unknown"),
            known_data_start=data.get("known_data_start"),
            known_data_end=data.get("known_data_end"),
            checked_ranges=[
                (str(r[0]), str(r[1]), str(r[2]))
                for r in data.get("checked_ranges", [])
            ],
            last_checked=data.get("last_checked"),
            consecutive_errors=data.get("consecutive_errors", 0),
        )


class StationCache:
    """Cache persistente para inventário, metadados e séries temporais.

    Estrutura de diretórios dentro de *cache_dir*::

        inventory.json               – lista completa de estações
        stations.json                – legado: dict[code, bool]
        data/{variable}/{code}.parquet  – séries temporais
        meta/{variable}/{code}.json  – metadados ricos por estação+variável

    Os arquivos de metadados são gravados atomicamente (write-to-tmp + rename)
    para garantir consistência mesmo em caso de interrupção do processo.

    Parameters
    ----------
    cache_dir : Path
        Diretório onde os arquivos de cache são armazenados.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._path = cache_dir
        self._inventory_file = self._path / "inventory.json"
        self._stations_file = self._path / "stations.json"
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        """Caminho do diretório de cache."""
        return self._path

    def has_inventory(self) -> bool:
        """Verifica se existe um inventário em cache no disco."""
        with self._lock:
            return self._inventory_file.exists()

    def inventory_age_days(self) -> float | None:
        """Retorna a idade do inventário em dias, ou ``None`` se não existir."""
        with self._lock:
            if not self._inventory_file.exists():
                return None
            mtime = datetime.datetime.fromtimestamp(
                self._inventory_file.stat().st_mtime
            )
            return (datetime.datetime.now() - mtime).total_seconds() / 86400

    def load_inventory(self) -> list[Station] | None:
        """Carrega o inventário em cache do disco, ou retorna ``None``."""
        with self._lock:
            if not self._inventory_file.exists():
                return None
            with self._inventory_file.open("r") as f:
                data = json.load(f)
        return [Station(**s) for s in data]

    def save_inventory(self, stations: list[Station]) -> None:
        """Salva o inventário de estações no disco como JSON."""
        self._path.mkdir(parents=True, exist_ok=True)
        data = [dataclasses.asdict(s) for s in stations]
        tmp = self._inventory_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.rename(self._inventory_file)

    def _meta_path(self, variable: str, code: str) -> Path:
        return self._path / "meta" / variable / f"{code}.json"

    def has_meta(self, variable: str, code: str) -> bool:
        """Verifica se existe metadado em cache para a estação e variável."""
        return self._meta_path(variable, code).exists()

    def load_meta(self, variable: str, code: str) -> StationMeta | None:
        """Carrega o metadado de cache para uma estação e variável.

        Parameters
        ----------
        variable : str
            Nome da variável (ex: ``"chuva"``).
        code : str
            Código da estação.

        Returns
        -------
        StationMeta or None
            Metadado encontrado, ou ``None`` se não existir.
        """
        path = self._meta_path(variable, code)
        if not path.exists():
            return None
        try:
            return StationMeta.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, KeyError):
            return None

    def save_meta(self, meta: StationMeta) -> None:
        """Salva o metadado de cache atomicamente.

        Usa write-to-tmp + rename para garantir que um crash no meio da
        gravação não deixe o arquivo corrompido.

        Parameters
        ----------
        meta : StationMeta
            Metadado a ser persistido.
        """
        path = self._meta_path(meta.variable, meta.code)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta.to_dict(), indent=2))
        tmp.rename(path)

    def load_stations(self) -> dict[str, bool] | None:
        """Carrega o mapa de disponibilidade legado do disco, ou ``None``."""
        with self._lock:
            if not self._stations_file.exists():
                return None
            with self._stations_file.open("r") as f:
                return json.load(f)

    def save_stations(self, data: dict[str, bool]) -> None:
        """Salva o mapa de disponibilidade legado no disco."""
        self._path.mkdir(parents=True, exist_ok=True)
        with self._lock, self._stations_file.open("w") as f:
            json.dump(data, f, indent=2)

    def update_station(self, code: str, has_data: bool) -> None:
        """Atualiza a disponibilidade de uma estação no mapa legado."""
        with self._lock:
            data = self.load_stations() or {}
            data[code] = has_data
            with self._stations_file.open("w") as f:
                json.dump(data, f, indent=2)

    @property
    def data_dir(self) -> Path:
        """Diretório onde os arquivos parquet por variável são armazenados."""
        p = self._path / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _data_file(self, variable: str, code: str) -> Path:
        return self.data_dir / variable / f"{code}.parquet"

    def save_station_data(self, variable: str, code: str, df: pd.DataFrame) -> None:
        """Salva a série temporal de uma estação como parquet."""
        path = self._data_file(variable, code)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    def load_station_data(self, variable: str, code: str) -> pd.DataFrame | None:
        """Carrega a série temporal em cache de uma estação, ou ``None``."""
        path = self._data_file(variable, code)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def concat_station_data(
        self, variable: str, code: str, df_new: pd.DataFrame
    ) -> None:
        """Mescla *df_new* com os dados existentes e persiste.

        Linhas com o mesmo ``"datetime"`` são sobrescritas pelos novos valores,
        garantindo que uma atualização sempre reflita os dados mais recentes.
        *df_new* deve estar no schema atual (colunas ``"datetime"`` e ``"value"``).

        Parameters
        ----------
        variable : str
            Nome da variável.
        code : str
            Código da estação.
        df_new : pd.DataFrame
            Novos dados a mesclar.
        """
        existing = self.load_station_data(variable, code)
        if existing is None:
            self.save_station_data(variable, code, df_new)
            return
        combined = pd.concat([existing, df_new], ignore_index=True)
        combined = combined.drop_duplicates(subset="datetime", keep="last")
        combined = combined.sort_values("datetime").reset_index(drop=True)
        self.save_station_data(variable, code, combined)

    def clear(self) -> None:
        """Remove todos os arquivos de cache."""
        import shutil

        with self._lock:
            for f in [self._inventory_file, self._stations_file]:
                if f.exists():
                    f.unlink()
            for subdir in ["data", "meta"]:
                d = self._path / subdir
                if d.exists():
                    shutil.rmtree(d)
