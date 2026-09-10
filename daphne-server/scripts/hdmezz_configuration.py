"""Validate the additive mezzanine calibration response without hardware access."""
import math


def check_configuration_readback(response, low):
    quality = getattr(response, "calibration_readback_quality", 0)
    if not quality:
        return {"available": False, "quality": "legacy-unqualified",
                "scope": "Old response/schema has no hardware-readback provenance"}
    known = (low.HDMEZZ_READBACK_GOOD, low.HDMEZZ_READBACK_UNAVAILABLE,
             low.HDMEZZ_READBACK_ERROR, low.HDMEZZ_READBACK_INVALID)
    if quality not in known:
        raise ValueError("Unknown calibration readback quality")
    available = quality == low.HDMEZZ_READBACK_GOOD
    actual = [response.shunt_cal_5V, response.shunt_cal_3V3]
    requested = [response.requested_shunt_cal_5V, response.requested_shunt_cal_3V3]
    if response.afeBlock > 4 or bool(response.success) != available:
        raise ValueError("Inconsistent block or success/quality metadata")
    if available:
        start, end = response.acquisition_started_monotonic_ns, response.observed_monotonic_ns
        if (not response.block_enabled or not response.requested_settings_available or
                not start or end < start or end - start > 100_000_000 or
                any(not 0 <= code <= 0x7FFF for code in actual)):
            raise ValueError("Invalid calibration acquisition evidence")
        if response.calibration_matches_requested != (actual == requested):
            raise ValueError("Calibration comparison disagrees with the reported codes")
    elif (actual != [0, 0] or response.observed_monotonic_ns or
          response.calibration_matches_requested):
        raise ValueError("Unavailable readback contains stale or partial values")
    settings = None
    if response.requested_settings_available:
        names = ("r_shunt_5V", "r_shunt_3V3", "max_current_5V_scale", "max_current_3V3_scale",
                 "max_current_5V_shutdown", "max_current_3V3_shutdown", "max_power_5V",
                 "max_power_3V3", "current_lsb_5V", "current_lsb_3V3")
        settings = {name: getattr(response, name) for name in names}
        if any(not math.isfinite(value) or value <= 0 for value in settings.values()):
            raise ValueError("Invalid requested/derived configuration cache")
        if any(not 1 <= code <= 0x7FFF for code in requested):
            raise ValueError("Invalid requested calibration code")
    return {
        "available": available, "quality": low.HDMezzReadbackQuality.Name(quality),
        "block_enabled": response.block_enabled, "driver_configured": response.driver_configured,
        "actual_calibration_5v_ce": actual if available else None,
        "requested_calibration_5v_ce": requested if settings is not None else None,
        "calibration_matches_requested": response.calibration_matches_requested if available else None,
        "requested_derived_settings": settings,
        "acquisition_started_monotonic_ns": response.acquisition_started_monotonic_ns,
        "observed_monotonic_ns": response.observed_monotonic_ns if available else None,
        "scope": "Sequential register pair; driver_configured is cached programming history, not fresh protection state or metrology",
    }
