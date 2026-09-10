"""Independent validation of typed host observations; no I/O or hardware access."""
import math


def check_host_resources(status, high, required=False, *, now_monotonic_ns=None):
    if not status.host_resources and not required:
        return None
    expected = {
        high.HOST_UPTIME_SECONDS: ("scalar_value", "s", "/proc/uptime:first field"),
        high.HOST_LOAD_AVERAGE_1MIN: ("scalar_value", "1", "/proc/loadavg:first field"),
        high.HOST_MEMORY_AVAILABLE_BYTES: ("bytes_value", "B", "/proc/meminfo:MemAvailable"),
        high.HOST_ROOT_FREE_BYTES: ("bytes_value", "B", "statvfs(/):f_bfree*f_frsize"),
        high.HOST_ROOT_AVAILABLE_BYTES: ("bytes_value", "B", "statvfs(/):f_bavail*f_frsize"),
        high.HOST_ROOT_READ_ONLY: ("flag_value", "1", "statvfs(/):ST_RDONLY"),
    }
    readings = {item.metric: item for item in status.host_resources}
    if len(readings) != len(status.host_resources) or readings.keys() != expected.keys():
        raise RuntimeError("Missing, duplicate or unexpected host resource metric")
    report = []
    for metric, (field, unit, source) in expected.items():
        item = readings[metric]
        if item.unit != unit or item.source != source or not item.detail:
            raise RuntimeError("Wrong host resource units/source/detail")
        good = item.quality == high.MEASUREMENT_GOOD
        if good:
            if (item.WhichOneof("value") != field or not item.acquisition_started_monotonic_ns
                    or item.observed_monotonic_ns < item.acquisition_started_monotonic_ns):
                raise RuntimeError("Wrong host resource value type or acquisition clock")
            value = getattr(item, field)
            if field == "scalar_value" and (not math.isfinite(value) or value < 0):
                raise RuntimeError("Invalid host resource decimal value")
            if now_monotonic_ns is not None and not 0 <= now_monotonic_ns - item.observed_monotonic_ns <= 5_000_000_000:
                raise RuntimeError("Stale or future host resource observation")
        else:
            value = None
            if (item.quality not in (high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR)
                    or item.WhichOneof("value") is not None or item.observed_monotonic_ns or item.observed_host_unix_ns):
                raise RuntimeError("Failed host resource looks like a measurement")
        if required and not good:
            raise RuntimeError("Required host resource is unavailable or invalid")
        report.append({"metric": high.HostResourceMetric.Name(metric), "value": value, "unit": unit,
                       "quality": high.MeasurementQuality.Name(item.quality), "source": source,
                       "observed_monotonic_ns": item.observed_monotonic_ns,
                       "observed_host_unix_ns": item.observed_host_unix_ns})
    root = [readings[metric] for metric in (high.HOST_ROOT_FREE_BYTES, high.HOST_ROOT_AVAILABLE_BYTES, high.HOST_ROOT_READ_ONLY)]
    if len({(r.quality, r.acquisition_started_monotonic_ns, r.observed_monotonic_ns, r.observed_host_unix_ns) for r in root}) != 1:
        raise RuntimeError("Mixed root filesystem observations")
    if root[0].quality == high.MEASUREMENT_GOOD and root[1].bytes_value > root[0].bytes_value:
        raise RuntimeError("Root available space exceeds free space")
    return report
