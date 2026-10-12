/* SPDX-License-Identifier: GPL-2.0
 * Compile-only ABI proof; no libc or executable needed for 32-bit compat.
 */
#include "daphne_afe_dma_uapi.h"
#include "daphne_afe_session_uapi.h"
#define AFE_OFFSET(t,m) __builtin_offsetof(t,m)
_Static_assert(sizeof(struct daphne_afe_dma_config)==32,"finite config");
_Static_assert(sizeof(struct daphne_afe_dma_status)==208,"finite status");
_Static_assert(sizeof(struct daphne_afe_trigger_config)==48,"trigger config");
_Static_assert(sizeof(struct daphne_afe_trigger_status)==272,"trigger status");
_Static_assert(sizeof(struct daphne_afe_session_config)==88,"session config");
_Static_assert(sizeof(struct daphne_afe_event_id)==32,"event ID");
_Static_assert(sizeof(struct daphne_afe_session_event)==160,"event");
_Static_assert(sizeof(struct daphne_afe_session_status)==184,"session status");
_Static_assert(sizeof(struct daphne_afe_session_caps)==56,"caps");
_Static_assert(sizeof(struct daphne_afe_session_batch)==24,"batch");
_Static_assert(sizeof(struct daphne_afe_session_read)==64,"read");
_Static_assert(AFE_OFFSET(struct daphne_afe_session_config,session)==80,"config tail");
_Static_assert(AFE_OFFSET(struct daphne_afe_session_read,buffer)==56,"read pointer");
_Static_assert(AFE_OFFSET(struct daphne_afe_session_batch,entries)==16,"batch pointer");
_Static_assert(_IOC_SIZE(DAPHNE_AFE_SESSION_READ)==64,"read ioctl");
_Static_assert(_IOC_SIZE(DAPHNE_AFE_SESSION_PREPARE)==88,"prepare ioctl");
_Static_assert(_IOC_NR(DAPHNE_AFE_ARM)==0x46,"existing ARM ioctl");
