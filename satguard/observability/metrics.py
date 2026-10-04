"""
satguard/observability/metrics.py
Operational Metrics Collector for SATGUARD Platform Reliability.
"""

import time
from typing import Dict, Any, List
from collections import defaultdict


class MetricsCollector:
    """
    Lightweight, thread-safe operational metrics collector.
    Exposes system-level latency and success/failure counters without external agent dependencies.
    """

    def __init__(self):
        self.start_time = time.time()
        self.api_requests_total = 0
        self.api_errors_total = 0
        self.requests_by_endpoint: Dict[str, int] = defaultdict(int)
        self.latencies_ms: List[float] = []
        self.monitoring_runs_total = 0
        self.monitoring_runs_success = 0
        self.monitoring_runs_failed = 0

    def record_request(self, endpoint: str, duration_ms: float, status_code: int):
        self.api_requests_total += 1
        self.requests_by_endpoint[endpoint] += 1
        if status_code >= 400:
            self.api_errors_total += 1
        
        # Keep sliding buffer of latest 1000 latencies
        self.latencies_ms.append(duration_ms)
        if len(self.latencies_ms) > 1000:
            self.latencies_ms.pop(0)

    def record_monitoring_run(self, status: str, duration_seconds: float = 0.0):
        self.monitoring_runs_total += 1
        if status.upper() in ("COMPLETED", "SUCCESS"):
            self.monitoring_runs_success += 1
        else:
            self.monitoring_runs_failed += 1

    def get_summary(self) -> Dict[str, Any]:
        uptime_seconds = round(time.time() - self.start_time, 1)
        
        p50 = 0.0
        p95 = 0.0
        p99 = 0.0
        avg_latency = 0.0

        if self.latencies_ms:
            sorted_lat = sorted(self.latencies_ms)
            n = len(sorted_lat)
            p50 = sorted_lat[int(n * 0.50)]
            p95 = sorted_lat[min(int(n * 0.95), n - 1)]
            p99 = sorted_lat[min(int(n * 0.99), n - 1)]
            avg_latency = round(sum(sorted_lat) / n, 2)

        error_rate = (
            round((self.api_errors_total / self.api_requests_total) * 100, 2)
            if self.api_requests_total > 0
            else 0.0
        )

        return {
            "uptime_seconds": uptime_seconds,
            "api_metrics": {
                "requests_total": self.api_requests_total,
                "errors_total": self.api_errors_total,
                "error_rate_pct": error_rate,
                "latency_p50_ms": p50,
                "latency_p95_ms": p95,
                "latency_p99_ms": p99,
                "average_latency_ms": avg_latency,
            },
            "monitoring_pipeline_metrics": {
                "runs_total": self.monitoring_runs_total,
                "runs_success": self.monitoring_runs_success,
                "runs_failed": self.monitoring_runs_failed,
            },
        }


metrics_collector = MetricsCollector()
