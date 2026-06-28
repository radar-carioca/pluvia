from dataclasses import dataclass

from shapely.geometry import Polygon

from pluvia.infrastructure.spatial import SpatialExtent


@dataclass
class _MockStation:
    latitude: float
    longitude: float


class TestSpatialExtent:
    def test_filter(self):
        poly = Polygon([(-50, -25), (-40, -25), (-40, -20), (-50, -20)])
        extent = SpatialExtent(poly)
        inside = [_MockStation(-23, -46), _MockStation(-22, -45)]
        outside = [_MockStation(-10, -60)]
        result = extent.filter(inside + outside)
        assert len(result) == 2
        assert result == inside

    def test_filter_empty(self):
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        extent = SpatialExtent(poly)
        assert extent.filter([]) == []

    def test_from_polygon(self):
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        extent = SpatialExtent(poly)
        inside = [_MockStation(5, 5)]
        outside = [_MockStation(20, 20)]
        assert len(extent.filter(inside)) == 1
        assert len(extent.filter(outside)) == 0
