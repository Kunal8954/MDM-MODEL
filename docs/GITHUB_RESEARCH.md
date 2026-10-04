# SATGUARD Open-Source GitHub Intelligence & Reuse Audit

## Document Overview
This document evaluates vetted open-source repositories and scientific libraries across satellite image processing, SAR change detection, flood mapping, landslide susceptibility, glacier monitoring, and geospatial deep learning.

Every repository is analyzed for:
1. Official GitHub URL
2. Legal Software License
3. Star count and community adoption
4. Activity & maintenance status
5. Specific technical components candidate for architectural reuse
6. Legal reuse suitability for government-grade systems
7. Production-readiness rating

---

## 1. Candidate Repository Evaluations

### 1. `torchgeo/torchgeo`
*   **Repository:** `torchgeo/torchgeo`
*   **GitHub URL:** https://github.com/torchgeo/torchgeo
*   **License:** MIT License (Permissive)
*   **Stars:** ~4,200+
*   **Last Activity:** Active (Weekly commits, regular releases, NumFOCUS affiliated)
*   **Component for Reuse:**
    *   `torchgeo.models.ChangeStar`: Change detection network architecture designed for multi-temporal optical imagery.
    *   Siamese segmentation heads and pre-trained geospatial encoders (e.g., Presto, SatMAE).
    *   Spatial samplers (`RandomGeoSampler`, `GridGeoSampler`) for slicing large raster grids without loading full scenes into GPU VRAM.
*   **Legal Reuse Status:** **Fully Approved.** MIT license allows unrestricted commercial, governmental, and private reuse, modification, and sublicensing with attribution.
*   **Production Readiness:** **High.** Well-documented, 95%+ test coverage, strict CI/CD, integrated with PyTorch Lightning.

---

### 2. `sentinel-hub/sentinelhub-py`
*   **Repository:** `sentinel-hub/sentinelhub-py`
*   **GitHub URL:** https://github.com/sentinel-hub/sentinelhub-py
*   **License:** MIT License (Permissive)
*   **Stars:** ~920+
*   **Last Activity:** Active (Maintained by Sinergise / Planet; full support for CDSE endpoints)
*   **Component for Reuse:**
    *   `SHConfig`: Configuration manager natively adapted to `https://sh.dataspace.copernicus.eu`.
    *   `SentinelHubCatalog`: Pre-built query builder for Sentinel-1 and Sentinel-2 acquisitions.
    *   `SentinelHubStatistical`: Computes spectral index histograms (NDWI, NDVI) and cloud-free statistics directly on the server without downloading raw gigabyte-scale tiles.
*   **Legal Reuse Status:** **Fully Approved.** MIT license allows seamless server-side incorporation.
*   **Production Readiness:** **Very High.** Production standard used globally across European and international EO platforms.

---

### 3. `sentinel-hub/eo-learn`
*   **Repository:** `sentinel-hub/eo-learn`
*   **GitHub URL:** https://github.com/sentinel-hub/eo-learn
*   **License:** MIT License (Permissive)
*   **Stars:** ~1,300+
*   **Last Activity:** Active (Regular maintenance cycles)
*   **Component for Reuse:**
    *   `EOPatch`: Structured container for multi-temporal raster arrays, vector features, and scalar time-series metadata.
    *   `eo-learn.features`: Pre-built transformations for band math (NDWI, MNDWI, NDSI snow index, NDVI).
    *   Temporal interpolation tasks to fill cloud-masked optical gaps.
*   **Legal Reuse Status:** **Fully Approved.** MIT license allows embedding into proprietary or sovereign pipelines.
*   **Production Readiness:** **High.** Robust modular architecture tested on continent-scale agricultural and land-cover workflows.

---

### 4. `bopen/sarsen`
*   **Repository:** `bopen/sarsen`
*   **GitHub URL:** https://github.com/bopen/sarsen
*   **License:** Apache License 2.0 (Permissive)
*   **Stars:** ~180+
*   **Last Activity:** Maintained (Sponsored by Microsoft Planetary Computer and ESA)
*   **Component for Reuse:**
    *   Cloud-native algorithms for Radiometric Terrain Correction (RTC) and Geometric Terrain Correction (GTC) of Sentinel-1 GRD and SLC products using Copernicus DEM.
    *   Direct integration with `xarray`, `rioxarray`, and `dask` enabling parallel processing of SAR swaths.
*   **Legal Reuse Status:** **Fully Approved.** Apache 2.0 allows free commercial/governmental reuse with clear patent grant and attribution.
*   **Production Readiness:** **Medium-High.** Highly performant mathematical core; ideal for targeted AOI cropping rather than bulk continent-wide reprocessing.

---

### 5. `johntruckenbrodt/pyroSAR`
*   **Repository:** `johntruckenbrodt/pyroSAR`
*   **GitHub URL:** https://github.com/johntruckenbrodt/pyroSAR
*   **License:** MIT License (Permissive)
*   **Stars:** ~380+
*   **Last Activity:** Active (German Aerospace Center / University of Jena community)
*   **Component for Reuse:**
    *   `pyroSAR.snap`: Automation wrappers for ESA SNAP (Sentinel Application Platform) command line execution.
    *   Automated extraction of orbit state vectors, calibration coefficients, and spatial footprints from raw Sentinel-1 `.SAFE` zip archives into a SpatiaLite/PostgreSQL index.
*   **Legal Reuse Status:** **Fully Approved.** MIT license allows unrestricted use.
*   **Production Readiness:** **Medium-High.** Excellent for offline batch pre-processing; for real-time microservices, native Python RTC (e.g., `sarsen`) is preferred to avoid heavy SNAP JVM dependencies.

---

