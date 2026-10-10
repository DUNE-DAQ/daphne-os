/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef DAPHNE_AFE_DMA_UAPI_H
#define DAPHNE_AFE_DMA_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>
#define DAPHNE_AFE_DMA_ABI 1U
#define DAPHNE_AFE_PATTERN 1U
#define DAPHNE_AFE_ALIGNED 2U
enum daphne_afe_dma_state {
 DAPHNE_AFE_IDLE, DAPHNE_AFE_PREPARED, DAPHNE_AFE_RUNNING,
 DAPHNE_AFE_COMPLETE, DAPHNE_AFE_ABORTED, DAPHNE_AFE_ERROR, DAPHNE_AFE_QUARANTINED
};
struct daphne_afe_dma_config {
 __u32 abi, flags, length, count, timeout_ms, expected_build_id;
 __aligned_u64 channel_mask;
};
struct daphne_afe_dma_status {
 __u32 abi, state;
 __s32 error;
 __u32 flags, active_routes, hardware_status, hardware_error, guards_ok;
 __u32 build_id, format, captured_ticks, reserved;
 __aligned_u64 channel_mask, timestamp, allocated_bytes, start_ns, end_ns;
 __aligned_u64 valid_bytes[3], transfer_bytes[3], received_bytes[3], accepted_beats[3];
 __u32 dma_status[3], dma_control[3];
};
#define DAPHNE_AFE_PREPARE _IOW('A',0x40,struct daphne_afe_dma_config)
#define DAPHNE_AFE_START _IO('A',0x41)
#define DAPHNE_AFE_STATUS _IOR('A',0x42,struct daphne_afe_dma_status)
#define DAPHNE_AFE_SELECT_ROUTE _IOW('A',0x43,__u32)
#define DAPHNE_AFE_ABORT _IO('A',0x44)
#endif
