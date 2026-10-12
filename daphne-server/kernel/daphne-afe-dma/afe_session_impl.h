/* SPDX-License-Identifier: GPL-2.0
 * Included after the legacy helpers; all session mutations use job->lock.
 * Slow stop runs without that lock. READ pins a slot across unlocked copying.
 */
static atomic64_t session_serial=ATOMIC64_INIT(0);
static_assert(sizeof(struct daphne_afe_session_config)==88);
static_assert(sizeof(struct daphne_afe_event_id)==32);
static_assert(sizeof(struct daphne_afe_session_event)==160);
static_assert(sizeof(struct daphne_afe_session_status)==184);
static_assert(sizeof(struct daphne_afe_session_batch)==24);
static_assert(sizeof(struct daphne_afe_session_read)==64);
static_assert(sizeof(struct daphne_afe_session_caps)==56);
static int session_admit(struct afe_job *p,u32 build)
{
 int err=identify(p,build);
 u32 slots;
 if(err) return err;
 /* The always-mapped identity gate must precede ANY extension access. */
 if(!(readl(p->identity)&BIT(SESSION_CAP_BIT))) return -EOPNOTSUPP;
 if(readl(p->control+S_API)!=1||readl(p->control+S_MAGIC)!=0x44534e31||
    (readl(p->control+S_FEATURES)&S_REQUIRED_FEATURES)!=S_REQUIRED_FEATURES) return -EPROTO;
 slots=readl(p->control+S_SLOTS);
 return slots<2||slots>32||!is_power_of_2(slots)?-EPROTO:0;
}
static int session_command(struct afe_job *p,u32 command)
{
 writel(command,p->control+S_COMMAND);
 return readl(p->control+S_REJECT)?-EIO:0;
}
/* Refresh all three passive witnesses, including inactive routes. A late B or
 * control write invalidates previous CR/SR observations in the firmware. */
