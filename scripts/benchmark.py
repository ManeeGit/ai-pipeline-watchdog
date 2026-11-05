"""Small reproducible synthetic microbenchmark, not a throughput guarantee."""
import json
import platform
import resource
import statistics
import tempfile
import time
from pathlib import Path

from pipeline_watchdog.demo import create_demo
from pipeline_watchdog.service import Watchdog

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory) / "bench"
    create_demo(root, "healthy")
    app = Watchdog(root / "watchdog.json", root / "watchdog.db")
    durations = []
    for _ in range(30):
        start = time.perf_counter()
        app.scan()
        durations.append((time.perf_counter() - start) * 1000)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() != "Darwin":
        peak *= 1024
    print(json.dumps({"scope": "30 scans, 3 synthetic CSV pipelines, approximately 410 total rows; excludes browser and model",
                      "platform": platform.system(), "python": platform.python_version(), "median_scan_ms": round(statistics.median(durations), 3),
                      "p95_scan_ms": round(sorted(durations)[28], 3), "peak_process_rss_mib": round(peak / 1024 ** 2, 2),
                      "database_bytes": (root / "watchdog.db").stat().st_size}, indent=2))