### 6. `fjmeyer/HydroSAR` & `ASF-SAR/asf-tools`
*   **Repository:** `ASF-SAR/asf-tools` (and `fjmeyer/HydroSAR`)
*   **GitHub URL:** https://github.com/ASF-SAR/asf-tools
*   **License:** BSD 3-Clause License (Permissive)
*   **Stars:** ~150+
*   **Last Activity:** Active (Maintained by Alaska Satellite Facility)
*   **Component for Reuse:**
    *   `asf_tools.water_map`: Automated, unsupervised SAR water extent extraction using bi-modal histogram thresholding (Kittler-Illingworth algorithm) on Sentinel-1 VV backscatter.
    *   `asf_tools.flood_map`: Differential thresholding comparing an event observation against a multi-month historical dry baseline to isolate flood-induced inundation from permanent reservoirs.
    *   HAND (Height Above Nearest Drainage) terrain masking to eliminate false SAR water detections on shadowed mountain slopes.
*   **Legal Reuse Status:** **Fully Approved.** BSD-3-Clause is completely compatible with proprietary and government-grade software architectures.
*   **Production Readiness:** **High.** Operationally deployed by NASA/ASF during major global flood disasters.

---

### 7. `nasa/LHASA`
*   **Repository:** `nasa/LHASA`
*   **GitHub URL:** https://github.com/nasa/LHASA
*   **License:** Apache License 2.0 (NASA Open Source Agreement compatible)
*   **Stars:** ~110+
*   **Last Activity:** Active (NASA Goddard Space Flight Center Disaster Team)
*   **Component for Reuse:**
    *   Landslide Hazard Assessment for Situational Awareness decision tree model.
    *   Dynamic rainfall trigger matrix combining 72-hour antecedent rainfall (from GPM IMERG) with a static landslide susceptibility raster (derived from Copernicus DEM slope, distance to fault lines, and geological lithology).
*   **Legal Reuse Status:** **Fully Approved.** Open-source release under standard US Government / Apache 2.0 permissive guidelines.
*   **Production Readiness:** **High.** Peer-reviewed scientific methodology running operationally for global situational awareness.

---

### 8. `OGGM/oggm`
*   **Repository:** `OGGM/oggm`
*   **GitHub URL:** https://github.com/OGGM/oggm
*   **License:** BSD 3-Clause License (Permissive, transitioned from GPLv3 in v1.2+)
*   **Stars:** ~270+
*   **Last Activity:** Highly Active (International glaciology consortium)
*   **Component for Reuse:**
    *   Topographical glacier boundary extraction and centerline flow routing based on DEM grids.
    *   Randolph Glacier Inventory (RGI) integration tools for querying historical glacier perimeters.
    *   Mass-balance and elevation change trend estimation.
*   **Legal Reuse Status:** **Fully Approved.** As of version 1.2+, OGGM's BSD 3-Clause license eliminates the viral copyleft risks of earlier versions, allowing safe inclusion in enterprise systems.
*   **Production Readiness:** **High for scientific modeling.** Computationally intensive; in SATGUARD, only perimeter vector extraction and slope-stability modules should be leveraged.

---

### 9. `ESA-PhiLab/OpenSarToolkit`
*   **Repository:** `ESA-PhiLab/OpenSarToolkit`
*   **GitHub URL:** https://github.com/ESA-PhiLab/OpenSarToolkit
*   **License:** MIT License (Permissive)
*   **Stars:** ~250+
*   **Last Activity:** Maintained (ESA Earth Observation Innovation Lab)
*   **Component for Reuse:**
    *   Time-series SAR change detection pipelines (multi-temporal despeckling via Quegan & Yu filter).
    *   Ratio and log-ratio change detection algorithms specifically tuned for Sentinel-1 dual-polarization ($\text{VV} / \text{VH}$) data.
*   **Legal Reuse Status:** **Fully Approved.** MIT license.
*   **Production Readiness:** **Medium.** Robust scientific logic; contains legacy packaging scripts that require modernization to clean Python 3.11+ / Pydantic v2 abstractions.

---

### 10. `stac-utils/pystac-client`
*   **Repository:** `stac-utils/pystac-client`
*   **GitHub URL:** https://github.com/stac-utils/pystac-client
*   **License:** Apache License 2.0 (Permissive)
*   **Stars:** ~350+
*   **Last Activity:** Highly Active (Radiant Earth Foundation / STAC community)
*   **Component for Reuse:**
    *   Standardized STAC v1.0 search query builder for discovering CDSE Sentinel-1, Sentinel-2, and Copernicus DEM collections.
    *   Pagination, bounding box clipping, and GeoJSON conversion.
*   **Legal Reuse Status:** **Fully Approved.**
*   **Production Readiness:** **Very High.** Industry benchmark for STAC catalog interaction.

---

## 2. Licensing Risk Assessment Matrix

| License Type | Permitted in SATGUARD? | Viral Copyleft Risk? | Commercial & Gov Use? | Conditions |
| :--- | :---: | :---: | :---: | :--- |
| **MIT** | **YES** | **NO** | Permitted | Maintain original copyright notice in distribution. |
| **Apache 2.0** | **YES** | **NO** | Permitted | Maintain copyright notice, include patent grant, state significant modifications. |
| **BSD 3-Clause** | **YES** | **NO** | Permitted | Maintain copyright notice, no endorsement using project/author names. |
| **GPLv3 / AGPLv3** | **FORBIDDEN** | **YES (High Risk)** | Restricted | Requires any derivative work or networked backend to disclose complete source code under GPL. **STRICTLY PROHIBITED in SATGUARD codebase.** |

> [!IMPORTANT]
> All 10 candidate repositories selected above use **MIT**, **Apache 2.0**, or **BSD-3-Clause** licenses. **Zero GPL/AGPL dependencies are permitted.**
