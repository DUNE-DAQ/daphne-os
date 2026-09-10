"""Validate local clock observations; no UTC accuracy or FPGA-time inference."""
from datetime import datetime, timedelta, timezone

CLOCK_SOURCE = "clock_gettime:CLOCK_REALTIME/CLOCK_BOOTTIME; CLOCK_MONOTONIC bracket"
KERNEL_SOURCE = "adjtimex:modes=0"
MAX_COLLECTION_NS = 250_000_000
MAX_AGE_NS = 5_000_000_000
MAX_SIGNED = (1 << 63) - 1
CLOCK_FIELDS = ("unix_time_ns", "current_utc", "boottime_ns", "boot_time_estimate_unix_ns",
                "boot_time_estimate_utc", "realtime_sample_span_ns")
KERNEL_FIELDS = ("time_state_raw", "status_raw", "reports_synchronized", "adjustment_offset_ns",
                 "maximum_error_ns", "estimated_error_ns")


def require(value):
    if not value:
        raise RuntimeError("Invalid or stale host-clock observation; details suppressed")


def utc(value):
    require(0 <= value <= MAX_SIGNED)
    seconds, nanos = divmod(value, 1_000_000_000)
    calendar = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return calendar.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


def check_host_time(status, high, *, now_monotonic_ns, require_good=True):
    require(status.HasField("host_time") and status.host_time.HasField("clock")
            and status.host_time.HasField("kernel") and now_monotonic_ns > 0)
    report = {}
    for name, fields, source in (("clock", CLOCK_FIELDS, CLOCK_SOURCE), ("kernel", KERNEL_FIELDS, KERNEL_SOURCE)):
        item = getattr(status.host_time, name)
        require(item.source == source and 0 < len(item.detail) <= 512)
        require(item.quality in (high.MEASUREMENT_GOOD, high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR))
        good = item.quality == high.MEASUREMENT_GOOD
        require(not require_good or good)
        for field in fields:
            require(item.HasField(field) == good)
        if good:
            require(0 < item.acquisition_started_monotonic_ns <= item.observed_monotonic_ns <= now_monotonic_ns)
            require(item.observed_monotonic_ns - item.acquisition_started_monotonic_ns <= MAX_COLLECTION_NS)
            require(now_monotonic_ns - item.observed_monotonic_ns <= MAX_AGE_NS)
        else:
            require(item.observed_monotonic_ns == 0)
        report[name] = {"quality": high.MeasurementQuality.Name(item.quality),
                        "observed_monotonic_ns": item.observed_monotonic_ns}
        # Only known typed fields; never echo free-form detail, peer identity or
        # unrelated fields from a complete system-status reply.
        report[name].update({field: getattr(item, field) if good else None for field in fields})
    wall, kernel = status.host_time.clock, status.host_time.kernel
    if wall.quality == high.MEASUREMENT_GOOD:
        require(0 <= wall.unix_time_ns <= MAX_SIGNED and wall.boottime_ns <= MAX_SIGNED)
        span = wall.realtime_sample_span_ns
        require(span <= wall.observed_monotonic_ns - wall.acquisition_started_monotonic_ns + 1_000_000)
        require(wall.unix_time_ns >= span)
        estimate = wall.unix_time_ns - (span - span // 2) - wall.boottime_ns
        require(0 <= estimate == wall.boot_time_estimate_unix_ns)
        require(wall.current_utc == utc(wall.unix_time_ns) and wall.boot_time_estimate_utc == utc(estimate))
        require(status.ps_local_time == wall.current_utc and status.ps_local_unix_ns == wall.unix_time_ns)
        if kernel.quality == high.MEASUREMENT_GOOD:
            require(wall.observed_monotonic_ns <= kernel.acquisition_started_monotonic_ns)
    else:
        require(not status.ps_local_time and status.ps_local_unix_ns == 0)
    if kernel.quality == high.MEASUREMENT_GOOD:
        require(kernel.time_state_raw in range(6) and kernel.status_raw <= (1 << 31) - 1)
        require(kernel.reports_synchronized == (kernel.time_state_raw != 5))
        require(kernel.maximum_error_ns % 1000 == 0 and kernel.estimated_error_ns % 1000 == 0)
        if not kernel.status_raw & 0x2000:  # Linux STA_NANO; otherwise offset was microseconds.
            require(kernel.adjustment_offset_ns % 1000 == 0)
    report["scope"] = "Local clock and kernel state only; not NTP peer offset, certified UTC, or FPGA timing"
    return report
