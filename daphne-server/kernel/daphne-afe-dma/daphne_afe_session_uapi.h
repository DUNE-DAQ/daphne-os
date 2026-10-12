/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef DAPHNE_AFE_SESSION_UAPI_H
#define DAPHNE_AFE_SESSION_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>
#define DAPHNE_AFE_SESSION_ABI 1U
#define DAPHNE_AFE_SESSION_BATCH 16U
#define DAPHNE_AFE_SESSION_AUTO 4U
#define DAPHNE_AFE_SESSION_READ_MAX (1U << 20)
enum daphne_afe_session_state {
 DAPHNE_SESSION_IDLE, DAPHNE_SESSION_PREPARED, DAPHNE_SESSION_RUNNING,
 DAPHNE_SESSION_DRAINING, DAPHNE_SESSION_COMPLETE, DAPHNE_SESSION_ABORTED,
 DAPHNE_SESSION_ERROR, DAPHNE_SESSION_QUARANTINED
};
/* PREPARE is in/out. Zero ring selects bounded default; zero budget uses the
 * module limit. slots and session must be zero on input. No allocation by N.
 */
struct daphne_afe_session_config {
 __u32 abi, flags, length, pretrigger, period_ticks, source, expected_build_id, reserved;
 __u32 trigger_timeout_ms, pressure_timeout_ms;
 __aligned_u64 channel_mask, target_events, budget_bytes;
 __u32 ring_ticks[3], slots;
 __aligned_u64 session;
};
struct daphne_afe_event_id {
 __aligned_u64 session, sequence, generation;
 __u32 slot, reserved;
};
struct daphne_afe_session_event {
 struct daphne_afe_event_id id;
 __aligned_u64 channel_mask, first_cursor, fence_end, trigger_index, timestamp, segment;
 __aligned_u64 valid_bytes[3];
 __u32 length, pretrigger, source, timestamp_valid, hardware_error, reserved;
 /* Publication-time cached counters, not trigger-time snapshots. */
 __aligned_u64 ignored[4];
};
struct daphne_afe_session_status {
 __u32 abi, state;
 __s32 error;
 __u32 flags, hardware_error, guards_ok, slots, active_routes;
 __aligned_u64 session, target_events, accepted, completed, delivered, released;
 __aligned_u64 cursor, sample_index, segment, pauses, ignored[4];
 __aligned_u64 allocated_bytes, start_ns, end_ns, starts, stops;
};
struct daphne_afe_session_batch {
 __u32 abi, capacity, count, reserved;
 __aligned_u64 entries; /* event[] for GET, ID[] for RELEASE; compat-safe */
};
struct daphne_afe_session_read {
 struct daphne_afe_event_id id;
 __u32 abi, route, length, copied;
 __aligned_u64 offset, buffer;
};
struct daphne_afe_session_caps {
 __u32 abi, features, slots, batch_max, read_max, format, period_min, period_max;
 __aligned_u64 pool_max, route_max, target_max;
};
/* Additive extension. Existing A40..A48 layouts and behavior remain intact. */
#define DAPHNE_AFE_SESSION_CAPS _IOR('A',0x50,struct daphne_afe_session_caps)
#define DAPHNE_AFE_SESSION_PREPARE _IOWR('A',0x51,struct daphne_afe_session_config)
#define DAPHNE_AFE_SESSION_START _IO('A',0x52)
#define DAPHNE_AFE_SESSION_STATUS _IOR('A',0x53,struct daphne_afe_session_status)
#define DAPHNE_AFE_SESSION_GET _IOWR('A',0x54,struct daphne_afe_session_batch)
#define DAPHNE_AFE_SESSION_READ _IOWR('A',0x55,struct daphne_afe_session_read)
#define DAPHNE_AFE_SESSION_RELEASE _IOWR('A',0x56,struct daphne_afe_session_batch)
#define DAPHNE_AFE_SESSION_CANCEL _IO('A',0x57)
#define DAPHNE_AFE_SESSION_TRIGGER _IO('A',0x58)
#endif
