"""Testes para os parsers XML do client ANA."""

from __future__ import annotations

from pluvia.infrastructure.ana.parser import parse_conventional
from pluvia.infrastructure.ana.parser import parse_inventory
from pluvia.infrastructure.ana.parser import parse_telemetric


class TestParseInventory:
    def test_parse_inventory_vazio(self):
        xml = b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body></soap:Body></soap:Envelope>'
        result = parse_inventory(xml)
        assert result == []

    def test_parse_inventory_simples(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <Table diffgr:id="Table1" msdata:rowOrder="0">\n'
            b"      <Codigo>12345</Codigo>\n"
            b"      <Nome>Test Station</Nome>\n"
            b"      <Latitude>-23.5</Latitude>\n"
            b"      <Longitude>-46.6</Longitude>\n"
            b"      <TipoEstacao>2</TipoEstacao>\n"
            b"      <nmEstado>SP</nmEstado>\n"
            b"      <nmMunicipio>Sao Paulo</nmMunicipio>\n"
            b"    </Table>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_inventory(xml)
        assert len(result) == 1
        assert result[0].code == "12345"
        assert result[0].name == "Test Station"
        assert result[0].station_type == "pluviometrica"
        assert result[0].state == "SP"

    def test_parse_inventory_telemetrica(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <Table diffgr:id="Table1" msdata:rowOrder="0">\n'
            b"      <Codigo>999</Codigo>\n"
            b"      <Nome>Telemetric</Nome>\n"
            b"      <Latitude>-22.0</Latitude>\n"
            b"      <Longitude>-44.0</Longitude>\n"
            b"      <TipoEstacaoTelemetrica>1</TipoEstacaoTelemetrica>\n"
            b"    </Table>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_inventory(xml)
        assert len(result) == 1
        assert result[0].code == "999"
        assert result[0].station_type == "telemetric"

    def test_parse_inventory_fluviometrica(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <Table diffgr:id="Table1" msdata:rowOrder="0">\n'
            b"      <Codigo>111</Codigo>\n"
            b"      <Nome>Fluviometric</Nome>\n"
            b"      <Latitude>-21.0</Latitude>\n"
            b"      <Longitude>-43.0</Longitude>\n"
            b"      <TipoEstacao>1</TipoEstacao>\n"
            b"    </Table>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_inventory(xml)
        assert len(result) == 1
        assert result[0].station_type == "fluviometrica"

    def test_parse_inventory_sem_codigo_ignora(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <Table diffgr:id="Table1" msdata:rowOrder="0">\n'
            b"      <Codigo>   </Codigo>\n"
            b"      <Nome>Empty</Nome>\n"
            b"    </Table>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_inventory(xml)
        assert result == []

    def test_parse_inventory_multiplo(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <Table diffgr:id="Table1" msdata:rowOrder="0">\n'
            b"      <Codigo>1</Codigo>\n"
            b"    </Table>\n"
            b'    <Table diffgr:id="Table2" msdata:rowOrder="1">\n'
            b"      <Codigo>2</Codigo>\n"
            b"    </Table>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_inventory(xml)
        assert len(result) == 2
        assert result[0].code == "1"
        assert result[1].code == "2"


class TestParseTelemetric:
    def test_telemetric_vazio(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            b'xmlns:mrcs="http://MRCS/">\n'
            b"  <soap:Body>\n"
            b"    <mrcs:DadosHidrometeorologicosResponse>\n"
            b"      <mrcs:DadosHidrometeorologicosResult/>\n"
            b"    </mrcs:DadosHidrometeorologicosResponse>\n"
            b"  </soap:Body>\n"
            b"</soap:Envelope>"
        )
        result = parse_telemetric(xml)
        assert result is None

    def test_telemetric_com_dados(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            b'xmlns:mrcs="http://MRCS/">\n'
            b"  <soap:Body>\n"
            b"    <mrcs:DadosHidrometeorologicosResponse>\n"
            b"      <mrcs:DadosHidrometeorologicosResult>\n"
            b'        <diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"          <DocumentElement>\n"
            b"            <DadosHidrometeorologicos>\n"
            b"              <DataHora>2024-01-01T00:00:00</DataHora>\n"
            b"              <Chuva>10.5</Chuva>\n"
            b"              <Nivel>2.5</Nivel>\n"
            b"            </DadosHidrometeorologicos>\n"
            b"          </DocumentElement>\n"
            b"        </diffgr:diffgram>\n"
            b"      </mrcs:DadosHidrometeorologicosResult>\n"
            b"    </mrcs:DadosHidrometeorologicosResponse>\n"
            b"  </soap:Body>\n"
            b"</soap:Envelope>"
        )
        result = parse_telemetric(xml)
        assert result is not None
        assert "Chuva" in result.columns
        assert "Nivel" in result.columns
        assert result.index.name == "DataHora"
        assert len(result) == 1
        assert result["Chuva"].iloc[0] == 10.5

    def test_telemetric_sem_datahora(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            b'xmlns:mrcs="http://MRCS/">\n'
            b"  <soap:Body>\n"
            b"    <mrcs:DadosHidrometeorologicosResponse>\n"
            b"      <mrcs:DadosHidrometeorologicosResult>\n"
            b'        <diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"          <DocumentElement>\n"
            b"            <DadosHidrometeorologicos>\n"
            b"              <Chuva>10.5</Chuva>\n"
            b"            </DadosHidrometeorologicos>\n"
            b"          </DocumentElement>\n"
            b"        </diffgr:diffgram>\n"
            b"      </mrcs:DadosHidrometeorologicosResult>\n"
            b"    </mrcs:DadosHidrometeorologicosResponse>\n"
            b"  </soap:Body>\n"
            b"</soap:Envelope>"
        )
        result = parse_telemetric(xml)
        assert result is None


class TestParseConventional:
    def test_conventional_vazio(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_conventional(xml, "2")
        assert result is None

    def test_conventional_chuva(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <SerieHistorica diffgr:id="SerieHistorica1" msdata:rowOrder="0">\n'
            b"      <DataHora>2024-01-01T00:00:00</DataHora>\n"
            b"      <NivelConsistencia>1</NivelConsistencia>\n"
            b"      <Chuva1>5.0</Chuva1>\n"
            b"      <Chuva2>10.0</Chuva2>\n"
            b"      <Chuva3>0.0</Chuva3>\n"
            b"      <Chuva1Status>0</Chuva1Status>\n"
            b"    </SerieHistorica>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_conventional(xml, "2")
        assert result is not None
        assert result.index.name == "Data"
        assert len(result) == 3
        assert "Chuva" in result.columns

    def test_conventional_cota(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <SerieHistorica diffgr:id="SerieHistorica1" msdata:rowOrder="0">\n'
            b"      <DataHora>2024-01-01T00:00:00</DataHora>\n"
            b"      <NivelConsistencia>1</NivelConsistencia>\n"
            b"      <Cota1>100.0</Cota1>\n"
            b"    </SerieHistorica>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_conventional(xml, "1")
        assert result is not None
        assert "Cota" in result.columns

    def test_conventional_vazao(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <SerieHistorica diffgr:id="SerieHistorica1" msdata:rowOrder="0">\n'
            b"      <DataHora>2024-01-01T00:00:00</DataHora>\n"
            b"      <NivelConsistencia>1</NivelConsistencia>\n"
            b"      <Vazao1>50.0</Vazao1>\n"
            b"    </SerieHistorica>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_conventional(xml, "3")
        assert result is not None
        assert "Vazao" in result.columns

    def test_conventional_sem_coluna_dado(self):
        xml = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">\n'
            b"  <NewDataSet>\n"
            b'    <SerieHistorica diffgr:id="SerieHistorica1" msdata:rowOrder="0">\n'
            b"      <DataHora>2024-01-01T00:00:00</DataHora>\n"
            b"      <NivelConsistencia>1</NivelConsistencia>\n"
            b"    </SerieHistorica>\n"
            b"  </NewDataSet>\n"
            b"</diffgr:diffgram>"
        )
        result = parse_conventional(xml, "2")
        assert result is None
