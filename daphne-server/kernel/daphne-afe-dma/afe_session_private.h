/* SPDX-License-Identifier: GPL-2.0 */
#ifndef AFE_SESSION_PRIVATE_H
#define AFE_SESSION_PRIVATE_H
#include "afe_session_contract.h"
struct afe_session_slot {
 struct daphne_afe_session_event event;
 unsigned int readers;
 enum afe_slot_state state;
};
struct afe_session {
 struct daphne_afe_session_config config;
 struct daphne_afe_session_status status;
 struct afe_session_slot slot[32];
 struct delayed_work service;
 struct work_struct stop;
 struct afe_job *job;
 unsigned int readers;
 bool started,stopping,quiescent,cancel_requested,get_busy;
 __u64 collected,release_requested;
 __u64 last_accepted,last_progress_ns,pressure_since_ns;
};
static void session_service(struct work_struct *work);
static void session_stop(struct work_struct *work);
static void session_cancel(struct afe_job *p,int error);
static int session_close(struct afe_job *p);
#endif
