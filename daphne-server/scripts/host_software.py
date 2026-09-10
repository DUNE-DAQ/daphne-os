"""Validate kernel/OS metadata, not current rootfs integrity or boot health."""
import re

KEYS = ("PRETTY_NAME", "ID", "VERSION_ID", "BUILD_ID", "IMAGE_ID", "IMAGE_VERSION")
MAX_AGE_NS = 5_000_000_000


def require(condition):
    if not condition:
        raise RuntimeError("Invalid host software observation; details suppressed")


def check_host_software(status, high, *, now_monotonic_ns, required=True):
    if not status.host_software and not required:
        return None
    require(now_monotonic_ns > 0 and len(status.host_software) == 7)
    items = {item.metric: item for item in status.host_software}
    require(items.keys() == set(range(1, 8)))
    sources, starts, completed, report = set(), set(), set(), []
    for metric in range(1, 8):
        item = items[metric]
        require(0 < len(item.detail) <= 512)
        if metric == high.HOST_KERNEL_RELEASE:
            require(item.source == "uname:release")
        else:
            key = KEYS[metric - 2]
            require(item.source in (f"/etc/os-release:{key}", f"/usr/lib/os-release:{key}"))
            sources.add(item.source.split(":")[0])
            starts.add(item.acquisition_started_monotonic_ns)
        require(item.quality in (high.MEASUREMENT_GOOD, high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR))
        good = item.quality == high.MEASUREMENT_GOOD
        require(item.HasField("value") == good)
        if good:
            value = item.value
            require(0 < len(value.encode("utf-8")) <= 256 and all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value))
            require(0 < item.acquisition_started_monotonic_ns <= item.observed_monotonic_ns <= now_monotonic_ns)
            require(now_monotonic_ns - item.observed_monotonic_ns <= MAX_AGE_NS)
            if metric in (high.HOST_OS_ID, high.HOST_OS_IMAGE_ID):
                require(re.fullmatch(r"[a-z0-9._-]+", value) is not None)
            if metric == high.HOST_OS_VERSION_ID:
                require(re.fullmatch(r"[a-zA-Z0-9._~^+-]+", value) is not None)
            if metric != high.HOST_KERNEL_RELEASE:
                completed.add((item.observed_monotonic_ns, item.observed_host_unix_ns))
        else:
            value = None
            require(not item.observed_monotonic_ns and not item.observed_host_unix_ns)
        # The first four identify the observed running kernel and OS release.
        # Optional image/base labels may be absent; never manufacture defaults.
        require(not required or metric > 4 or good)
        report.append({"metric": high.HostSoftwareMetric.Name(metric), "value": value,
                       "quality": high.MeasurementQuality.Name(item.quality), "source": item.source,
                       "observed_monotonic_ns": item.observed_monotonic_ns})
    require(len(sources) == 1 and len(starts) == 1 and len(completed) <= 1)
    for metric, legacy in ((high.HOST_KERNEL_RELEASE, status.kernel_release),
                           (high.HOST_OS_PRETTY_NAME, status.petalinux_version)):
        item = items[metric]
        require(legacy == (item.value if item.quality == high.MEASUREMENT_GOOD else ""))
    return {"observations": report, "rootfs_integrity_verified": False, "boot_health_verified": False}
