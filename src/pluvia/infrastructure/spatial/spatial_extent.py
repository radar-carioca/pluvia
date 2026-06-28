"""Spatial extent representation and file-based filtering."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

_SUPPORTED = {".shp", ".gpkg", ".geojson"}


class SpatialExtent:
    """A spatial region defined by a Shapely geometry.

    Parameters
    ----------
    geometry : BaseGeometry or GeoDataFrame or GeoSeries
        The input geometry (multiple features are unioned).
    crs : str, optional
        Coordinate reference system, by default ``"EPSG:4326"``.
    """

    def __init__(self, geometry, crs: str = "EPSG:4326"):
        if isinstance(geometry, gpd.GeoDataFrame | gpd.GeoSeries):
            geometry = geometry.union_all()
        self._geometry = geometry
        self._crs = crs

    @classmethod
    def from_file(
        cls, path: str, column: str | None = None, value=None
    ) -> SpatialExtent:
        """Create a SpatialExtent from a vector file.

        Parameters
        ----------
        path : str
            Path to .shp, .gpkg, or .geojson file.
        column : str or None, optional
            Attribute column to filter by.
        value : any, optional
            Desired value for the column filter.

        Returns
        -------
        SpatialExtent
        """
        ext = Path(path).suffix.lower()
        if ext not in _SUPPORTED:
            raise ValueError(
                f"Unsupported format '{ext}'. Supported: {sorted(_SUPPORTED)}"
            )
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise ValueError(f"File {path} has no CRS defined.")
        crs = gdf.crs.to_string()
        if column is not None and value is not None:
            gdf = gdf[gdf[column] == value]
        return cls(gdf, crs=crs)

    def filter(self, stations: list) -> list:
        """Filter a list of Station-like objects by spatial extent.

        All points are transformed in a single CRS reprojection,
        orders of magnitude faster than point-by-point checking.

        Parameters
        ----------
        stations : list[Station]
            Each item must have ``.latitude`` and ``.longitude``.

        Returns
        -------
        list[Station]
        """
        if not stations:
            return []

        import numpy as np

        lats = np.array([s.latitude for s in stations])
        lons = np.array([s.longitude for s in stations])

        pts = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries(
                [Point(x, y) for x, y in zip(lons, lats, strict=True)], crs="EPSG:4326"
            ),
        )
        mask = pts.to_crs(self._crs).within(self._geometry).values
        return [s for s, keep in zip(stations, mask, strict=True) if keep]

    @property
    def geometry(self):
        """The underlying Shapely geometry."""
        return self._geometry
