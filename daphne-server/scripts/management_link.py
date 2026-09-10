"""Independent management-link health evaluation; never formats private identity."""

SPECS = (
    ("operstate", "1", "text_value", 0), ("carrier", "1", "flag_value", 0),
    ("speed", "Mbit/s", "unsigned_value", 0), ("duplex", "1", "text_value", 0),
    ("mtu", "B", "unsigned_value", 0), ("statistics/rx_bytes", "B", "unsigned_value", 64),
    ("statistics/rx_packets", "packet", "unsigned_value", 64),
    ("statistics/rx_errors", "packet", "unsigned_value", 64),
    ("statistics/rx_dropped", "packet", "unsigned_value", 64),
    ("statistics/tx_bytes", "B", "unsigned_value", 64),
    ("statistics/tx_packets", "packet", "unsigned_value", 64),
    ("statistics/tx_errors", "packet", "unsigned_value", 64),
    ("statistics/tx_dropped", "packet", "unsigned_value", 64),
    ("carrier_changes", "count", "unsigned_value", 32),
)


def check_link(link, h, require_all_good=False):
    """Check typed metrics and reported bracket; output only validated values.

    This validates the wire contract, not independent kernel readback or proof
    that two equal samples exclude a transient link change between them.
    """
    def require(ok):
        if not ok:
            raise RuntimeError("Invalid management-link telemetry; private details suppressed")

    require(link.quality in (h.MEASUREMENT_GOOD, h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_ERROR) and bool(link.detail))
    good = link.quality == h.MEASUREMENT_GOOD
    require(len(link.observations) == 14 and {i.metric for i in link.observations} == set(range(1, 15)))
    if good:
        require(link.HasField("interface_index") and 0 < link.interface_index <= 0x7fffffff
                and 0 < link.acquisition_started_monotonic_ns <= link.observed_monotonic_ns
                and bool(link.observed_host_unix_ns))
    else:
        require(not link.HasField("interface_index") and not link.observed_monotonic_ns
                and not link.observed_host_unix_ns and not link.link_state_bracket_verified)
    report, selected = {}, {}
    for item in link.observations:
        path, unit, kind, width = SPECS[item.metric - 1]
        require((item.source, item.unit, item.counter_width_bits) == (path, unit, width) and bool(item.detail))
        require(item.quality in (h.MEASUREMENT_GOOD, h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_ERROR))
        selected[item.metric] = item
        available = item.quality == h.MEASUREMENT_GOOD
        value = None
        if available:
            require(good and item.WhichOneof("value") == kind
                    and link.acquisition_started_monotonic_ns <= item.acquisition_started_monotonic_ns
                    <= item.observed_monotonic_ns <= link.observed_monotonic_ns and bool(item.observed_host_unix_ns))
            value = getattr(item, kind)
            if item.metric == h.MANAGEMENT_LINK_OPERSTATE:
                require(value in ("unknown", "notpresent", "down", "lowerlayerdown", "testing", "dormant", "up"))
            elif item.metric == h.MANAGEMENT_LINK_DUPLEX:
                require(value in ("half", "full"))
            elif item.metric == h.MANAGEMENT_LINK_SPEED_MBPS:
                require(0 < value < 0xffffffff)
            elif item.metric == h.MANAGEMENT_LINK_MTU_BYTES:
                require(0 < value <= 0xffffffff)
            elif width:
                require(0 <= value < 1 << width)
        else:
            require(item.WhichOneof("value") is None and not item.observed_monotonic_ns and not item.observed_host_unix_ns)
        report[h.ManagementLinkMetric.Name(item.metric)] = {
            "quality": h.MeasurementQuality.Name(item.quality), "value": value, "unit": unit}
    state, carrier = selected[h.MANAGEMENT_LINK_OPERSTATE], selected[h.MANAGEMENT_LINK_CARRIER]
    if link.link_state_bracket_verified:
        require(state.quality == carrier.quality == h.MEASUREMENT_GOOD)
    negotiation = (link.link_state_bracket_verified and state.text_value == "up" and carrier.flag_value)
    if not negotiation:
        require(all(selected[n].quality != h.MEASUREMENT_GOOD for n in (h.MANAGEMENT_LINK_SPEED_MBPS, h.MANAGEMENT_LINK_DUPLEX)))
    if require_all_good:
        require(good and all(i.quality == h.MEASUREMENT_GOOD for i in link.observations) and negotiation)
    return {"quality": h.MeasurementQuality.Name(link.quality), "metrics": report,
            "observed_monotonic_ns": link.observed_monotonic_ns,
            "link_state_bracket_verified": link.link_state_bracket_verified,
            "counter_epoch": "unobserved", "scope": "management NIC only; not reachability or Hermes delivery"}


def health_state(network, h, now):
    unknown, passed, failed = h.HEALTH_CHECK_UNKNOWN, h.HEALTH_CHECK_PASS, h.HEALTH_CHECK_FAIL

    def fresh(quality, observed):
        return quality == h.MEASUREMENT_GOOD and 0 < observed <= now and now - observed <= 5_000_000_000

    if not fresh(network.quality, network.observed_monotonic_ns) or not network.HasField("present"):
        return unknown
    if (not network.present or (network.HasField("interface_up") and not network.interface_up)
            or (network.HasField("running_flag") and not network.running_flag)):
        return failed
    if not network.HasField("interface_up") or not network.HasField("running_flag"):
        return unknown
    link = network.link
    if (not network.HasField("interface_index") or not link.HasField("interface_index")
            or not network.interface_index or link.interface_index != network.interface_index
            or not link.link_state_bracket_verified or not fresh(link.quality, link.observed_monotonic_ns)
            or not 0 < network.acquisition_started_monotonic_ns <= link.acquisition_started_monotonic_ns
            <= link.observed_monotonic_ns <= network.observed_monotonic_ns):
        return unknown
    selected = {}
    for item in link.observations:
        if item.metric not in (h.MANAGEMENT_LINK_OPERSTATE, h.MANAGEMENT_LINK_CARRIER):
            continue
        if (item.metric in selected or not fresh(item.quality, item.observed_monotonic_ns)
                or not link.acquisition_started_monotonic_ns <= item.acquisition_started_monotonic_ns
                <= item.observed_monotonic_ns <= link.observed_monotonic_ns):
            return unknown
        selected[item.metric] = item
    state, carrier = selected.get(h.MANAGEMENT_LINK_OPERSTATE), selected.get(h.MANAGEMENT_LINK_CARRIER)
    if (state is None or carrier is None or state.WhichOneof("value") != "text_value"
            or carrier.WhichOneof("value") != "flag_value"
            or state.text_value not in ("unknown", "notpresent", "down", "lowerlayerdown", "testing", "dormant", "up")):
        return unknown
    if not carrier.flag_value:
        return failed
    if state.text_value == "unknown":
        return unknown
    return passed if state.text_value == "up" else failed
