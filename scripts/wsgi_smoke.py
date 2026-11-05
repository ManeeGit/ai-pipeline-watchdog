"""Optional local Gunicorn smoke fixture; no cloud credentials or API calls."""
from pipeline_watchdog.cloud import CloudDashboard, VersionedObject, run_scan


class MemoryObjects:
    def __init__(self):
        self.items = {}

    def read(self, name, max_bytes):
        result = self.items.get(name)
        if result and len(result.content) > max_bytes:
            raise ValueError("too large")
        return result

    def write(self, name, content, expected_generation):
        current = self.items.get(name)
        if (current.generation if current else 0) != expected_generation:
            raise ValueError("generation conflict")
        self.items[name] = VersionedObject(content, expected_generation + 1)


objects = MemoryObjects()
run_scan(objects, scenario="cascade")
app = CloudDashboard(objects)
