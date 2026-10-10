#pragma once
#include "daphneV3_high_level_confs.pb.h"
#include "daphneV3_low_level_confs.pb.h"

namespace daphne_sc {
template<class T> uint32_t single_afe_mask(const std::string& bytes) {
  T request;
  if (!request.ParseFromString(bytes) || request.afeblock() >= 5) return 31;
  return 1U << request.afeblock();
}
inline uint32_t affected_afe_mask(daphne::MessageTypeV2 type, const std::string& bytes) {
  using namespace daphne;
  switch (type) {
    case MT2_WRITE_AFE_REG_REQ: return single_afe_mask<cmd_writeAFEReg>(bytes);
    case MT2_WRITE_AFE_VGAIN_REQ: return single_afe_mask<cmd_writeAFEVGAIN>(bytes);
    case MT2_WRITE_AFE_BIAS_SET_REQ: return single_afe_mask<cmd_writeAFEBiasSet>(bytes);
    case MT2_WRITE_TRIM_ALL_AFE_REQ: return single_afe_mask<cmd_writeTrim_allAFE>(bytes);
    case MT2_WRITE_OFFSET_ALL_AFE_REQ: return single_afe_mask<cmd_writeOFFSET_allAFE>(bytes);
    case MT2_WRITE_AFE_ATTENUATION_REQ: return single_afe_mask<cmd_writeAFEAttenuation>(bytes);
    case MT2_WRITE_AFE_FUNCTION_REQ: return single_afe_mask<cmd_writeAFEFunction>(bytes);
    case MT2_WRITE_AFE_BIAS_CONTROLLED_SET_REQ: {
      cmd_writeAFEBiasControlledSet r;
      return r.ParseFromString(bytes) && r.afe_block() < 5 ? 1U << r.afe_block() : 31;
    }
    case MT2_WRITE_TRIM_CH_REQ: {
      cmd_writeTrim_singleChannel r;
      return r.ParseFromString(bytes) && r.trimchannel() < 40 ? 1U << (r.trimchannel() / 8) : 31;
    }
    case MT2_WRITE_OFFSET_CH_REQ: {
      cmd_writeOFFSET_singleChannel r;
      return r.ParseFromString(bytes) && r.offsetchannel() < 40 ? 1U << (r.offsetchannel() / 8) : 31;
    }
    case MT2_WRITE_AFE_TIMING_REQ: {
      WriteAfeTimingRequest r; uint32_t mask = 0;
      if (!r.ParseFromString(bytes)) return 31;
      for (const auto& a : r.settings()) { if (a.afe() >= 5) return 31; mask |= 1U << a.afe(); }
      return mask ? mask : 31;
    }
    default: return 31; // Global clocks/reset/power or unknown operation.
  }
}
}
