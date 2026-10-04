"""
satguard/providers/copernicus.py
Copernicus Data Space Ecosystem (CDSE) Provider.
Integrates OAuth2 Keycloak token management, STAC catalog search, and OData access.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import requests
from shapely.geometry import Polygon, mapping
from satguard.providers.base import SatelliteProvider, ObservationHeader


class CopernicusSatelliteProvider(SatelliteProvider):
    """
    Authoritative CDSE client for Sentinel-1 and Sentinel-2 observation discovery.
    """

    TOKEN_ENDPOINT = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    STAC_ENDPOINT = "https://stac.dataspace.copernicus.eu/v1/search"
    ODATA_ENDPOINT = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        s3_access_key: Optional[str] = None,
        s3_secret_key: Optional[str] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.s3_access_key = s3_access_key
        self.s3_secret_key = s3_secret_key

        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authenticate(self) -> bool:
        """
        Executes OAuth2 client_credentials grant against Keycloak token service.
        """
        if not self.is_configured():
            return False

        # Return cached token if still valid (with 60-second buffer)
        if self._access_token and self._token_expires_at:
            if datetime.now(timezone.utc) < (self._token_expires_at - timedelta(seconds=60)):
                return True

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post(self.TOKEN_ENDPOINT, data=payload, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            self._access_token = data.get("access_token")
            expires_in = data.get("expires_in", 600)
            self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            return True
        except requests.RequestException as e:
            raise ConnectionError(f"CDSE OAuth2 authentication failed: {e}")

    def search_observations(
        self,
        geometry: Polygon,
        start_time: datetime,
        end_time: datetime,
        collection: str = "sentinel-2-l2a",
        max_cloud_cover: float = 30.0,
        limit: int = 20,
    ) -> List[ObservationHeader]:
        """
        Searches CDSE STAC catalog for observations intersecting geometry within time range.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/geo+json",
        }

        # If credentials exist, attach bearer token
        if self.authenticate():
            headers["Authorization"] = f"Bearer {self._access_token}"

        time_str = (
            f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

        body: Dict[str, Any] = {
            "collections": [collection],
            "intersects": mapping(geometry),
            "datetime": time_str,
            "limit": limit,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }

        if "sentinel-2" in collection:
            body["query"] = {"eo:cloud_cover": {"lte": max_cloud_cover}}

        try:
            response = requests.post(self.STAC_ENDPOINT, json=body, headers=headers, timeout=25)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise ConnectionError(f"CDSE STAC query failed: {e}")

        observations: List[ObservationHeader] = []
        features = data.get("features", [])

        for feat in features:
            props = feat.get("properties", {})
            acq_str = props.get("datetime")
            acq_dt = (
                datetime.fromisoformat(acq_str.replace("Z", "+00:00"))
                if acq_str
                else datetime.now(timezone.utc)
            )

            # S3 direct path if available in assets
            s3_path = None
            assets = feat.get("assets", {})
            if "PRODUCT" in assets:
                s3_path = assets["PRODUCT"].get("href")

            obs = ObservationHeader(
                product_id=feat.get("id", "unknown"),
                collection=collection,
                sensor="MSI" if "sentinel-2" in collection else "SAR-C",
                acquisition_time=acq_dt,
                cloud_cover=props.get("eo:cloud_cover"),
                footprint=feat.get("geometry", {}),
                s3_uri=s3_path,
                processing_level=props.get("processing:level", "Level-2A"),
                quicklook_url=assets.get("thumbnail", {}).get("href"),
                assets=assets,
            )
            observations.append(obs)

        return observations

    def search_sentinel1_raw(
        self,
        geometry: Polygon,
        start_time: datetime,
        end_time: datetime,
        acquisition_mode: Optional[str] = "IW",
        orbit_direction: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Executes raw STAC query for Sentinel-1 GRD products intersecting geometry within time window.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/geo+json",
        }

        if self.authenticate():
            headers["Authorization"] = f"Bearer {self._access_token}"

        time_str = (
            f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

        body: Dict[str, Any] = {
            "collections": ["sentinel-1-grd"],
            "intersects": mapping(geometry),
            "datetime": time_str,
            "limit": limit,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }

        try:
            response = requests.post(self.STAC_ENDPOINT, json=body, headers=headers, timeout=25)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise ConnectionError(f"CDSE Sentinel-1 STAC query failed: {e}")

        features = data.get("features", [])
        return features

    def retrieve_aoi_bands(
        self,
        bbox: tuple[float, float, float, float],
        acquisition_time: datetime,
        window_minutes: int = 60,
        resolution_pixels: int = 256,
    ) -> Dict[str, Any]:
        """
        Retrieves calibrated real Green (B03) and NIR (B08) surface reflectance arrays
        for the given bounding box and observation timestamp using Sentinel Hub Process API on CDSE.
        """
        if not self.authenticate():
            raise PermissionError("Failed to authenticate with CDSE Keycloak token service.")

        sh_url = "https://sh.dataspace.copernicus.eu/api/v1/process"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "image/tiff",
        }

        min_lon, min_lat, max_lon, max_lat = bbox
        time_from = (acquisition_time - timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_to = (acquisition_time + timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        evalscript = """//VERSION=3
function setup() {
  return {
    input: ['B03', 'B08'],
    output: { bands: 2, sampleType: 'FLOAT32' }
  };
}
function evaluatePixel(sample) {
  return [sample.B03, sample.B08];
}
"""

        payload = {
            "input": {
                "bounds": {"bbox": [min_lon, min_lat, max_lon, max_lat]},
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {"from": time_from, "to": time_to},
                        },
                    }
                ],
            },
            "output": {
                "width": resolution_pixels,
                "height": resolution_pixels,
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
            },
            "evalscript": evalscript,
        }

        try:
            resp = requests.post(sh_url, json=payload, headers=headers, timeout=35)
            resp.raise_for_status()
            
            import io, tifffile
            arr = tifffile.imread(io.BytesIO(resp.content))
            # Shape is (height, width, 2)
            green_b03 = arr[:, :, 0]
            nir_b08 = arr[:, :, 1]

            return {
                "green_band": green_b03,
                "nir_band": nir_b08,
                "raw_bytes": len(resp.content),
                "shape": arr.shape,
            }
        except Exception as e:
            raise ConnectionError(f"Failed to retrieve AOI spectral bands from CDSE Process API: {e}")

    def retrieve_sar_bands(
        self,
        bbox: tuple[float, float, float, float],
        acquisition_time: datetime,
        window_minutes: int = 60,
        resolution_pixels: int = 256,
    ) -> Dict[str, Any]:
        """
        Retrieves calibrated real SAR Dual-Polarization (VV + VH) backscatter arrays
        for the given bounding box and acquisition timestamp using Sentinel Hub Process API on CDSE.
        """
        if not self.authenticate():
            raise PermissionError("Failed to authenticate with CDSE Keycloak token service.")

        sh_url = "https://sh.dataspace.copernicus.eu/api/v1/process"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "image/tiff",
        }

        min_lon, min_lat, max_lon, max_lat = bbox
        time_from = (acquisition_time - timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_to = (acquisition_time + timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        evalscript = """//VERSION=3
function setup() {
  return {
    input: ['VV', 'VH'],
    output: { bands: 2, sampleType: 'FLOAT32' }
  };
}
function evaluatePixel(sample) {
  return [sample.VV, sample.VH];
}
"""

        payload = {
            "input": {
                "bounds": {"bbox": [min_lon, min_lat, max_lon, max_lat]},
                "data": [
                    {
                        "type": "sentinel-1-grd",
                        "dataFilter": {
                            "timeRange": {"from": time_from, "to": time_to},
                            "acquisitionMode": "IW",
                            "polarization": "DV",
                            "resolution": "HIGH",
                        },
                        "processing": {
                            "backCoeff": "GAMMA0_ELLIPSOID",
                            "orthorectify": True,
                        },
                    }
                ],
            },
            "output": {
                "width": resolution_pixels,
                "height": resolution_pixels,
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
            },
            "evalscript": evalscript,
        }

        try:
            resp = requests.post(sh_url, json=payload, headers=headers, timeout=35)
            resp.raise_for_status()

            import io, tifffile
            arr = tifffile.imread(io.BytesIO(resp.content))
            vv_band = arr[:, :, 0]
            vh_band = arr[:, :, 1]

            return {
                "vv_band": vv_band,
                "vh_band": vh_band,
                "raw_bytes": len(resp.content),
                "shape": arr.shape,
            }
        except Exception as e:
            raise ConnectionError(f"Failed to retrieve SAR bands from CDSE Process API: {e}")
