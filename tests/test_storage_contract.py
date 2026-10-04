"""
Storage contract tests.

The invariant under test: a path returned by `StorageAdapter` always refers to a file that
exists, and the sidecar metadata names that same file. An earlier version wrote a `.npy`
array but recorded a `.tif` name, which handed callers a path to a file that was never
created and silently discarded the raster.
"""

import json

import numpy as np
import pytest

from satguard.geospatial.raster import GeoTransform
from satguard.processing.storage import StorageAdapter

CRS = "EPSG:32644"


def _transform(height: int = 8, width: int = 8) -> GeoTransform:
    return GeoTransform.from_bounds((500000.0, 3100000.0, 500800.0, 3100800.0), width, height)


def test_georeferenced_write_returns_an_existing_geotiff(tmp_path):
    storage = StorageAdapter(base_dir=tmp_path)
    array = np.arange(64, dtype="float32").reshape(8, 8)

    path = storage._write_raster(tmp_path, "ndwi_obs.tif", array, _transform(), CRS,
                                 nodata=-9999.0)

    assert path.endswith(".tif")
    assert (tmp_path / "ndwi_obs.tif").exists()

    meta = json.loads((tmp_path / "ndwi_obs.json").read_text())
    assert meta["file"] == "ndwi_obs.tif"
    assert meta["georeferenced"] is True
    assert meta["crs"] == CRS


def test_ungeoreferenced_write_returns_an_existing_file_not_a_missing_geotiff(tmp_path):
    """Without a transform the array is saved as .npy; the returned path must match."""
    storage = StorageAdapter(base_dir=tmp_path)
    array = np.arange(16, dtype="float32").reshape(4, 4)

    path = storage._write_raster(tmp_path, "ndwi_obs.tif", array, None, CRS)

    from pathlib import Path

    returned = Path(path)
    assert returned.exists(), f"returned path does not exist: {returned}"
    assert returned.suffix == ".npy"
    assert not returned.with_suffix(".tif").exists(), "no .tif should be claimed"

    # The saved array round-trips with its original values.
    assert np.allclose(np.load(returned), array)

    meta = json.loads((tmp_path / "ndwi_obs.json").read_text())
    assert meta["file"] == returned.name
    assert meta["georeferenced"] is False
    assert meta["crs"] is None
    assert "georeferencing" in meta["warning"]
    assert "raster" not in meta


@pytest.mark.parametrize("filename", ["change_a_vs_b.tif", "quicklook_rgb.tif"])
def test_every_returned_path_exists_regardless_of_filename(tmp_path, filename):
    storage = StorageAdapter(base_dir=tmp_path)
    array = np.random.default_rng(0).random((6, 6)).astype("float32")
    transform = _transform(6, 6)

    path = storage._write_raster(tmp_path, filename, array, transform, CRS)

    from pathlib import Path

    assert Path(path).exists()
    assert json.loads(Path(path).with_suffix(".json").read_text())["file"] == Path(path).name