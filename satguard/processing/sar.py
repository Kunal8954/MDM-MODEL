"""
satguard/processing/sar.py
Sentinel-1 SAR Processing and Differential Temporal Change Detection Pipeline.
Implements:
- Phase 2.3: SAR Preprocessing (validation, AOI masking, radiometric representation)
- Phase 2.4: Dual-Polarization (VV + VH) Backscatter Extraction in Decibels (dB)
- Phase 2.5: Temporal T1 vs T2 Comparison with Acquisition Geometry & Orbit Validation
- Phase 2.6: Spatial SAR Change Map Generation, Thresholding, and Connected Change Regions
- Phase 2.7: Database Persistence & Manifest Auditing
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, timezone

import numpy as np
import tifffile
import scipy.ndimage
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.db.session import get_db_session
from satguard.models.entities import (
    CriticalLocation,
    SatelliteObservation,
    Sentinel1ProcessingResult,
    Sentinel1ChangeDetection,
)
from satguard.geospatial.aoi import create_circular_aoi
from satguard.ingestion.sentinel1_retrieval import retrieve_sentinel1_observation

logger = logging.getLogger("satguard.processing.sar")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "sentinel1"


class SARValidationError(Exception):
    """Raised when SAR raster fails source validation."""
    pass


class IncompatibleGeometryError(Exception):
    """Raised when comparing observations with incompatible orbit geometry."""
    pass


class CalibratedResult(tuple):
    """
    Tuple containing (db_array, unit_str).
    Provides ndarray-like access for backwards compatibility with Phase 1 tests and pipeline.
    """
    def __new__(cls, array: np.ndarray, unit: str = "dB"):
        return super().__new__(cls, (array, unit))

    @property
    def array(self) -> np.ndarray:
        return self[0]

    @property
    def unit(self) -> str:
        return self[1]

    def __array__(self, dtype=None):
        return np.asarray(self[0], dtype=dtype)

    def __getitem__(self, item):
        if isinstance(item, tuple):
            return self[0][item]
        return super().__getitem__(item)

    def astype(self, dtype):
        return self[0].astype(dtype)

    @property
    def shape(self):
        return self[0].shape

    @property
    def dtype(self):
        return self[0].dtype


class SARProcessor:
    """
    Core scientific processing engine for Sentinel-1 C-Band SAR observations.
    Computes calibrated backscatter (dB), extracts VV/VH, and generates
    differential temporal change products with connected component region analysis.
    """

    def __init__(
        self,
        vv_change_threshold_db: float = 3.0,
        vh_change_threshold_db: float = 3.0,
        pixel_resolution_m: float = 10.0,
        base_storage_dir: Optional[Path] = None,
        change_threshold_db: Optional[float] = None,
    ):
        if change_threshold_db is not None:
            vv_change_threshold_db = change_threshold_db
            vh_change_threshold_db = change_threshold_db
        self.vv_change_threshold_db = vv_change_threshold_db
        self.vh_change_threshold_db = vh_change_threshold_db
        self.pixel_resolution_m = pixel_resolution_m
        self.pixel_area_m2 = pixel_resolution_m * pixel_resolution_m
        self.base_storage_dir = Path(base_storage_dir or DEFAULT_DATA_DIR)
        self.base_storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 2.3.1 SOURCE VALIDATION
    # ------------------------------------------------------------------
    def validate_sar_raster(self, raster_path: Path) -> Dict[str, Any]:
        """
        Validates the downloaded Sentinel-1 SAR raster file.
        Ensures file exists, size > 0, readable, and contains at least 2 bands (VV, VH).
        """
        if not raster_path.exists():
            raise SARValidationError(f"SAR raster file does not exist: {raster_path}")

        file_size = raster_path.stat().st_size
        if file_size == 0:
            raise SARValidationError(f"SAR raster file is empty (0 bytes): {raster_path}")

        try:
            arr = tifffile.imread(str(raster_path))
        except Exception as e:
            raise SARValidationError(f"Failed to read SAR raster with tifffile ({raster_path}): {e}")

        # Standardize array shape to (H, W, Bands)
        if arr.ndim == 2:
            raise SARValidationError(f"Expected at least 2 bands (VV, VH), got 1 band (shape {arr.shape})")
        elif arr.ndim == 3:
            if arr.shape[0] in (2, 3) and arr.shape[2] not in (2, 3):
                # Shape is (Bands, H, W) -> transpose to (H, W, Bands)
                arr = np.transpose(arr, (1, 2, 0))

        height, width, bands = arr.shape
        if bands < 2:
            raise SARValidationError(f"Expected at least 2 bands (VV, VH), found {bands}")

        # Check for NaN / Inf
        nan_count = int(np.isnan(arr).sum())
        inf_count = int(np.isinf(arr).sum())

        return {
            "valid": True,
            "dimensions": {"height": height, "width": width, "bands": bands},
            "file_size_bytes": file_size,
            "nan_count": nan_count,
            "inf_count": inf_count,
            "array": arr.astype(np.float32),
        }

    # ------------------------------------------------------------------
    # 2.3.3 AOI MASKING
    # ------------------------------------------------------------------
    def create_aoi_mask(self, height: int, width: int) -> np.ndarray:
        """
        Creates a circular binary mask for the monitored critical location AOI.
        Pixels inside circle are True, outside are False.
        """
        center_y = (height - 1) / 2.0
        center_x = (width - 1) / 2.0
        radius_y = height / 2.0
        radius_x = width / 2.0

        y_indices, x_indices = np.ogrid[:height, :width]
        norm_dist_sq = ((y_indices - center_y) / radius_y) ** 2 + ((x_indices - center_x) / radius_x) ** 2
        return norm_dist_sq <= 1.0

    # ------------------------------------------------------------------
    # 2.3.6 RADIOMETRIC REPRESENTATION (DECIBEL CONVERSION)
    # ------------------------------------------------------------------
    def calibrate_to_db(self, array: np.ndarray) -> CalibratedResult:
        """
        Converts linear radar backscatter power/amplitude to logarithmic decibel (dB) scale.
        If values are already in dB (e.g. median < 0 and min < -5), preserves them without double conversion.
        """
        valid_vals = array[np.isfinite(array)]
        if valid_vals.size > 0:
            median_val = float(np.median(valid_vals))
            min_val = float(np.min(valid_vals))
            # Already in dB check: dB values for SAR are typically in range -40 dB to +5 dB
            if median_val < 0.0 and min_val < -5.0:
                logger.info("SAR array is already in decibels (dB); preserving input representation.")
                return CalibratedResult(array.copy(), "dB")

        epsilon = 1e-7
        clipped = np.maximum(array, epsilon)
        db_array = 10.0 * np.log10(clipped)
        return CalibratedResult(db_array, "dB")

    # ------------------------------------------------------------------
    # 2.3.8 OPTIONAL SPECKLE FILTERING
    # ------------------------------------------------------------------
    def apply_speckle_filter(
        self,
        array_2d: np.ndarray,
        filter_name: Optional[str] = None,
    ) -> np.ndarray:
        """
        Applies optional speckle filtering. Defaults to None to preserve fine structural changes.
        Supported options: 'box_3x3', 'median_3x3'.
        """
        if not filter_name or filter_name == "none":
            return array_2d

        nan_mask = np.isnan(array_2d)
        filled = np.nan_to_num(array_2d, nan=0.0)

        if filter_name == "box_3x3":
            filtered = scipy.ndimage.uniform_filter(filled, size=3)
        elif filter_name == "median_3x3":
            filtered = scipy.ndimage.median_filter(filled, size=3)
        else:
            logger.warning(f"Unknown speckle filter '{filter_name}'; passing through unchanged.")
            return array_2d

        filtered[nan_mask] = np.nan
        return filtered

    # ------------------------------------------------------------------
    # 2.4.4 BACKSCATTER STATISTICS
    # ------------------------------------------------------------------
    def calculate_band_statistics(
        self,
        band_array_db: np.ndarray,
        mask: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Calculates robust descriptive statistics for a SAR backscatter band in decibels (dB).
        """
        valid_condition = np.isfinite(band_array_db)
        if mask is not None:
            valid_condition = valid_condition & mask

        valid_values = band_array_db[valid_condition]
        valid_count = int(valid_values.size)

        if valid_count == 0:
            return {
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "median": 0.0,
                "std": 0.0,
                "valid_pixel_count": 0,
            }

        return {
            "min": round(float(np.min(valid_values)), 4),
            "max": round(float(np.max(valid_values)), 4),
            "mean": round(float(np.mean(valid_values)), 4),
            "median": round(float(np.median(valid_values)), 4),
            "std": round(float(np.std(valid_values)), 4),
            "valid_pixel_count": valid_count,
        }

    # ------------------------------------------------------------------
    # PHASE 2.3 & 2.4: PREPROCESSING WORKFLOW
    # ------------------------------------------------------------------
    def preprocess_observation(
        self,
        observation_id: str,
        db: Session,
        speckle_filter: Optional[str] = None,
        force_reprocess: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end preprocessing for a single Sentinel-1 SAR observation:
        1. Validates source raster
        2. Applies AOI masking
        3. Converts VV and VH to decibels (dB)
        4. Calculates backscatter statistics
        5. Persists derived analysis rasters and metadata
        """
        # 1. Load observation from DB
        obs = db.query(SatelliteObservation).filter(SatelliteObservation.id == observation_id).first()
        if not obs:
            raise SARValidationError(f"Observation '{observation_id}' not found in database.")

        location_id = obs.location_id
        product_id = obs.product_id

        # Deterministic output directory
        proc_dir = self.base_storage_dir / location_id / observation_id / "processed"
        proc_dir.mkdir(parents=True, exist_ok=True)
        vv_path = proc_dir / "vv_db.tif"
        vh_path = proc_dir / "vh_db.tif"
        manifest_path = proc_dir / "manifest.json"

        # Idempotency check
        if not force_reprocess and vv_path.exists() and vh_path.exists() and manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                logger.info(f"Observation {observation_id} already preprocessed. Returning cached result.")
                return {
                    "location_id": location_id,
                    "observation_id": observation_id,
                    "product_id": product_id,
                    "status": "ALREADY_PROCESSED",
                    "vv_raster": str(vv_path),
                    "vh_raster": str(vh_path),
                    "vv_mean_db": manifest_data["vv_statistics"]["mean"],
                    "vh_mean_db": manifest_data["vh_statistics"]["mean"],
                    "vv_statistics": manifest_data["vv_statistics"],
                    "vh_statistics": manifest_data["vh_statistics"],
                    "manifest": manifest_data,
                }
            except Exception:
                logger.warning(f"Corrupt processed manifest at {manifest_path}; re-processing.")

        # Ensure raw raster is retrieved
        raw_raster_path = None
        if obs.raster_artifact_path and Path(obs.raster_artifact_path).exists():
            raw_raster_path = Path(obs.raster_artifact_path)
        else:
            expected_raw = self.base_storage_dir / location_id / observation_id / f"sentinel1_grd_{product_id}.tif"
            if expected_raw.exists():
                raw_raster_path = expected_raw
            else:
                logger.info(f"Raw SAR data for {observation_id} not found locally; triggering retrieval.")
                retrieval_res = retrieve_sentinel1_observation(observation_id=observation_id, db=db)
                raw_raster_path = Path(retrieval_res["storage_path"])

        # 2. Source Validation
        val_res = self.validate_sar_raster(raw_raster_path)
        arr = val_res["array"]
        height, width, _ = arr.shape

        # 3. Separate VV and VH bands
        vv_raw = arr[:, :, 0]
        vh_raw = arr[:, :, 1]

        # 4. Decibel conversion
        vv_db, vv_unit = self.calibrate_to_db(vv_raw)
        vh_db, vh_unit = self.calibrate_to_db(vh_raw)

        # 5. Optional speckle filtering
        if speckle_filter:
            vv_db = self.apply_speckle_filter(vv_db, speckle_filter)
            vh_db = self.apply_speckle_filter(vh_db, speckle_filter)

        # 6. Apply AOI mask
        aoi_mask = self.create_aoi_mask(height, width)
        vv_db_masked = np.where(aoi_mask, vv_db, np.nan)
        vh_db_masked = np.where(aoi_mask, vh_db, np.nan)

        # 7. Compute statistics
        vv_stats = self.calculate_band_statistics(vv_db, aoi_mask)
        vh_stats = self.calculate_band_statistics(vh_db, aoi_mask)

        # 8. Save derived analysis GeoTIFFs
        tifffile.imwrite(str(vv_path), vv_db_masked.astype(np.float32))
        tifffile.imwrite(str(vh_path), vh_db_masked.astype(np.float32))

        # 9. Extract STAC/orbit metadata from observation
        orbit_dir = None
        rel_orbit = None
        try:
            raw_meta = json.loads(obs.raw_metadata) if obs.raw_metadata else {}
            orbit_dir = raw_meta.get("orbit_direction")
            rel_orbit = raw_meta.get("relative_orbit")
        except Exception:
            raw_meta = {}

        # 10. Generate manifest
        manifest = {
            "location_id": location_id,
            "observation_id": observation_id,
            "product_id": product_id,
            "mission": "Sentinel-1",
            "instrument_mode": "IW",
            "polarizations": ["VV", "VH"],
            "orbit_direction": orbit_dir,
            "relative_orbit": rel_orbit,
            "acquisition_time": obs.acquisition_time.isoformat(),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "source_raster_path": str(raw_raster_path),
            "vv_raster_path": str(vv_path),
            "vh_raster_path": str(vh_path),
            "vv_unit": vv_unit,
            "vh_unit": vh_unit,
            "vv_statistics": vv_stats,
            "vh_statistics": vh_stats,
            "speckle_filter": speckle_filter or "none",
            "processing_version": "1.0.0",
            "dimensions": {"height": height, "width": width},
            "status": "SUCCESS",
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # 11. Persist processing record in database
        proc_record = Sentinel1ProcessingResult(
            id=f"proc-s1-{observation_id}",
            location_id=location_id,
            observation_id=observation_id,
            product_id=product_id,
            acquisition_time=obs.acquisition_time,
            vv_statistics=json.dumps(vv_stats),
            vh_statistics=json.dumps(vh_stats),
            vv_raster_path=str(vv_path),
            vh_raster_path=str(vh_path),
            processing_version="1.0.0",
            status="SUCCESS",
        )
        db.merge(proc_record)
        obs.processing_time = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"Successfully preprocessed observation {observation_id}: "
            f"VV mean={vv_stats['mean']} dB, VH mean={vh_stats['mean']} dB"
        )

        return {
            "location_id": location_id,
            "observation_id": observation_id,
            "product_id": product_id,
            "status": "SUCCESS",
            "vv_raster": str(vv_path),
            "vh_raster": str(vh_path),
            "vv_mean_db": vv_stats["mean"],
            "vh_mean_db": vh_stats["mean"],
            "vv_statistics": vv_stats,
            "vh_statistics": vh_stats,
            "manifest": manifest,
        }

    # ------------------------------------------------------------------
    # PHASE 2.5 & 2.6: TEMPORAL COMPARISON & CHANGE MAP GENERATION
    # ------------------------------------------------------------------
    def detect_connected_change_regions(
        self,
        change_mask: np.ndarray,
        min_pixels: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Identifies spatially contiguous clusters of significant backscatter change.
        Formally designated as 'SIGNIFICANT SAR CHANGE REGIONS'.
        """
        # Binary mask of any significant change (values >= 2: VV_CHANGE, VH_CHANGE, or VV_AND_VH_CHANGE)
        binary_mask = (change_mask >= 2).astype(np.uint8)
        labeled_array, num_features = scipy.ndimage.label(binary_mask)

        regions: List[Dict[str, Any]] = []
        if num_features == 0:
            return regions

        for feature_id in range(1, num_features + 1):
            region_indices = np.argwhere(labeled_array == feature_id)
            pixel_count = int(len(region_indices))
            if pixel_count < min_pixels:
                continue

            area_m2 = pixel_count * self.pixel_area_m2
            min_r, min_c = np.min(region_indices, axis=0)
            max_r, max_c = np.max(region_indices, axis=0)
            centroid_r, centroid_c = np.mean(region_indices, axis=0)

            regions.append({
                "region_id": feature_id,
                "designation": "SIGNIFICANT_SAR_CHANGE_REGION",
                "pixel_count": pixel_count,
                "area_m2": round(area_m2, 2),
                "centroid": [round(float(centroid_r), 2), round(float(centroid_c), 2)],
                "bounding_box": [int(min_r), int(min_c), int(max_r), int(max_c)],
            })

        # Sort largest region first
        regions.sort(key=lambda r: r["area_m2"], reverse=True)
        return regions

    def compare_observations(
        self,
        location_id: str,
        db: Session,
        t1_observation_id: Optional[str] = None,
        t2_observation_id: Optional[str] = None,
        vv_threshold_db: Optional[float] = None,
        vh_threshold_db: Optional[float] = None,
        allow_cross_orbit: bool = False,
        force_reprocess: bool = False,
    ) -> Dict[str, Any]:
        """
        Performs dual-temporal SAR change detection between T1 and T2:
        1. Selects dynamic T1 and T2 if not supplied
        2. Validates orbit and acquisition geometry
        3. Computes ΔVV = VV(T2) - VV(T1) and ΔVH = VH(T2) - VH(T1) in dB
        4. Generates classified 5-class change mask
        5. Extracts connected change regions
        6. Persists change records and manifest
        """
        th_vv = vv_threshold_db or self.vv_change_threshold_db
        th_vh = vh_threshold_db or self.vh_change_threshold_db

        # 1. Resolve T2 (latest valid processed observation)
        if t2_observation_id:
            t2_obs = db.query(SatelliteObservation).filter(
                SatelliteObservation.id == t2_observation_id,
                SatelliteObservation.location_id == location_id,
            ).first()
        else:
            t2_obs = (
                db.query(SatelliteObservation)
                .filter(
                    SatelliteObservation.location_id == location_id,
                    SatelliteObservation.sensor == "SAR-C",
                )
                .order_by(SatelliteObservation.acquisition_time.desc())
                .first()
            )

        if not t2_obs:
            return {
                "location_id": location_id,
                "status": "INSUFFICIENT_DATA",
                "message": "No Sentinel-1 observations available for this location.",
            }

        # 2. Resolve T1 (previous compatible observation)
        if t1_observation_id:
            t1_obs = db.query(SatelliteObservation).filter(
                SatelliteObservation.id == t1_observation_id,
                SatelliteObservation.location_id == location_id,
            ).first()
        else:
            # Parse T2 orbit direction for geometry matching preference
            t2_orbit_dir = None
            try:
                t2_meta = json.loads(t2_obs.raw_metadata) if t2_obs.raw_metadata else {}
                t2_orbit_dir = t2_meta.get("orbit_direction")
            except Exception:
                t2_meta = {}

            # Query observations strictly prior to T2
            prior_query = (
                db.query(SatelliteObservation)
                .filter(
                    SatelliteObservation.location_id == location_id,
                    SatelliteObservation.sensor == "SAR-C",
                    SatelliteObservation.acquisition_time < t2_obs.acquisition_time,
                    SatelliteObservation.id != t2_obs.id,
                )
                .order_by(SatelliteObservation.acquisition_time.desc())
            )
            prior_all = prior_query.all()

            # Prefer same orbit direction
            t1_obs = None
            if t2_orbit_dir:
                for cand in prior_all:
                    try:
                        cand_meta = json.loads(cand.raw_metadata) if cand.raw_metadata else {}
                        if cand_meta.get("orbit_direction") == t2_orbit_dir:
                            t1_obs = cand
                            break
                    except Exception:
                        pass

            if not t1_obs and prior_all:
                t1_obs = prior_all[0]

        if not t1_obs:
            return {
                "location_id": location_id,
                "status": "INSUFFICIENT_DATA",
                "message": "Need at least two temporal Sentinel-1 observations for comparison.",
                "t2": {"observation_id": t2_obs.id, "acquisition_time": t2_obs.acquisition_time.isoformat()},
            }

        # Parse orbit metadata
        try:
            t1_meta = json.loads(t1_obs.raw_metadata) if t1_obs.raw_metadata else {}
        except Exception:
            t1_meta = {}
        try:
            t2_meta = json.loads(t2_obs.raw_metadata) if t2_obs.raw_metadata else {}
        except Exception:
            t2_meta = {}

        t1_orbit = t1_meta.get("orbit_direction")
        t2_orbit = t2_meta.get("orbit_direction")
        t1_rel_orbit = t1_meta.get("relative_orbit")
        t2_rel_orbit = t2_meta.get("relative_orbit")

        # 3. Geometry & Orbit Compatibility Check (Phase 2.5.4)
        if not allow_cross_orbit and t1_orbit and t2_orbit:
            if t1_orbit.upper() != t2_orbit.upper():
                logger.warning(
                    f"Incompatible orbit geometry: T1 is {t1_orbit} (orbit {t1_rel_orbit}), "
                    f"T2 is {t2_orbit} (orbit {t2_rel_orbit}). Refusing misleading subtraction."
                )
                return {
                    "location_id": location_id,
                    "status": "INCOMPATIBLE_GEOMETRY",
                    "message": (
                        f"Incompatible acquisition geometry: T1 is {t1_orbit} (relative orbit {t1_rel_orbit}), "
                        f"T2 is {t2_orbit} (relative orbit {t2_rel_orbit}). Same orbit geometry required."
                    ),
                    "t1": {
                        "observation_id": t1_obs.id,
                        "product_id": t1_obs.product_id,
                        "acquisition_time": t1_obs.acquisition_time.isoformat(),
                        "orbit_direction": t1_orbit,
                        "relative_orbit": t1_rel_orbit,
                    },
                    "t2": {
                        "observation_id": t2_obs.id,
                        "product_id": t2_obs.product_id,
                        "acquisition_time": t2_obs.acquisition_time.isoformat(),
                        "orbit_direction": t2_orbit,
                        "relative_orbit": t2_rel_orbit,
                    },
                }

        # 4. Preprocess both T1 and T2 (idempotent)
        t1_proc = self.preprocess_observation(t1_obs.id, db=db)
        t2_proc = self.preprocess_observation(t2_obs.id, db=db)

        # 5. Deterministic change storage
        change_dir = self.base_storage_dir / location_id / "derived" / "change" / f"{t2_obs.id}_vs_{t1_obs.id}"
        change_dir.mkdir(parents=True, exist_ok=True)
        delta_vv_path = change_dir / "delta_vv.tif"
        delta_vh_path = change_dir / "delta_vh.tif"
        change_mask_path = change_dir / "change_mask.tif"
        change_manifest_path = change_dir / "change_manifest.json"

        # Check existing result for idempotency
        if not force_reprocess and change_manifest_path.exists() and change_mask_path.exists():
            try:
                with open(change_manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                if (
                    manifest_data.get("vv_threshold_db") == th_vv
                    and manifest_data.get("vh_threshold_db") == th_vh
                ):
                    logger.info("Identical change detection result exists. Returning cached result.")
                    return {
                        "location_id": location_id,
                        "sensor": "SENTINEL-1",
                        "status": "ALREADY_PROCESSED",
                        "t1": manifest_data["t1"],
                        "t2": manifest_data["t2"],
                        "delta_vv_mean_db": manifest_data["delta_vv_statistics"]["mean"],
                        "delta_vh_mean_db": manifest_data["delta_vh_statistics"]["mean"],
                        "vv_changed_percent": manifest_data["vv_changed_percentage"],
                        "vh_changed_percent": manifest_data["vh_changed_percentage"],
                        "joint_changed_percent": manifest_data["joint_changed_percentage"],
                        "changed_percentage": manifest_data["changed_percentage"],
                        "significant_change_regions_count": len(manifest_data.get("significant_change_regions", [])),
                        "significant_change_regions": manifest_data.get("significant_change_regions", []),
                        "change_raster": str(change_mask_path),
                        "delta_vv_raster": str(delta_vv_path),
                        "delta_vh_raster": str(delta_vh_path),
                        "manifest": manifest_data,
                    }
            except Exception:
                pass

        # Load processed dB arrays
        t1_vv_db = tifffile.imread(t1_proc["vv_raster"])
        t1_vh_db = tifffile.imread(t1_proc["vh_raster"])
        t2_vv_db = tifffile.imread(t2_proc["vv_raster"])
        t2_vh_db = tifffile.imread(t2_proc["vh_raster"])

        if t1_vv_db.shape != t2_vv_db.shape:
            raise ValueError(f"Raster dimension mismatch: T1 {t1_vv_db.shape} vs T2 {t2_vv_db.shape}")

        height, width = t1_vv_db.shape
        aoi_mask = self.create_aoi_mask(height, width)

        # 6. Temporal Differences: ΔVV and ΔVH (in dB)
        delta_vv = t2_vv_db - t1_vv_db
        delta_vh = t2_vh_db - t1_vh_db

        valid_mask = aoi_mask & np.isfinite(delta_vv) & np.isfinite(delta_vh)
        total_aoi_pixels = int(np.sum(aoi_mask))
        valid_pixels = int(np.sum(valid_mask))

        if valid_pixels == 0:
            raise ValueError("No valid pixels found within AOI for temporal difference.")

        # 7. Spatial SAR Change Mask Generation (Categorical 0-4)
        # 0 = NO_DATA
        # 1 = NO_SIGNIFICANT_CHANGE
        # 2 = VV_CHANGE
        # 3 = VH_CHANGE
        # 4 = VV_AND_VH_CHANGE
        change_mask = np.zeros((height, width), dtype=np.uint8)
        change_mask[valid_mask] = 1

        vv_change_mask = valid_mask & (np.abs(delta_vv) >= th_vv)
        vh_change_mask = valid_mask & (np.abs(delta_vh) >= th_vh)

        change_mask[vv_change_mask & ~vh_change_mask] = 2
        change_mask[~vv_change_mask & vh_change_mask] = 3
        change_mask[vv_change_mask & vh_change_mask] = 4

        # Metrics
        vv_changed_count = int(np.sum(vv_change_mask))
        vh_changed_count = int(np.sum(vh_change_mask))
        joint_changed_count = int(np.sum(vv_change_mask & vh_change_mask))
        total_changed_count = int(np.sum(change_mask >= 2))

        vv_changed_pct = (vv_changed_count / valid_pixels) * 100.0
        vh_changed_pct = (vh_changed_count / valid_pixels) * 100.0
        joint_changed_pct = (joint_changed_count / valid_pixels) * 100.0
        total_changed_pct = (total_changed_count / valid_pixels) * 100.0

        # Statistics
        delta_vv_stats = self.calculate_band_statistics(delta_vv, valid_mask)
        delta_vh_stats = self.calculate_band_statistics(delta_vh, valid_mask)

        # 8. Connected Change Regions Analysis
        regions = self.detect_connected_change_regions(change_mask)

        # 9. Save output GeoTIFFs
        masked_delta_vv = np.where(valid_mask, delta_vv, np.nan)
        masked_delta_vh = np.where(valid_mask, delta_vh, np.nan)
        tifffile.imwrite(str(delta_vv_path), masked_delta_vv.astype(np.float32))
        tifffile.imwrite(str(delta_vh_path), masked_delta_vh.astype(np.float32))
        tifffile.imwrite(str(change_mask_path), change_mask)

        # 10. Write change manifest
        change_manifest = {
            "location_id": location_id,
            "t1": {
                "observation_id": t1_obs.id,
                "product_id": t1_obs.product_id,
                "acquisition_time": t1_obs.acquisition_time.isoformat(),
                "orbit_direction": t1_orbit,
                "relative_orbit": t1_rel_orbit,
                "vv_mean_db": t1_proc["vv_mean_db"],
                "vh_mean_db": t1_proc["vh_mean_db"],
            },
            "t2": {
                "observation_id": t2_obs.id,
                "product_id": t2_obs.product_id,
                "acquisition_time": t2_obs.acquisition_time.isoformat(),
                "orbit_direction": t2_orbit,
                "relative_orbit": t2_rel_orbit,
                "vv_mean_db": t2_proc["vv_mean_db"],
                "vh_mean_db": t2_proc["vh_mean_db"],
            },
            "vv_threshold_db": th_vv,
            "vh_threshold_db": th_vh,
            "total_aoi_pixels": total_aoi_pixels,
            "valid_pixels": valid_pixels,
            "changed_pixels": total_changed_count,
            "changed_percentage": round(total_changed_pct, 2),
            "vv_changed_percentage": round(vv_changed_pct, 2),
            "vh_changed_percentage": round(vh_changed_pct, 2),
            "joint_changed_percentage": round(joint_changed_pct, 2),
            "delta_vv_statistics": delta_vv_stats,
            "delta_vh_statistics": delta_vh_stats,
            "significant_change_regions_count": len(regions),
            "significant_change_regions": regions,
            "delta_vv_raster": str(delta_vv_path),
            "delta_vh_raster": str(delta_vh_path),
            "change_raster": str(change_mask_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "SUCCESS",
        }

        with open(change_manifest_path, "w", encoding="utf-8") as f:
            json.dump(change_manifest, f, indent=2)

        # 11. Database Persistence
        change_record = Sentinel1ChangeDetection(
            id=f"sar-change-{t2_obs.id}-vs-{t1_obs.id}",
            location_id=location_id,
            t1_observation_id=t1_obs.id,
            t2_observation_id=t2_obs.id,
            t1_product_id=t1_obs.product_id,
            t2_product_id=t2_obs.product_id,
            t1_acquisition_time=t1_obs.acquisition_time,
            t2_acquisition_time=t2_obs.acquisition_time,
            orbit_information=json.dumps({
                "t1_orbit_direction": t1_orbit,
                "t2_orbit_direction": t2_orbit,
                "t1_relative_orbit": t1_rel_orbit,
                "t2_relative_orbit": t2_rel_orbit,
            }),
            delta_vv_statistics=json.dumps(delta_vv_stats),
            delta_vh_statistics=json.dumps(delta_vh_stats),
            changed_percentage=total_changed_pct,
            thresholds=json.dumps({"vv_threshold_db": th_vv, "vh_threshold_db": th_vh}),
            change_raster_path=str(change_mask_path),
            status="SUCCESS",
        )
        db.merge(change_record)
        db.commit()

        logger.info(
            f"Successfully computed SAR change for {location_id} ({t2_obs.id} vs {t1_obs.id}): "
            f"Mean ΔVV={delta_vv_stats['mean']} dB, Changed={total_changed_pct:.2f}%"
        )

        return {
            "location_id": location_id,
            "sensor": "SENTINEL-1",
            "status": "SUCCESS",
            "t1": change_manifest["t1"],
            "t2": change_manifest["t2"],
            "delta_vv_mean_db": delta_vv_stats["mean"],
            "delta_vh_mean_db": delta_vh_stats["mean"],
            "vv_changed_percent": round(vv_changed_pct, 2),
            "vh_changed_percent": round(vh_changed_pct, 2),
            "joint_changed_percent": round(joint_changed_pct, 2),
            "changed_percentage": round(total_changed_pct, 2),
            "significant_change_regions_count": len(regions),
            "significant_change_regions": regions,
            "change_raster": str(change_mask_path),
            "delta_vv_raster": str(delta_vv_path),
            "delta_vh_raster": str(delta_vh_path),
            "manifest": change_manifest,
        }
