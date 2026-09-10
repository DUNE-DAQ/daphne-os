"""Independent management-link health evaluation; never formats private identity."""


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
