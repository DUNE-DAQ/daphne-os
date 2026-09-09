#include "server_controller/current_monitor.hpp"
#include "ADS1261.hpp"

namespace daphne_sc {
CurrentChannelSelection current_request_selection(const daphne::cmd_readCurrentMonitor& request) {
  if (!request.has_physical_channel() || request.currentmonitorchannel() != 0)
    throw std::invalid_argument("Set physical_channel (0..39) and leave legacy currentMonitorChannel unset; old ADC-input addressing is not a physical-channel measurement");
  return current_channel_selection(request.physical_channel());
}
void set_current_sample(daphne::cmd_readCurrentMonitor_response& r, const ADS1261Sample& s) {
  r.set_adc_id(s.id);
  r.set_adc_status(s.status);
  r.set_adc_input_mux(s.input_mux);
  r.set_raw_code(s.raw_code);
  r.set_observed_monotonic_ns(s.observed_monotonic_ns);
  r.set_pga_gain(ADS1261::gain);
  r.set_pga_bypassed(ADS1261::pga_bypassed);
  r.set_nominal_reference_volts(ADS1261::reference_volts);
  r.set_saturated(s.saturated);
  r.set_success(false);
  r.set_currentvalue(0);
  r.clear_differential_volts();
  r.set_current_quality(daphne::CURRENT_MONITOR_UNAVAILABLE);
  r.clear_current_amperes();
  // Internal clock, unlocked registers, no CRC/reference/PGA/reset faults, new data.
  if (s.status != 4 || !s.observed_monotonic_ns) {
    r.set_quality(daphne::CURRENT_MONITOR_ERROR);
    r.set_message("ADC sample has status faults, non-internal clock or no new-data indication; raw code is diagnostic only");
  } else if (s.saturated) {
    r.set_quality(daphne::CURRENT_MONITOR_SATURATED);
    r.set_message("ADC full-scale code; no usable voltage/current measurement");
  } else {
    r.set_quality(daphne::CURRENT_MONITOR_GOOD);
    r.set_success(true);
    r.set_currentvalue(static_cast<uint32_t>(s.raw_code));
    r.set_differential_volts(s.differential_volts);
    r.set_message("CRC-checked fresh ADS1261 differential conversion; nominal ADC scaling, not calibrated SiPM current");
  }
}
}  // namespace daphne_sc
