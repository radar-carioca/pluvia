"""Testes para a CLI de pluvia — argument parsing e fluxo principal."""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pandas as pd
import pytest

from pluvia.__main__ import _save_data
from pluvia.__main__ import _valid_date
from pluvia.__main__ import _valid_state
from pluvia.__main__ import main
from pluvia.__main__ import parse_args


class TestValidState:
    def test_estado_valido_caixa_alta(self):
        assert _valid_state("SP") == "SP"

    def test_estado_valido_caixa_baixa(self):
        assert _valid_state("sp") == "SP"

    def test_estado_invalido_lanca_erro(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _valid_state("XX")


class TestValidDate:
    def test_data_valida(self):
        assert _valid_date("2024-06-15") == datetime.date(2024, 6, 15)

    def test_data_invalida_lanca_erro(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _valid_date("15-06-2024")

    def test_data_malformada_lanca_erro(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _valid_date("não-é-data")


class TestParseArgs:
    def test_args_minimos(self):
        args = parse_args(["--state", "SP"])
        assert args.state == "SP"
        assert args.rebuild is False
        assert args.update_active is True

    def test_start_end_custom(self):
        args = parse_args(
            ["--state", "RJ", "--start", "2024-01-01", "--end", "2024-01-31"]
        )
        assert args.start == datetime.date(2024, 1, 1)
        assert args.end == datetime.date(2024, 1, 31)

    def test_defaults_dates(self):
        today = datetime.date.today()
        args = parse_args(["--state", "CE"])
        assert args.end == today
        assert args.start == today - datetime.timedelta(days=1)

    def test_end_menor_que_start_error(self):
        with pytest.raises(SystemExit):
            parse_args(
                ["--state", "MG", "--start", "2024-02-01", "--end", "2024-01-01"]
            )

    def test_output_default(self):
        args = parse_args(["--state", "BA"])
        assert args.output == "."

    def test_output_custom(self):
        args = parse_args(["--state", "BA", "--output", "./dados"])
        assert args.output == "./dados"

    def test_shapefile_sem_shape_id_error(self):
        with pytest.raises(SystemExit):
            parse_args(["--shapefile", "./custom.shp"])

    def test_shapefile_custom_completo(self):
        args = parse_args(
            [
                "--shapefile",
                "./bacias.shp",
                "--shape-column",
                "codigo",
                "--shape-id",
                "01",
            ]
        )
        assert args.shapefile == "./bacias.shp"
        assert args.shape_column == "codigo"
        assert args.shape_id == "01"
        assert args.state is None

    def test_shapefile_custom_com_state(self):
        args = parse_args(
            [
                "--state",
                "SP",
                "--shapefile",
                "./bacias.shp",
                "--shape-column",
                "codigo",
                "--shape-id",
                "01",
            ]
        )
        assert args.state == "SP"
        assert args.shape_id == "01"

    def test_station_type(self):
        args = parse_args(["--state", "SP", "--station-type", "fluviometrica"])
        assert args.station_type == "fluviometrica"

    def test_station_type_invalido_error(self):
        with pytest.raises(SystemExit):
            parse_args(["--state", "SP", "--station-type", "invalido"])


class TestSaveData:
    def test_salva_csvs(self, tmp_path: Path):
        data = {
            "123": pd.DataFrame({"datetime": ["2024-01-01T00:00:00"], "value": [1.0]}),
        }
        _save_data(data, tmp_path)

        csv_files = sorted(tmp_path.iterdir())
        assert len(csv_files) == 1
        assert csv_files[0].name == "123.csv"

    def test_diretorio_vazio(self, tmp_path: Path):
        _save_data({}, tmp_path)
        csv_files = list(tmp_path.iterdir())
        assert csv_files == []
        assert csv_files == []


class TestMain:
    @patch("pluvia.__main__._resolve_shapefile_path")
    @patch("pluvia.ANA")
    def test_main_fluxo_completo(self, mock_ana_cls, mock_shapefile, tmp_path: Path):
        mock_client = MagicMock()
        mock_ana_cls.return_value = mock_client

        mock_client.get_stations.return_value = [
            MagicMock(code="123", name="Teste", station_type="fluviometrica")
        ]
        mock_client.fetch_data.return_value = {
            "123": pd.DataFrame({"datetime": ["2024-01-01T00:00:00"], "value": [5.0]}),
        }
        mock_shapefile.return_value = str(tmp_path / "fake.shp")

        main(
            [
                "--state",
                "SP",
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-02",
                "--output",
                str(tmp_path),
            ]
        )

        mock_client.get_stations.assert_called_once()
        mock_client.fetch_data.assert_called_once()
        assert mock_client.fetch_data.call_args[1]["variable"] == "chuva"

    @patch("pluvia.__main__._resolve_shapefile_path")
    @patch("pluvia.ANA")
    def test_main_rebuild(self, mock_ana_cls, mock_shapefile, tmp_path: Path):
        mock_client = MagicMock()
        mock_ana_cls.return_value = mock_client
        mock_client.get_stations.return_value = []
        mock_client.fetch_data.return_value = {}
        mock_shapefile.return_value = str(tmp_path / "fake.shp")

        main(["--state", "RJ", "--rebuild", "--output", str(tmp_path)])

        assert mock_client.fetch_data.call_args[1]["rebuild"] is True

    @patch("pluvia.__main__._resolve_shapefile_path")
    @patch("pluvia.ANA")
    def test_main_update_active(self, mock_ana_cls, mock_shapefile, tmp_path: Path):
        mock_client = MagicMock()
        mock_ana_cls.return_value = mock_client
        mock_client.get_stations.return_value = []
        mock_client.fetch_data.return_value = {}
        mock_shapefile.return_value = str(tmp_path / "fake.shp")

        main(["--state", "RJ", "--update-active", "--output", str(tmp_path)])

        assert mock_client.fetch_data.call_args[1]["update_active"] is True

    @patch("pluvia.ANA")
    def test_main_shapefile_custom(self, mock_ana_cls, tmp_path: Path):
        mock_client = MagicMock()
        mock_ana_cls.return_value = mock_client
        mock_client.get_stations.return_value = []
        mock_client.fetch_data.return_value = {}

        main(
            [
                "--shapefile",
                str(tmp_path / "custom.shp"),
                "--shape-column",
                "codigo",
                "--shape-id",
                "01",
                "--output",
                str(tmp_path),
            ]
        )

        call_kwargs = mock_client.get_stations.call_args[1]
        assert call_kwargs["contour"] == str(tmp_path / "custom.shp")
        assert call_kwargs["column"] == "codigo"
        assert call_kwargs["value"] == "01"
        assert call_kwargs["station_type"] is None

    @patch("pluvia.ANA")
    def test_main_station_type(self, mock_ana_cls, tmp_path: Path):
        mock_client = MagicMock()
        mock_ana_cls.return_value = mock_client
        mock_client.get_stations.return_value = []
        mock_client.fetch_data.return_value = {}

        main(
            [
                "--state",
                "SP",
                "--station-type",
                "fluviometrica",
                "--output",
                str(tmp_path),
            ]
        )

        call_kwargs = mock_client.get_stations.call_args[1]
        assert call_kwargs["station_type"] == "fluviometrica"
