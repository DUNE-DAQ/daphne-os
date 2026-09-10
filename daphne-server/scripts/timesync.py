"""Check timesync1 reporting without promoting history into a current UTC claim."""
import ipaddress
import re

SOURCE = "local system bus:org.freedesktop.timesync1.Manager:GetAll"
META_FIELDS = ("selected_name_present", "selected_address_present", "poll_interval_us", "poll_minimum_us",
               "poll_maximum_us", "root_distance_maximum_us", "processed_packet_count", "frequency_scaled_ppm")
SAMPLE_FIELDS = ("leap", "version", "mode", "stratum", "precision_exponent", "root_delay_us", "root_dispersion_us",
                 "origin_unix_us", "receive_unix_us", "transmit_unix_us", "destination_unix_us", "ignored_spike",
                 "jitter_us", "offset_ns", "round_trip_delay_ns")


def require(value):
    if not value:
        raise RuntimeError("Invalid or stale timesync observation; private details suppressed")


def hostname(value):
    require(0 < len(value) <= 253)
    try:
        ipaddress.ip_address(value)
        return
    except ValueError:
        pass
    require(all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in value.rstrip('.').split('.')) and not value.endswith('..'))


def check_timesync(status, high, *, now_monotonic_ns, private_requested=False, require_available=False):
    require(status.HasField("host_time") and status.host_time.HasField("timesync") and now_monotonic_ns > 0)
    item = status.host_time.timesync
    require(item.source == SOURCE and 0 < len(item.detail) <= 512)
    require(item.quality in (high.MEASUREMENT_GOOD, high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR))
    good = item.quality == high.MEASUREMENT_GOOD
    require(good or not require_available)
    for field in META_FIELDS:
        require(item.HasField(field) == good)
    require(item.HasField("last_sample"))
    if good:
        require(item.owner_bracket_verified and bool(re.fullmatch(r"[0-9a-f]{32}", item.bus_id)))
        require(len(item.unique_owner) <= 80 and bool(re.fullmatch(r":[0-9]+(?:\.[0-9]+)+", item.unique_owner)))
        require(0 < item.acquisition_started_monotonic_ns <= item.observed_monotonic_ns <= now_monotonic_ns)
        require(item.observed_monotonic_ns - item.acquisition_started_monotonic_ns <= 2_000_000_000)
        require(now_monotonic_ns - item.observed_monotonic_ns <= 5_000_000_000)
        require(item.details_included == private_requested)
        require(item.HasField("selected_server_name") == (private_requested and item.selected_name_present))
        require(item.HasField("selected_server_address") == (private_requested and item.selected_address_present))
        if item.HasField("selected_server_name"):
            hostname(item.selected_server_name)
        if item.HasField("selected_server_address"):
            require('%' not in item.selected_server_address and len(item.selected_server_address) <= 45)
            try:
                ipaddress.ip_address(item.selected_server_address)
            except ValueError:
                require(False)
        require(0 < item.poll_minimum_us <= item.poll_maximum_us and item.root_distance_maximum_us > 0)
        require(item.poll_interval_us == 0 or item.poll_minimum_us <= item.poll_interval_us <= item.poll_maximum_us)
        if status.host_time.HasField("kernel") and status.host_time.kernel.quality == high.MEASUREMENT_GOOD:
            require(status.host_time.kernel.observed_monotonic_ns <= item.acquisition_started_monotonic_ns)
    else:
        require(not item.observed_monotonic_ns and not item.owner_bracket_verified and not item.details_included)
        require(not item.bus_id and not item.unique_owner)
        require(not item.HasField("selected_server_name") and not item.HasField("selected_server_address"))
        require(item.acquisition_started_monotonic_ns <= now_monotonic_ns)
    sample = item.last_sample
    require(sample.quality in (high.MEASUREMENT_GOOD, high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR))
    require(0 < len(sample.detail) <= 512)
    usable = sample.quality == high.MEASUREMENT_GOOD
    require(not usable or (good and item.processed_packet_count > 0))
    require(sample.quality != high.MEASUREMENT_ERROR or (good and item.processed_packet_count > 0))
    if good and item.processed_packet_count > 0:
        require(sample.quality != high.MEASUREMENT_UNAVAILABLE)
    for field in SAMPLE_FIELDS:
        require(sample.HasField(field) == usable)
    if usable:
        require(sample.leap in range(3) and sample.version in (3, 4) and sample.mode == 4 and 1 <= sample.stratum <= 15)
        require(-128 <= sample.precision_exponent <= 127)
        t1, t2, t3, t4 = (getattr(sample, key + "_unix_us") for key in ("origin", "receive", "transmit", "destination"))
        require(all(0 < t <= ((1 << 63) - 1) // 1000 for t in (t1, t2, t3, t4)))
        delay, offset = (t4 - t1) - (t3 - t2), ((t2 - t1) + (t3 - t4)) * 500
        require(t4 >= t1 and t3 >= t2 and 0 <= delay * 1000 <= (1 << 64) - 1)
        require(-(1 << 63) <= offset <= (1 << 63) - 1)
        require(sample.offset_ns == offset and sample.round_trip_delay_ns == delay * 1000)
    require(sample.age_bound_quality in (high.MEASUREMENT_GOOD, high.MEASUREMENT_UNAVAILABLE))
    bound = sample.age_bound_quality == high.MEASUREMENT_GOOD
    require(not bound or usable)
    require(sample.HasField("not_before_monotonic_ns") == bound and sample.HasField("maximum_age_ns") == bound)
    if bound:
        require(0 < sample.not_before_monotonic_ns <= item.acquisition_started_monotonic_ns)
        require(sample.maximum_age_ns == item.observed_monotonic_ns - sample.not_before_monotonic_ns)
    return {
        "quality": high.MeasurementQuality.Name(item.quality), "service_observed": good,
        "private_details_included": item.details_included,
        "observed_monotonic_ns": item.observed_monotonic_ns,
        **{field: getattr(item, field) if good else None for field in META_FIELDS},
        "sample_quality": high.MeasurementQuality.Name(sample.quality),
        "historical_sample": {field: getattr(sample, field) if usable else None for field in SAMPLE_FIELDS},
        "sample_age_upper_bound_ns": sample.maximum_age_ns if bound else None,
        "scope": "Service and historical NTP data; no selected-peer/sample-origin binding, present offset or verified UTC claim",
    }
