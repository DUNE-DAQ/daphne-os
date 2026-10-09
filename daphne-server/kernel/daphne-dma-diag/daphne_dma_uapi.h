/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef DAPHNE_DMA_UAPI_H
#define DAPHNE_DMA_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>

#define DAPHNE_DMA_ABI 1U
#define DAPHNE_DMA_CHUNK_BYTES (4U * 1024U * 1024U)
#define DAPHNE_DMA_MAX_PACKET_BYTES (256U * 1024U * 1024U)
#define DAPHNE_DMA_MAX_BLOCKS 16384U
#define DAPHNE_DMA_GUARD_BYTES 64U
#define DAPHNE_DMA_GUARD_VALUE 0xa5U

enum daphne_dma_state {
 DAPHNE_DMA_IDLE, DAPHNE_DMA_PREPARED, DAPHNE_DMA_RUNNING,
 DAPHNE_DMA_STOPPING, DAPHNE_DMA_COMPLETE, DAPHNE_DMA_STOPPED,
 DAPHNE_DMA_ABORTED, DAPHNE_DMA_ERROR, DAPHNE_DMA_QUARANTINED
};
struct daphne_dma_config {
 __u32 abi, beats, packets, seed;
 __u32 rate_num, rate_den, timeout_ms, expected_build_id;
};
struct daphne_dma_status {
 __u32 abi, path, state;
 __s32 error;
 __u32 magic, gateware_abi, variant, build_id;
 __u32 capabilities, producer_status, producer_packets, completed_packets;
 __u32 dma_control, dma_status, blocks, guards_ok;
 __aligned_u64 allocated_bytes, requested_bytes, received_bytes;
 __aligned_u64 accepted_beats, start_ns, end_ns;
};
struct daphne_dma_block_info {
 __u32 abi, index, length, reserved;
 __aligned_u64 dma_address, logical_offset;
};
#define DAPHNE_DMA_PREPARE _IOW('D', 0x30, struct daphne_dma_config)
#define DAPHNE_DMA_START _IO('D', 0x31)
#define DAPHNE_DMA_STOP _IO('D', 0x32)
#define DAPHNE_DMA_ABORT _IO('D', 0x33)
#define DAPHNE_DMA_STATUS _IOR('D', 0x34, struct daphne_dma_status)
#define DAPHNE_DMA_BLOCK _IOWR('D', 0x35, struct daphne_dma_block_info)
#endif
