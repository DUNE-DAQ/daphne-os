/* SPDX-License-Identifier: GPL-2.0
 * Execute the production service function with deterministic MMIO/work mocks.
 * This covers final-publication ordering, not Linux concurrency or hardware.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint64_t u64;
#define BIT(n) (1U<<(n))
#define S_FLAGS 0x218
#define DAPHNE_SESSION_DRAINING 3
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
#define to_delayed_work(w) ((struct delayed_work *)(w))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct afe_job;
struct afe_session {
 struct delayed_work service;
 struct work_struct stop;
 struct afe_job *job;
 bool stopping,started,cancel_requested,quiescent;
 struct { u64 accepted,completed,released; unsigned int flags,state; } status;
 struct { u64 target_events; unsigned int slots,pressure_timeout_ms,trigger_timeout_ms; } config;
 u64 last_accepted,last_progress_ns,pressure_since_ns,collected,release_requested;
};
struct afe_job {
 int lock;
 bool removed,poisoned;
 uintptr_t control,monitor[3];
 struct { unsigned int active_routes; } status;
 struct afe_session *session;
};
static unsigned int snapshots,queued,stops,cancelled;
static int cancel_error;
static u64 committed,arriving;
static bool publish_after_empty;
static void mutex_lock(int *p) {(void)p;}
static void mutex_unlock(int *p) {(void)p;}
static u64 ktime_get_ns(void) {return 1000;}
static unsigned int msecs_to_jiffies(unsigned int ms) {return ms;}
static void schedule_work(struct work_struct *w) {(void)w;stops++;}
static void schedule_delayed_work(struct delayed_work *w,unsigned int delay) {(void)w;(void)delay;queued++;}
static void session_cancel(struct afe_job *p,int error)
{p->session->stopping=true;cancelled++;cancel_error=error;}
static void session_snapshot(struct afe_job *p)
{
 snapshots++;p->session->status.completed=committed;p->session->status.accepted=committed;
 p->session->status.flags=committed==p->session->config.target_events?4:0;
}
static unsigned int readl(uintptr_t address)
{
 if(address==0x1000+S_FLAGS) {
  if(publish_after_empty) {committed=arriving;publish_after_empty=false;}
  return committed?BIT(4):0;
 }
 return 0;
}
static int session_collect(struct afe_job *p)
{
 if(!publish_after_empty&&p->session->collected<arriving) {
  p->session->collected++;committed=arriving;return 1;
 }
 return 0;
}
static int session_release_one(struct afe_job *p,struct afe_session *s)
{(void)p;(void)s;return 0;}
/* Generated from afe_session_impl.h by the runner, never a copied function. */
#include "session_service_under_test.h"
static void initialize(struct afe_job *p,struct afe_session *s,u64 target)
{
 memset(p,0,sizeof(*p));memset(s,0,sizeof(*s));p->control=0x1000;p->session=s;
 s->job=p;s->started=true;s->config.target_events=target;s->config.slots=8;
 s->config.trigger_timeout_ms=30000;
 snapshots=queued=stops=cancelled=0;committed=arriving=0;cancel_error=0;publish_after_empty=false;
}
int main(void)
{
 struct afe_job p;
 struct afe_session s;
 /* Final fence/READY arrives between empty collect and live STOP read. */
 initialize(&p,&s,1);arriving=1;publish_after_empty=true;
 session_service(&s.service.work);
 assert(!cancelled&&!stops&&queued==1&&snapshots==2&&s.collected==0&&s.status.completed==1);
 session_service(&s.service.work);
 assert(!cancelled&&stops==1&&s.collected==1&&s.status.state==DAPHNE_SESSION_DRAINING);
 /* Earlier snapshot stale; collect itself observes all final records. */
 initialize(&p,&s,2);arriving=2;session_service(&s.service.work);
 assert(!cancelled&&stops==1&&snapshots==2&&s.collected==2);
 /* Reused slots and counters beyond 32 bits; no userspace GET in any case. */
 initialize(&p,&s,0x100000002ULL);s.collected=0x100000000ULL;
 arriving=0x100000002ULL;session_service(&s.service.work);
 assert(!cancelled&&stops==1&&s.collected==s.config.target_events);
 /* Inconsistent STOP/counter still fails closed. */
 initialize(&p,&s,2);committed=arriving=1;session_service(&s.service.work);
 assert(cancelled==1&&cancel_error==-EPROTO&&!stops);
 puts("AFE_DMA_SESSION_SERVICE_PASS final_after_empty=1 stale_snapshot=1 counters64=1 bad_stop=1");
 return 0;
}
