"""
satguard/monitor.py
CLI entrypoint supporting command: python -m satguard.monitor run
"""

import sys
from satguard.monitoring.service import run_monitoring_cli

if __name__ == "__main__":
    loc_id = None
    if len(sys.argv) > 2 and sys.argv[1] == "run":
        loc_id = sys.argv[2]
    run_monitoring_cli(location_id=loc_id)
