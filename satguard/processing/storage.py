"""
satguard/processing/storage.py
Configurable object and local storage adapter for SATGUARD.

Georeferencing contract:
    Derived rasters are written as true GeoTIFFs via
    :func:`satguard.geospatial.raster.write_geotiff`, so the affine transform and CRS
    are persisted and pixel indices remain convertible to geographic coordinates.

    The previous implementation used ``tifffile.imwrite`` with no transform, producing
    files that carried no georeferencing at all. Callers may still omit the transform,
    but the artifact is then explicitly recorded as ungeoreferenced so it can never be
    mistaken for a map-registered product.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np

from satguard.geospatial.raster import (
    GEOGRAPHIC_CRS,
    GeoTransform,
    RasterProfile,
    write_geotiff,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class StorageAdapter:
    """
    Manages a structured artifact hierarchy::

        storage/satguard/locations/{location_id}/
            observations/{observation_id}/
            derived/ndwi/
            derived/change/
            derived/sar/
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or (PROJECT_ROOT / "storage" / "satguard")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_location_dir(self, location_id: str) -> Path:
        p = self.base_dir / "locations" / location_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_observation_dir(self, location_id: str, observation_id: str) -> Path:
        p = self._get_location_dir(location_id) / "observations" / observation_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_derived_ndwi_dir(self, location_id: str) -> Path:
        p = self._get_location_dir(location_id) / "derived" / "ndwi"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_derived_change_dir(self, location_id: str) -> Path:
        p = self._get_location_dir(location_id) / "derived" / "change"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_derived_sar_dir(self, location_id: str) -> Path:
        p = self._get_location_dir(location_id) / "derived" / "sar"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _write_raster(
        self,
        out_dir: Path,
        filename: str,
        array: np.ndarray,
        transform: Optional[GeoTransform],
        crs: str,
        nodata: Optional[float] = None,
        band_names: Optional[Sequence[str]] = None,
        sidecar_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Write a raster plus a JSON sidecar describing its georeferencing.

        The sidecar makes the georeferencing explicit and machine-readable even for
        artifacts produced before a transform was available.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        arr = np.asarray(array)
        georeferenced = transform is not None

        if georeferenced:
            write_geotiff(
                out_path,
                arr,
                transform,  # type: ignore[arg-type]
                crs=crs,
                nodata=nodata,
                band_names=band_names,
            )
        else:
            # No transform available: write the raw array and mark it ungeoreferenced.
            # Callers must not treat this artifact as map-registered. The extension changes
            # to .npy and every recorded path below follows it, so a returned path always
            # refers to a file that exists rather than a .tif that was never written.
            written_path = out_path.with_suffix(".npy")
            np.save(written_path, arr)
            out_path = written_path

        meta: Dict[str, Any] = {
            "file": out_path.name,
            "shape": list(arr.shape),
            "dtype": str(arr.dtype),
            "georeferenced": georeferenced,
            "crs": crs if georeferenced else None,
        }
        if georeferenced:
            prof = RasterProfile(
                array=arr,
                transform=transform,  # type: ignore[arg-type]
                crs=crs,
                nodata=nodata,
                band_names=band_names,
            )
            meta["raster"] = prof.to_dict()
        else:
            meta["warning"] = (
                "Written without georeferencing; pixel coordinates cannot be "
                "converted to geographic coordinates."
            )
        if sidecar_meta:
            meta.update(sidecar_meta)

        with open(out_path.with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, default=str)

        return str(out_path)

    # ------------------------------------------------------------------
    # optical products
    # ------------------------------------------------------------------

    def save_ndwi_raster(
        self,
        location_id: str,
        observation_id: str,
        ndwi_array: np.ndarray,
        transform: Optional[GeoTransform] = None,
        crs: str = GEOGRAPHIC_CRS,
        nodata: Optional[float] = None,
    ) -> str:
        """Save a 2D NDWI array as a georeferenced GeoTIFF."""
        return self._write_raster(
            self.get_derived_ndwi_dir(location_id),
            f"ndwi_{observation_id}.tif",
            ndwi_array,
            transform,
            crs,
            nodata=nodata,
            band_names=["NDWI"],
        )

    def save_change_mask(
        self,
        location_id: str,
        baseline_id: str,
        current_id: str,
        change_mask: np.ndarray,
        transform: Optional[GeoTransform] = None,
        crs: str = GEOGRAPHIC_CRS,
        nodata: Optional[float] = None,
    ) -> str:
        """Save a difference mask as a georeferenced GeoTIFF."""
        return self._write_raster(
            self.get_derived_change_dir(location_id),
            f"change_{current_id}_vs_{baseline_id}.tif",
            change_mask,
            transform,
            crs,
            nodata=nodata,
            band_names=["DELTA_NDWI"],
        )

    # ------------------------------------------------------------------
    # SAR products
    # ------------------------------------------------------------------

    def save_sar_raster(
        self,
        location_id: str,
        observation_id: str,
        vv_db: np.ndarray,
        vh_db: np.ndarray,
        transform: Optional[GeoTransform] = None,
        crs: str = GEOGRAPHIC_CRS,
        nodata: Optional[float] = None,
    ) -> str:
        """
        Save calibrated dual-polarization backscatter.

        Band 1 = VV (dB), Band 2 = VH (dB).
        """
        stacked = np.stack(
            [np.asarray(vv_db, dtype=np.float32), np.asarray(vh_db, dtype=np.float32)],
            axis=-1,
        )
        return self._write_raster(
            self.get_derived_sar_dir(location_id),
            f"sar_{observation_id}.tif",
            stacked,
            transform,
            crs,
            nodata=nodata,
            band_names=["VV_dB", "VH_dB"],
        )

    def save_sar_change_mask(
        self,
        location_id: str,
        baseline_id: str,
        current_id: str,
        delta_vv_db: np.ndarray,
        transform: Optional[GeoTransform] = None,
        crs: str = GEOGRAPHIC_CRS,
        nodata: Optional[float] = None,
    ) -> str:
        """Save the differential VV backscatter mask as a georeferenced GeoTIFF."""
        return self._write_raster(
            self.get_derived_change_dir(location_id),
            f"sar_delta_{current_id}_vs_{baseline_id}.tif",
            delta_vv_db,
            transform,
            crs,
            nodata=nodata,
            band_names=["DELTA_VV_dB"],
        )

    # ------------------------------------------------------------------
    # quicklook products (for before/after visual inspection)
    # ------------------------------------------------------------------

    def save_quicklook_rgb(
        self,
        location_id: str,
        observation_id: str,
        rgb: np.ndarray,
        transform: Optional[GeoTransform] = None,
        crs: str = GEOGRAPHIC_CRS,
        kind: str = "rgb",
    ) -> str:
        """Save an 8-bit RGB quicklook (bands ordered R, G, B)."""
        arr = np.asarray(rgb)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError(f"RGB quicklook requires (h, w, 3), got {arr.shape}")
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        return self._write_raster(
            self.get_observation_dir(location_id, observation_id),
            f"{kind}_{observation_id}.tif",
            arr,
            transform,
            crs,
            nodata=None,
            band_names=["R", "G", "B"],
        )

    # ------------------------------------------------------------------
    # metadata sidecars
    # ------------------------------------------------------------------

    def write_sidecar(
        self,
        directory: Path,
        filename: str,
        payload: Dict[str, Any],
    ) -> str:
        """Write a JSON sidecar describing an artifact or processing step."""
        directory.mkdir(parents=True, exist_ok=True)
        out_path = directory / filename
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        return str(out_path)

    def read_sidecar(self, raster_path: str | Path) -> Optional[Dict[str, Any]]:
        """Read the JSON sidecar associated with a raster artifact, if present."""
        sidecar = Path(raster_path).with_suffix(".json")
        if not sidecar.exists():
            return None
        try:
            with open(sidecar, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None


storage = StorageAdapter()