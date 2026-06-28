from pluvia.domain.entities import Station


class TestStation:
    def test_create_station(self):
        s = Station(
            code="123",
            name="Teste",
            latitude=-23.5,
            longitude=-46.6,
            station_type="fluviometrica",
        )
        assert s.code == "123"
        assert s.name == "Teste"

    def test_hash_by_code(self):
        s1 = Station(
            code="123", name="A", latitude=0, longitude=0, station_type="fluviometrica"
        )
        s2 = Station(
            code="123", name="B", latitude=0, longitude=0, station_type="fluviometrica"
        )
        assert hash(s1) == hash(s2)

    def test_with_optional_fields(self):
        s = Station(
            code="456",
            name="Rio",
            latitude=-22,
            longitude=-44,
            station_type="pluviometrica",
            state="SP",
            municipality="Sao Paulo",
            basin="1",
            river="Tiete",
        )
        assert s.state == "SP"
        assert s.river == "Tiete"
