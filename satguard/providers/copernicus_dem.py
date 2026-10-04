"""
satguard/providers/copernicus_dem.py
Copernicus Digital Elevation Model (GLO-30) provider on AWS Open Data.
Requires NO API key or AWS credentials (uses unsigned S3 client).
"""

from typing import Dict, Any, Optional
import math
import boto3
from botocore import UNSIGNED
from botocore.client import Config
from satguard.providers.base import ElevationProvider


class CopernicusDEMProvider(ElevationProvider):
    """
    Direct access to Copernicus DEM GLO-30 Cloud-Optimized GeoTIFFs hosted on AWS Open Data.
    Bucket: s3://copernicus-dem-30m/
    """

    def __init__(self, bucket_name: str = "copernicus-dem-30m", region: str = "eu-central-1"):
        self.bucket_name = bucket_name
        self.region = region
        # Create unauthenticated S3 client
        self.s3_client = boto3.client(
            "s3",
            region_name=self.region,
            config=Config(signature_version=UNSIGNED),
        )

    def _get_tile_prefix(self, latitude: float, longitude: float) -> str:
        """
        Derive Copernicus DEM 1-arc-second tile identifier.
        Example: Lat 30.3781, Lon 78.4803 -> Copernicus_DSM_COG_10_N30_00_E078_00_DEM
        """
        lat_int = math.floor(latitude)
        lon_int = math.floor(longitude)

        lat_hem = "N" if lat_int >= 0 else "S"
        lon_hem = "E" if lon_int >= 0 else "W"

        lat_str = f"{lat_hem}{abs(lat_int):02d}_00"
        lon_str = f"{lon_hem}{abs(lon_int):03d}_00"

        tile_name = f"Copernicus_DSM_COG_10_{lat_str}_{lon_str}_DEM"
        return tile_name

    def check_dem_tile_availability(
        self,
        latitude: float,
        longitude: float,
    ) -> Dict[str, Any]:
        """
        Verifies tile presence on the public AWS S3 bucket and returns metadata.
        """
        tile_name = self._get_tile_prefix(latitude, longitude)
        prefix = f"{tile_name}/{tile_name}.tif"

        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=prefix,
            )
            content_length = response.get("ContentLength", 0)
            last_modified = response.get("LastModified")

            return {
                "available": True,
                "tile_name": tile_name,
                "s3_uri": f"s3://{self.bucket_name}/{prefix}",
                "https_url": f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{prefix}",
                "size_bytes": content_length,
                "size_mb": round(content_length / (1024 * 1024), 2),
                "last_modified": last_modified.isoformat() if last_modified else None,
                "format": "Cloud-Optimized GeoTIFF (COG)",
                "resolution": "30m (1 arc-second)",
            }
        except self.s3_client.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            return {
                "available": False,
                "tile_name": tile_name,
                "error_code": error_code,
                "message": f"Tile not found in public bucket or inaccessible: {e}",
            }
