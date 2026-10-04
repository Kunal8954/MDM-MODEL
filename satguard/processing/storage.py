"""
satguard/processing/storage.py
Configurable object and local storage adapter for SATGUARD.
Organizes large raster artifacts, NDWI GeoTIFF arrays, difference masks, and quicklooks.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np
import tifffile

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class StorageAdapter:
    """
    Manages structured file and object storage hierarchy:
    satguard/locations/{location_id}/observations/{observation_id}/
    satguard/locations/{location_id}/derived/ndwi/
    satguard/locations/{location_id}/derived/change/
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

    def save_ndwi_raster(
        self,
        location_id: str,
        observation_id: str,
        ndwi_array: np.ndarray,
    ) -> str:
        """
        Saves a 2D float32 NDWI array as a GeoTIFF.
        """
        out_dir = self.get_derived_ndwi_dir(location_id)
        filename = f"ndwi_{observation_id}.tif"
        out_path = out_dir / filename

        # Write float32 raster
        tifffile.imwrite(str(out_path), ndwi_array.astype(np.float32))
        return str(out_path)

    def save_sar_raster(
        self,
        location_id: str,
        observation_id: str,
        vv_db: np.ndarray,
        vh_db: np.ndarray,
    ) -> str:
        """
        Saves calibrated 2-band float32 SAR backscatter GeoTIFF (Band 1: VV dB, Band 2: VH dB).
        """
        out_dir = self.get_derived_sar_dir(location_id)
        filename = f"sar_{observation_id}.tif"
        out_path = out_dir / filename

        stacked = np.stack([vv_db.astype(np.float32), vh_db.astype(np.float32)], axis=0)
        tifffile.imwrite(str(out_path), stacked)
        return str(out_path)

    def save_change_mask(
        self,
        location_id: str,
        baseline_id: str,
        current_id: str,
        change_mask: np.ndarray,
    ) -> str:
        """
        Saves the difference mask array as GeoTIFF.
        """
        out_dir = self.get_derived_change_dir(location_id)
        filename = f"change_{current_id}_vs_{baseline_id}.tif"
        out_path = out_dir / filename

        tifffile.imwrite(str(out_path), change_mask.astype(np.float32))
        return str(out_path)

    def save_sar_change_mask(
        self,
        location_id: str,
        baseline_id: str,
        current_id: str,
        delta_vv_db: np.ndarray,
    ) -> str:
        """
        Saves the differential SAR backscatter delta mask as GeoTIFF.
        """
        out_dir = self.get_derived_change_dir(location_id)
        filename = f"sar_delta_{current_id}_vs_{baseline_id}.tif"
        out_path = out_dir / filename

        tifffile.imwrite(str(out_path), delta_vv_db.astype(np.float32))
        return str(out_path)


storage = StorageAdapter()