static bool session_live_quiet(struct afe_job *p)
{
 unsigned int r;
 bool halted=true;
 for(r=0;r<3;r++) {
  u32 cr=readl(p->monitor[r]);
  u32 sr=readl(p->monitor[r]+4);
  if((cr&5)||!(sr&1)) halted=false;
 }
 return halted&&(readl(p->control+S_FLAGS)&BIT(8));
}
static bool session_empty(struct afe_session *s)
{
 unsigned int i;
 if(s->readers||s->get_busy) return false;
 for(i=0;i<s->config.slots;i++) if(s->slot[i].state!=AFE_SLOT_FREE) return false;
 return true;
}
static void session_cancel(struct afe_job *p,int error)
{
 struct afe_session *s=p->session;
 if(!s) return;
 s->cancel_requested=true;
 if(error) s->status.error=error;
 if(s->quiescent) {
  s->status.state=error?DAPHNE_SESSION_ERROR:DAPHNE_SESSION_ABORTED;
  wake_up_all(&p->wait);return;
 }
 if(!s->stopping) {
  s->stopping=true;s->status.state=DAPHNE_SESSION_DRAINING;
  schedule_work(&s->stop);
 }
 wake_up_all(&p->wait);
}
static void session_snapshot(struct afe_job *p)
{
 struct afe_session *s=p->session;
 u32 words[24];
 unsigned int i;
 if(session_command(p,S_SNAPSHOT)) {session_cancel(p,-EIO);return;}
 for(i=0;i<24;i++) words[i]=readl(p->control+S_STATUS+i*4);
 s->status.accepted=afe_bits(words,0,64);
 s->status.cursor=afe_bits(words,128,64);s->status.sample_index=afe_bits(words,192,64);
 s->status.segment=afe_bits(words,256,64);s->status.pauses=afe_bits(words,320,64);
 for(i=0;i<4;i++) s->status.ignored[i]=afe_bits(words,384+64*i,64);
 s->status.hardware_error=words[20];
 s->status.flags=afe_bits(words,672,5);
 s->status.completed=read64(p->control,S_COMPLETED);
 if(s->status.accepted>s->config.target_events||s->status.completed>s->config.target_events)
  session_cancel(p,-EPROTO);
 /* completed is independent of the slower sample-domain status mailbox.
  * Its fence proves at least that many accepted records, so expose a lower
  * bound consistent with publication while the cached sample count catches up.
  */
 s->status.accepted=max(s->status.accepted,s->status.completed);
 if(s->status.hardware_error) session_cancel(p,-EIO);
}
static int session_collect(struct afe_job *p)
{
 struct afe_session *s=p->session;
 u32 words[22];
 struct daphne_afe_session_event e={};
 struct afe_session_slot *slot;
 u64 end;
 unsigned int i;
 if(!(readl(p->control+S_FLAGS)&BIT(1))) return 0;
 for(i=0;i<22;i++) words[i]=readl(p->control+S_EVENT+i*4);
 afe_event_words(words,&e);
 for(i=651;i<704;i++) if(afe_bits(words,i,1)) return -EPROTO;
 if(e.id.session!=s->config.session||e.id.sequence!=s->collected+1||
    e.id.sequence>s->config.target_events||e.id.slot!=(s->collected&(s->config.slots-1))||
    e.id.generation!=s->collected/s->config.slots+1||e.channel_mask!=s->config.channel_mask||
    e.length!=s->config.length||e.pretrigger!=s->config.pretrigger||e.source!=s->config.source||
    e.trigger_index<e.pretrigger||e.first_cursor>e.trigger_index-e.pretrigger||
    (e.source==2&&!e.timestamp_valid)||check_add_overflow(e.first_cursor,(u64)e.length,&end)||
    end>0x07ffffffffffffffULL||e.fence_end!=ALIGN(end,(u64)s->config.period_ticks)) return -EPROTO;
 slot=&s->slot[e.id.slot];
 if(slot->state!=AFE_SLOT_FREE) return -EPROTO;
 for(i=0;i<3;i++) if(e.valid_bytes[i]&&
    e.fence_end-e.first_cursor>s->config.ring_ticks[i]) return -EPROTO;
 /* The hardware popped record proves the per-route DDR prefix, not a DMA IRQ. */
 dma_rmb();
 memcpy(e.ignored,s->status.ignored,sizeof(e.ignored));
 slot->event=e;slot->state=AFE_SLOT_READY;s->collected++;
 if(session_command(p,S_POP)) return -EIO;
 wake_up_all(&p->wait);return 1;
}
static int session_release_one(struct afe_job *p,struct afe_session *s)
{
 u64 seq=s->status.released+1;
 struct afe_session_slot *slot=&s->slot[(seq-1)&(s->config.slots-1)];
 u32 words[7],reply;
 unsigned int i;
 int err;
 if(seq>s->release_requested||slot->state!=AFE_SLOT_RELEASING) return 0;
 if(s->cancel_requested) {
  if(!s->quiescent) return 0;
  slot->state=AFE_SLOT_FREE;s->status.released++;return 1;
 }
 if(!(readl(p->control+S_FLAGS)&BIT(2))) return 0;
 afe_release_words(&slot->event.id,words);
 for(i=0;i<7;i++) writel(words[i],p->control+S_RELEASE+i*4);
 if(session_command(p,S_ACK_RELEASE)) return -EIO;
 /* Drop the cache/ownership lock while waiting for the short CDC handshake.
  * The single service worker owns all RELEASE MMIO; cancellation merely sets
  * a flag and stop waits for this worker to finish before touching registers.
  */
 mutex_unlock(&p->lock);
 err=readl_poll_timeout(p->control+S_REPLY,reply,reply&BIT(8),10,20000);
 mutex_lock(&p->lock);
 if(err) return err;
 if((reply&255)!=0) return -EPROTO;
 if(session_command(p,S_POP_REPLY)) return -EIO;
 slot->state=AFE_SLOT_FREE;s->status.released++;wake_up_all(&p->wait);return 1;
}
static void session_service(struct work_struct *work)
{
 struct afe_session *s=container_of(to_delayed_work(work),struct afe_session,service);
 struct afe_job *p=s->job;
 unsigned int i,r;
 int err=0;
 mutex_lock(&p->lock);
 if(p->removed||p->poisoned||s->stopping) goto out;
 if(s->started&&!s->cancel_requested) {
  u64 now=ktime_get_ns();
  session_snapshot(p);
  if(s->status.accepted!=s->last_accepted) {
   s->last_accepted=s->status.accepted;s->last_progress_ns=now;
  }
  if(s->status.flags&1) {
   s->last_progress_ns=now;
   if(!s->pressure_since_ns) s->pressure_since_ns=now;
   if(s->config.pressure_timeout_ms&&now-s->pressure_since_ns>=(u64)s->config.pressure_timeout_ms*1000000)
    session_cancel(p,-ETIMEDOUT);
  } else {
   s->pressure_since_ns=0;
   if(!(s->status.flags&4)&&now-s->last_progress_ns>=(u64)s->config.trigger_timeout_ms*1000000)
    session_cancel(p,-ETIMEDOUT);
  }
  for(r=0;r<3;r++) if(p->status.active_routes&BIT(r))
   if(readl(p->monitor[r]+4)&0x770) session_cancel(p,-EIO);
  if(!s->stopping) for(i=0;i<s->config.slots;i++) {
   err=session_collect(p);if(err<=0) break;
  }
 }
 if(err<0) {session_cancel(p,err);goto out;}
 if(!s->stopping) for(i=0;i<s->config.slots;i++) {
  err=session_release_one(p,s);if(err<=0||s->stopping) break;
 }
 if(err<0) {session_cancel(p,err);goto out;}
 if(s->started&&!s->stopping&&!s->quiescent&&!s->cancel_requested&&
    (readl(p->control+S_FLAGS)&BIT(4))) {
  /* STOP may assert after the earlier snapshot or after collect observed an
   * empty FIFO. Refresh the frozen counters; leave newly queued final records
   * for the next service pass. Producer completion does not require GET.
   */
  session_snapshot(p);
  if(!s->stopping) {
   if(s->status.completed!=s->config.target_events||s->collected>s->status.completed)
    session_cancel(p,-EPROTO);
   else if(s->collected==s->config.target_events) {
    s->stopping=true;s->status.state=DAPHNE_SESSION_DRAINING;schedule_work(&s->stop);
   }
  }
 }
 if(!s->stopping&&s->started&&((!s->quiescent&&!s->cancel_requested)||s->release_requested>s->status.released))
  schedule_delayed_work(&s->service,msecs_to_jiffies(1));
out: mutex_unlock(&p->lock);
}
static void session_stop(struct work_struct *work)
{
 struct afe_session *s=container_of(work,struct afe_session,stop);
 struct afe_job *p=s->job;
 int err=0,e;
 unsigned int r;
 u32 value;
 cancel_delayed_work_sync(&s->service);
 /* No long polling under job->lock: SESSION_STATUS is entirely cached. */
 if(READ_ONCE(s->cancel_requested)) err=session_command(p,S_CANCEL);
 writel(2,p->control+HW_COMMAND); /* Integration flushes packers, retains session ledger. */
 for(r=0;r<3;r++) if(p->route[r].chan) {
  e=dmaengine_terminate_sync(p->route[r].chan);
  if(!e) e=readl_poll_timeout(p->monitor[r]+4,value,value&1,10,100000);
  if(!e) e=readl_poll_timeout(p->monitor[r],value,!(value&5),10,100000);
  if(e) err=e;
 }
 if(!err) err=read_poll_timeout(session_live_quiet,value,value,10,100000,false,p);
 mutex_lock(&p->lock);
 s->status.stops++;s->status.end_ns=ktime_get_ns();s->stopping=false;
 if(err) {quarantine(p);s->status.state=DAPHNE_SESSION_QUARANTINED;s->status.error=err;}
 else {
  s->quiescent=true;s->status.guards_ok=guards(p);
  if(!s->status.guards_ok) s->status.error=-EIO;
  s->status.state=s->status.error?DAPHNE_SESSION_ERROR:
      (s->cancel_requested?DAPHNE_SESSION_ABORTED:DAPHNE_SESSION_COMPLETE);
  p->status.state=s->status.error?DAPHNE_AFE_ERROR:
      (s->cancel_requested?DAPHNE_AFE_ABORTED:DAPHNE_AFE_COMPLETE);
  if(!session_empty(s)) schedule_delayed_work(&s->service,0);
 }
 wake_up_all(&p->wait);mutex_unlock(&p->lock);
}
/* Called with job lock. Never wait for workers while holding that lock. */
static int session_close(struct afe_job *p)
{
 struct afe_session *s=p->session;
 int err;
 if(!s) return 0;
 if(p->closing) return -EBUSY;
 if(!s->quiescent||!session_empty(s)) return -EBUSY;
 p->closing=true;
 mutex_unlock(&p->lock);
 cancel_delayed_work_sync(&s->service);cancel_work_sync(&s->stop);
 mutex_lock(&p->lock);
 /* Callers serialize replacement; no other PREPARE may replace the pointer. */
 if(!session_empty(s)) {p->closing=false;wake_up_all(&p->wait);return -EBUSY;}
 /* Software owns no event/read reference; return hardware ownership too. */
 if(s->started) {
  err=session_command(p,S_RESET);
  if(err) {p->closing=false;wake_up_all(&p->wait);return err;}
 }
 kfree(s);p->session=NULL;p->closing=false;wake_up_all(&p->wait);return 0;
}
static int session_prepare(struct afe_job *p,struct daphne_afe_session_config *c)
{
 struct daphne_afe_dma_config cfg={};
 struct daphne_afe_trigger_config trigger={};
 struct afe_session *s;
 u64 total=0,ring;
 unsigned int r;
 int err;
 err=afe_geometry(c,(u64)max_pool_mib<<20,PAGE_SIZE,&total);if(err) return err;
 err=session_admit(p,c->expected_build_id);if(err) return err;
 if(p->session) {err=session_close(p);if(err) return err;}
 ring=0;
 for(r=0;r<3;r++) if(c->ring_ticks[r]) ring=c->ring_ticks[r];
 s=kzalloc(sizeof(*s),GFP_KERNEL);if(!s) return -ENOMEM;
 cfg.abi=1;cfg.flags=c->flags&3;cfg.length=c->length;cfg.count=1;
 cfg.timeout_ms=600000;cfg.expected_build_id=c->expected_build_id;cfg.channel_mask=c->channel_mask;
 trigger.abi=1;trigger.flags=cfg.flags;trigger.length=c->length;trigger.pretrigger=c->pretrigger;
 trigger.period_ticks=c->period_ticks;trigger.ring_ticks=ring;trigger.source=c->source;
 err=prepare(p,&cfg,&trigger);if(err) {kfree(s);return err;}
 /* Saturate serial at signed limit: no ID reuse after exhaustion. */
 c->session=atomic64_fetch_add_unless(&session_serial,1,S64_MAX)+1;
 if(c->session>S64_MAX) {kfree(s);return -EOVERFLOW;}
 c->slots=readl(p->control+S_SLOTS);c->budget_bytes=total;
 s->config=*c;s->job=p;s->quiescent=true;
 s->status.abi=1;s->status.state=DAPHNE_SESSION_PREPARED;s->status.session=c->session;
 s->status.target_events=c->target_events;s->status.slots=c->slots;
 s->status.active_routes=p->status.active_routes;s->status.allocated_bytes=p->status.allocated_bytes;
 INIT_DELAYED_WORK(&s->service,session_service);INIT_WORK(&s->stop,session_stop);
 p->session=s;return 0;
}
static int session_start(struct afe_job *p)
{
 struct afe_session *s=p->session;
 u32 words[12],value;
 unsigned int r,i;
 int err;
 if(!s||s->started||s->status.state!=DAPHNE_SESSION_PREPARED) return -EINVAL;
 err=session_admit(p,s->config.expected_build_id);if(err) return err;
 if(!(s->config.flags&1)&&!(readl(p->control+0x4c)&8)) return -ENOLINK;
 if(s->config.source==2&&!(readl(p->control+0x4c)&4)) return -ENOLINK;
 if(!session_live_quiet(p)) return -EBUSY;
 err=session_command(p,S_RESET);if(err) return err;
 err=readl_poll_timeout(p->control+S_FLAGS,value,!(value&BIT(6)),10,100000);
 if(err) return err;
 writel(1,p->control+HW_MODE);
 if(readl(p->control+HW_MODE)!=1) return -EBUSY;
 writel(s->config.flags&3,p->control+HW_FLAGS);
 afe_start_words(&s->config,words);
 for(i=0;i<12;i++) writel(words[i],p->control+S_CONFIG+i*4);
 for(r=0;r<3;r++) {
  u64 base=0,end=0;
  if(p->status.active_routes&BIT(r)) {
   base=(u64)p->route[r].blocks[0].dma+GUARD_BYTES;
   end=base+p->route[r].blocks[0].length;
  }
  writel(lower_32_bits(base),p->control+S_REGIONS+r*16);
  writel(upper_32_bits(base),p->control+S_REGIONS+r*16+4);
  writel(lower_32_bits(end),p->control+S_REGIONS+r*16+8);
  writel(upper_32_bits(end),p->control+S_REGIONS+r*16+12);
 }
 s->started=true;s->quiescent=false;s->status.state=DAPHNE_SESSION_RUNNING;
 p->status.state=DAPHNE_AFE_RUNNING;
 for(r=0;r<3;r++) if(p->status.active_routes&BIT(r)) {
  struct afe_route *route=&p->route[r];
  struct dma_async_tx_descriptor *tx;
  dma_cookie_t cookie;
  size_t period=(size_t)s->config.period_ticks*afe_channels(s->config.channel_mask,r)*2;
  dma_wmb();
  tx=dmaengine_prep_dma_cyclic(route->chan,route->blocks[0].dma+GUARD_BYTES,
      route->blocks[0].length,period,DMA_DEV_TO_MEM,DMA_CTRL_ACK);
  if(!tx) {err=-ENOMEM;goto fail;}
  cookie=dmaengine_submit(tx);
  if(dma_submit_error(cookie)) {err=dma_submit_error(cookie);goto fail;}
  dma_async_issue_pending(route->chan);
 }
 err=readl_poll_timeout(p->control+S_FLAGS,value,value&BIT(0),10,100000);
 if(err) goto fail;
 err=session_command(p,S_START);if(err) goto fail;
 s->status.starts++;s->status.start_ns=ktime_get_ns();
 s->last_progress_ns=s->status.start_ns;
 schedule_delayed_work(&s->service,0);return 0;
fail: session_cancel(p,err);return err;
}
static long session_get(struct afe_job *p,void __user *arg)
{
 struct afe_session *s=p->session;
 struct daphne_afe_session_batch b;
 struct daphne_afe_session_event *events;
 unsigned int i,n=0;
 int err=0;
 if(!s) return -EINVAL;
 if(copy_from_user(&b,arg,sizeof(b))) return -EFAULT;
 if(b.abi!=1||b.reserved||b.count||!b.capacity||b.capacity>DAPHNE_AFE_SESSION_BATCH||!b.entries) return -EINVAL;
 if(s->get_busy) return -EBUSY;
 if(s->cancel_requested||s->status.error) return s->status.error?s->status.error:-ECANCELED;
 events=kcalloc(b.capacity,sizeof(*events),GFP_KERNEL);if(!events) return -ENOMEM;
 for(i=0;i<b.capacity;i++) {
  u64 seq=s->status.delivered+i+1;
  struct afe_session_slot *slot=&s->slot[(seq-1)&(s->config.slots-1)];
  if(slot->state!=AFE_SLOT_READY||slot->event.id.sequence!=seq) break;
  events[n++]=slot->event;
 }
 if(!n) {err=s->quiescent?-ENODATA:-EAGAIN;goto done;}
 b.count=n;s->get_busy=true;
 mutex_unlock(&p->lock);
 if(copy_to_user(u64_to_user_ptr(b.entries),events,n*sizeof(*events))||copy_to_user(arg,&b,sizeof(b))) err=-EFAULT;
 mutex_lock(&p->lock);
 if(!err) for(i=0;i<n;i++) {
  s->slot[events[i].id.slot].state=AFE_SLOT_OWNED;s->status.delivered++;
 }
 s->get_busy=false;
done: kfree(events);return err;
}
static long session_read(struct afe_job *p,void __user *arg)
{
 struct afe_session *s=p->session;
 struct daphne_afe_session_read q;
 struct afe_session_slot *slot;
 struct afe_block *block;
 size_t offset,n;
 u32 first_length;
 u64 valid,physical;
 int err=0;
 if(!s) return -EINVAL;
 if(copy_from_user(&q,arg,sizeof(q))) return -EFAULT;
 if(q.abi!=1||q.copied||q.id.slot>=s->config.slots||q.route>2||!q.length||
    q.length>DAPHNE_AFE_SESSION_READ_MAX||!q.buffer) return -EINVAL;
 slot=&s->slot[q.id.slot];
 if(slot->state!=AFE_SLOT_OWNED||!afe_same_id(&q.id,&slot->event.id)) return -ESTALE;
 if(s->status.error||p->poisoned) return -EIO;
 valid=slot->event.valid_bytes[q.route];
 err=afe_read_range(slot->event.first_cursor,s->config.ring_ticks[q.route],
     afe_channels(s->config.channel_mask,q.route),valid,q.offset,q.length,&physical,&first_length);
 if(err) return err;
 block=&p->route[q.route].blocks[0];
 slot->readers++;s->readers++;
 mutex_unlock(&p->lock);
 dma_rmb();offset=physical;n=first_length;
 if(copy_to_user(u64_to_user_ptr(q.buffer),block->cpu+GUARD_BYTES+offset,n)||
    (n<q.length&&copy_to_user(u64_to_user_ptr(q.buffer+n),block->cpu+GUARD_BYTES,q.length-n))) err=-EFAULT;
 else {q.copied=q.length;if(copy_to_user(arg,&q,sizeof(q))) err=-EFAULT;}
 mutex_lock(&p->lock);
 slot->readers--;s->readers--;wake_up_all(&p->wait);return err;
}
static long session_release_events(struct afe_job *p,void __user *arg)
{
 struct afe_session *s=p->session;
 struct daphne_afe_session_batch b;
 struct daphne_afe_event_id ids[DAPHNE_AFE_SESSION_BATCH];
 unsigned int i;
 int err;
 if(!s) return -EINVAL;
 if(copy_from_user(&b,arg,sizeof(b))) return -EFAULT;
 if(b.abi!=1||b.reserved||!b.count||b.count>DAPHNE_AFE_SESSION_BATCH||b.capacity!=b.count||!b.entries) return -EINVAL;
 if(copy_from_user(ids,u64_to_user_ptr(b.entries),b.count*sizeof(*ids))) return -EFAULT;
 if(s->get_busy||s->stopping||p->poisoned) return -EBUSY;
 for(i=0;i<b.count;i++) {
  u64 seq=s->release_requested+i+1;
  struct afe_session_slot *slot=&s->slot[(seq-1)&(s->config.slots-1)];
  err=afe_release_check(&ids[i],&slot->event.id,slot->state,slot->readers,seq);
  if(err) return err;
 }
 /* Entire batch validated before changing any ownership or sending MMIO. */
 for(i=0;i<b.count;i++) s->slot[ids[i].slot].state=AFE_SLOT_RELEASING;
 s->release_requested+=b.count;
 schedule_delayed_work(&s->service,0);return 0;
}
static long session_ioctl(struct afe_job *p,unsigned int cmd,void __user *arg)
{
 struct afe_session *s=p->session;
 struct daphne_afe_session_config c;
 struct daphne_afe_session_caps caps={.abi=1,.batch_max=DAPHNE_AFE_SESSION_BATCH,
  .read_max=DAPHNE_AFE_SESSION_READ_MAX,.format=1,.period_min=8,.period_max=1048576,
  .pool_max=(u64)max_pool_mib<<20,.route_max=MAX_ROUTE_BYTES,.target_max=U64_MAX};
 int err;
 switch(cmd) {
 case DAPHNE_AFE_SESSION_CAPS:
  err=session_admit(p,readl(p->identity+0x1c));if(err) return err;
  caps.features=readl(p->control+S_FEATURES);caps.slots=readl(p->control+S_SLOTS);
  return copy_to_user(arg,&caps,sizeof(caps))?-EFAULT:0;
 case DAPHNE_AFE_SESSION_PREPARE:
  if(copy_from_user(&c,arg,sizeof(c))) return -EFAULT;
  err=session_prepare(p,&c);if(err) return err;
  return copy_to_user(arg,&c,sizeof(c))?-EFAULT:0;
 case DAPHNE_AFE_SESSION_START: return session_start(p);
 case DAPHNE_AFE_SESSION_STATUS:
  if(!s) return -EINVAL;
  {
   struct daphne_afe_session_status cached=s->status;
   mutex_unlock(&p->lock);
   err=copy_to_user(arg,&cached,sizeof(cached))?-EFAULT:0;
   mutex_lock(&p->lock);return err;
  }
 case DAPHNE_AFE_SESSION_GET: return session_get(p,arg);
 case DAPHNE_AFE_SESSION_READ: return session_read(p,arg);
 case DAPHNE_AFE_SESSION_RELEASE: return session_release_events(p,arg);
 case DAPHNE_AFE_SESSION_CANCEL:
  if(!s) return -EINVAL;
  session_cancel(p,0);return 0;
 case DAPHNE_AFE_SESSION_TRIGGER:
  if(!s||s->config.source!=0||s->status.state!=DAPHNE_SESSION_RUNNING) return -EINVAL;
  if(s->stopping||!(readl(p->control+S_FLAGS)&BIT(5))) return -EAGAIN;
  return session_command(p,S_SW_TRIGGER);
 default: return -ENOTTY;
 }
}
