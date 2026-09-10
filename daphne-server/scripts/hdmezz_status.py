"""Validate cache provenance before displaying mezzanine telemetry. No hardware I/O."""
import math

VALUE_FIELDS = ("power5V", "power3V3", "measured_voltage5V", "measured_voltage3V3",
                "measured_current5V", "measured_current3V3", "measured_power5V", "measured_power3V3")


def check_monitoring_status(response, low, expected_afe=None, roundtrip_ns=0):
    if not isinstance(roundtrip_ns, int) or roundtrip_ns < 0:
        raise ValueError("Invalid request duration")
    if response.afeBlock > 4 or (expected_afe is not None and response.afeBlock != expected_afe):
        raise ValueError("Unexpected mezzanine block in status response")
    quality = getattr(response, "monitor_quality", 0)
    if not quality:
        return {"available": False, "quality": "legacy-unqualified", "values": None,
                "alerts": [None, None], "driver_state": None,
                "scope": "Old response/schema has no coherent sample provenance"}
    known = (low.HDMEZZ_MONITOR_GOOD, low.HDMEZZ_MONITOR_UNAVAILABLE, low.HDMEZZ_MONITOR_ERROR,
             low.HDMEZZ_MONITOR_INVALID, low.HDMEZZ_MONITOR_STALE)
    if quality not in known:
        raise ValueError("Unknown mezzanine monitoring quality")
    good = quality == low.HDMEZZ_MONITOR_GOOD
    stale = quality == low.HDMEZZ_MONITOR_STALE
    if bool(response.success) != good:
        raise ValueError("Inconsistent monitoring success/quality")
    start, end, now = (response.acquisition_started_monotonic_ns, response.observed_monotonic_ns,
                       response.state_observed_monotonic_ns)
    state = None
    if response.driver_state_available:
        state = {"enabled": response.block_enabled, "configured": response.driver_configured,
                 "observed_monotonic_ns": now}
        if state["configured"] and not state["enabled"]:
            raise ValueError("Configured block is not enabled")
    elif response.block_enabled or response.driver_configured or now:
        raise ValueError("Missing driver has fabricated state")
    if good or stale:
        if (not state or not state["enabled"] or not state["configured"] or not response.sample_attempt or
                not start or end < start or end - start > 100_000_000 or not now or now < end or
                response.last_good_monotonic_ns != end):
            raise ValueError("Invalid monitoring acquisition/state timestamps or provenance")
        if stale != (now - end > 5_000_000_000):
            raise ValueError("Monitoring quality disagrees with sample age")
    elif end:
        raise ValueError("Failed sample contains a completed measurement timestamp")
    alerts = []
    for name, legacy in (("alert_history_5V", "alert_5V"), ("alert_history_3V3", "alert_3V3")):
        present = response.HasField(name)
        if response.HasField(legacy) != present:
            raise ValueError("Alert presence disagrees with its history")
        if not present:
            alerts.append(None)
            continue
        history = getattr(response, name)
        if history.mask_enable_raw > 0xFFFF or getattr(response, legacy) != history.software_latched:
            raise ValueError("Invalid alert history or latch mapping")
        # A raw asserted AFF must be retained even on a later power-write failure.
        if history.mask_enable_raw & 0x10 and not history.software_latched:
            raise ValueError("Hardware alert evidence was discarded")
        alerts.append({"latched": history.software_latched, "mask_enable_raw": history.mask_enable_raw,
                       "observed_monotonic_ns": history.observed_monotonic_ns})
    values = None
    if good:
        if not response.active_configuration_verified or not all(response.HasField(n) for n in VALUE_FIELDS):
            raise ValueError("GOOD sample lacks values or checked configuration")
        values = {name: getattr(response, name) for name in VALUE_FIELDS}
        if any(not math.isfinite(values[n]) for n in VALUE_FIELDS[2:]):
            raise ValueError("Non-finite measurement")
        if any(values[n] < 0 for n in VALUE_FIELDS[2:] if "current" not in n):
            raise ValueError("Invalid voltage or power sign")
        for alert in alerts:
            if (not alert or not start <= alert["observed_monotonic_ns"] <= end or
                    alert["mask_enable_raw"] & 0xFFE7 != 0x8001 or
                    alert["latched"] != bool(alert["mask_enable_raw"] & 0x10)):
                raise ValueError("GOOD sample lacks fresh valid device status")
        if alerts[0]["observed_monotonic_ns"] > alerts[1]["observed_monotonic_ns"]:
            raise ValueError("Alert timestamps run backward")
        tripped = any(a["latched"] for a in alerts)
        off = not values["power5V"] and not values["power3V3"]
        if (response.power_requests_off_confirmed != off or response.protective_action_attempted != tripped or
                (tripped and not off)):
            raise ValueError("Inconsistent protective action/request readback")
    elif (any(response.HasField(n) for n in VALUE_FIELDS) or response.active_configuration_verified or
          response.power_requests_off_confirmed):
        raise ValueError("Unavailable sample contains partial/old numerical or power observations")
    # The server's clock cannot be compared with the client's clock. Full request
    # duration is a conservative bound on transit time since the server snapshot.
    client_stale = good and now - end + roundtrip_ns > 5_000_000_000
    return {"available": good and not client_stale,
            "quality": "CLIENT_STALE" if client_stale else low.HDMezzMonitorQuality.Name(quality),
            "values": None if client_stale else values,
            "alerts": alerts, "driver_state": state, "sample_attempt": response.sample_attempt,
            "acquisition_started_monotonic_ns": start, "observed_monotonic_ns": end,
            "state_observed_monotonic_ns": now, "last_good_monotonic_ns": response.last_good_monotonic_ns,
            "age_ns": now - end + roundtrip_ns if (good or stale) else None,
            "protective_action_attempted": response.protective_action_attempted,
            "scope": "Sequential cached sample; TCA requests are not physical power; alert times are historical, not refreshed by RPC"}
