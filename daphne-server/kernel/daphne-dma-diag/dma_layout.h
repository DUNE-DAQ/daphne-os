/* SPDX-License-Identifier: GPL-2.0 */
/* Shared, hardware-free validation used by the actual driver and unit tests. */
#ifndef DAPHNE_DMA_LAYOUT_H
#define DAPHNE_DMA_LAYOUT_H
#include <linux/errno.h>
#include "daphne_dma_uapi.h"

struct daphne_dma_layout {
 __u64 packet_bytes, requested_bytes, allocated_bytes;
 __u32 blocks_per_packet, blocks;
};

static inline int daphne_dma_layout(const struct daphne_dma_config *c,
                                    __u64 page_size, struct daphne_dma_layout *out)
{
 __u64 packet, blocks, allocated = 0, segment;
 __u32 i;
 if (c->abi != DAPHNE_DMA_ABI || !c->beats || !c->packets ||
     !c->rate_num || !c->rate_den || c->rate_num > c->rate_den ||
     !c->timeout_ms || c->timeout_ms > 3600000 || (c->expected_build_id & 0xf0000000U) ||
     page_size < 4096 || page_size > 65536 || (page_size & (page_size - 1)))
  return -EINVAL;
 packet = (__u64)c->beats * 16;
 if (packet > DAPHNE_DMA_MAX_PACKET_BYTES || (__u64)c->packets > ~(__u64)0 / packet)
  return -EOVERFLOW;
 blocks = (packet + DAPHNE_DMA_CHUNK_BYTES - 1) / DAPHNE_DMA_CHUNK_BYTES;
 if (blocks * c->packets > DAPHNE_DMA_MAX_BLOCKS)
  return -E2BIG;
 for (i = 0; i < blocks; ++i) {
  segment = packet - (__u64)i * DAPHNE_DMA_CHUNK_BYTES;
  if (segment > DAPHNE_DMA_CHUNK_BYTES)
   segment = DAPHNE_DMA_CHUNK_BYTES;
  allocated += (segment + 2 * DAPHNE_DMA_GUARD_BYTES + page_size - 1) & ~(page_size - 1);
 }
 out->packet_bytes = packet;
 out->requested_bytes = packet * c->packets;
 out->allocated_bytes = allocated * c->packets;
 out->blocks_per_packet = blocks;
 out->blocks = blocks * c->packets;
 return 0;
}
#endif
