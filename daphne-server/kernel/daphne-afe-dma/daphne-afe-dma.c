// SPDX-License-Identifier: GPL-2.0
/* One finite common-start chunk; no server, ring or automatic acquisition.
 * DMAengine owns all three engines. Claim even inactive routes to exclude
 * diagnostic jobs while the shared source mux selects physical capture.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/compat.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/dmaengine.h>
#include <linux/dma-mapping.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/poll.h>
#include <linux/uaccess.h>
#include <linux/workqueue.h>
#include <linux/ktime.h>
#include <linux/kref.h>
#include <linux/overflow.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include "daphne_afe_dma_uapi.h"
#define BLOCK_BYTES (4U << 20)
#define GUARD_BYTES 64U
#define MAX_ROUTE_BYTES (256ULL << 20)
#define HW_MODE 0x0c
#define HW_FLAGS 0x10
#define HW_MASK_LO 0x14
#define HW_MASK_HI 0x18
#define HW_L 0x1c
#define HW_C 0x20
#define HW_COMMAND 0x24
#define HW_STATUS 0x28
#define HW_ERROR 0x40
struct afe_block { void *cpu; dma_addr_t dma; size_t allocation; u32 length; u64 offset; };
struct afe_job;
struct afe_route {
 struct afe_job *job;
 struct dma_chan *chan;
 struct device *dma_dev;
 struct afe_block *blocks;
 struct scatterlist *sg;
 u32 nblocks;
 bool completed;
 atomic_t callback_ready;
 struct dmaengine_result result;
};
struct afe_job {
 struct device *dev;
 struct miscdevice misc;
 struct kref ref;
 struct mutex lock;
 struct work_struct completion;
 struct delayed_work watchdog;
 wait_queue_head_t wait;
 void __iomem *control, *identity, *monitor[3];
 struct afe_route route[3];
 struct daphne_afe_dma_config config;
 struct daphne_afe_dma_status status;
 bool opened, removed, poisoned, control_owned;
 u32 read_route;
};
static unsigned int max_pool_mib = 448;
module_param(max_pool_mib,uint,0444);
MODULE_PARM_DESC(max_pool_mib,"Finite AFE chunk pool limit (1..480 MiB)");
static void destroy(struct kref *ref)
{
 struct afe_job *p=container_of(ref,struct afe_job,ref);
 put_device(p->dev);kfree(p);
}
static u64 read64(void __iomem *base, u32 low)
{
 u32 hi,lo,again;
 do {hi=readl(base+low+4);lo=readl(base+low);again=readl(base+low+4);} while(hi!=again);
 return ((u64)hi<<32)|lo;
}
static void snapshot(struct afe_job *p)
{
 unsigned int r;
 p->status.hardware_status=readl(p->control+HW_STATUS);
 p->status.hardware_error=readl(p->control+HW_ERROR);
 p->status.captured_ticks=readl(p->control+0x30);
 p->status.timestamp=read64(p->control,0x38);
 for(r=0;r<3;r++) {
  p->status.accepted_beats[r]=read64(p->control,0x68+r*32);
  p->status.dma_control[r]=readl(p->monitor[r]);
  p->status.dma_status[r]=readl(p->monitor[r]+4);
 }
}
static int identify(struct afe_job *p,u32 build)
{
 if(readl(p->identity+0x10)!=0x44415048 || readl(p->identity+0x14)!=0x20000 ||
    readl(p->identity+0x18)!=3 || !(readl(p->identity)&BIT(4)))
  return -EPROTO;
 p->status.build_id=readl(p->identity+0x1c);
 if(p->status.build_id&0xf0000000 || p->status.build_id!=build) return -ESTALE;
 return (readl(p->control)!=0x41464543 || readl(p->control+4)!=1 || readl(p->control+8)!=1)?-EPROTO:0;
}
static bool guards(struct afe_job *p)
{
 unsigned int r,i;
 dma_rmb();
 for(r=0;r<3;r++) for(i=0;i<p->route[r].nblocks;i++) {
  struct afe_block *b=&p->route[r].blocks[i];
  if(memchr_inv(b->cpu,0xa5,GUARD_BYTES)||
     memchr_inv(b->cpu+GUARD_BYTES+b->length,0xa5,b->allocation-GUARD_BYTES-b->length))
   return false;
 }
 return true;
}
static void quarantine(struct afe_job *p)
{
 if(!p->poisoned) {p->poisoned=true;__module_get(THIS_MODULE);kref_get(&p->ref);}
 p->status.state=DAPHNE_AFE_QUARANTINED;p->status.error=-EIO;
 dev_crit(p->dev,"AFE DMA halt/reset unproven; memory quarantined, do not unload overlay\n");
 wake_up_all(&p->wait);
}
/* Every DMA must be proven halted with RUN/RESET clear before freeing payloads.
 * Use the bounded Xilinx provider qualified in point 3 for termination.
 */
static int halt(struct afe_job *p)
{
 unsigned int r;
 u32 value;
 int err=0,e;
 writel(2,p->control+HW_COMMAND);
 for(r=0;r<3;r++) if(p->route[r].chan) {
  e=dmaengine_terminate_sync(p->route[r].chan);
  if(!e) e=readl_poll_timeout(p->monitor[r]+4,value,value&1,10,100000);
  if(!e) e=readl_poll_timeout(p->monitor[r],value,!(value&5),10,100000);
  if(e) err=e;
 }
 if(!err) err=readl_poll_timeout(p->control+HW_STATUS,value,!(value&1),10,100000);
 if(err) quarantine(p);
 return err;
}
static void release_buffers(struct afe_job *p)
{
 unsigned int r,i;
 if(p->poisoned) return;
 for(r=0;r<3;r++) {
  struct afe_route *route=&p->route[r];
  for(i=0;route->blocks&&i<route->nblocks;i++) {
   struct afe_block *b=&route->blocks[i];
   if(b->cpu) dma_free_coherent(route->dma_dev,b->allocation,b->cpu,b->dma);
  }
  kfree(route->blocks);kfree(route->sg);route->blocks=NULL;route->sg=NULL;route->nblocks=0;
  if(route->chan) dma_release_channel(route->chan);
  route->chan=NULL;
 }
 p->status.allocated_bytes=0;
}
static void abort_job(struct afe_job *p,int error)
{
 unsigned int r;
 p->status.state=error?DAPHNE_AFE_ERROR:DAPHNE_AFE_ABORTED;p->status.error=error;
 cancel_delayed_work(&p->watchdog);
 snapshot(p);
 if(!halt(p)) {
  p->status.guards_ok=guards(p);p->status.end_ns=ktime_get_ns();
  for(r=0;r<3;r++) {
   p->status.dma_control[r]=readl(p->monitor[r]);
   p->status.dma_status[r]=readl(p->monitor[r]+4);
  }
 }
 wake_up_all(&p->wait);
}
static void callback(void *arg,const struct dmaengine_result *result)
{
 struct afe_route *r=arg;
 if(result) r->result=*result;
 else {r->result.result=DMA_TRANS_ABORTED;r->result.residue=0;}
 atomic_set_release(&r->callback_ready,1);schedule_work(&r->job->completion);
}
static void complete_work(struct work_struct *work)
{
 struct afe_job *p=container_of(work,struct afe_job,completion);
 unsigned int r;
 bool all=true;
 u32 value;
 mutex_lock(&p->lock);
 if(p->removed||p->status.state!=DAPHNE_AFE_RUNNING) goto out;
 for(r=0;r<3;r++) if(p->status.active_routes&BIT(r)) {
  if(atomic_xchg(&p->route[r].callback_ready,0)) {
   if(p->route[r].result.result!=DMA_TRANS_NOERROR||p->route[r].result.residue) {
    abort_job(p,-EIO);goto out;
   }
   p->route[r].completed=true;p->status.received_bytes[r]=p->status.transfer_bytes[r];
  }
  all&=p->route[r].completed;
 }
 if(!all) goto out;
 if(readl_poll_timeout(p->control+HW_STATUS,value,!(value&1),1,10000)) {
  abort_job(p,-ETIMEDOUT);goto out;
 }
 snapshot(p);p->status.guards_ok=guards(p);
 if(!(p->status.hardware_status&2)||p->status.hardware_error||!p->status.guards_ok||
    p->status.captured_ticks!=(u64)p->config.length*p->config.count) {
  abort_job(p,-EIO);goto out;
 }
 for(r=0;r<3;r++) if(p->status.active_routes&BIT(r))
  if(p->status.accepted_beats[r]*16!=p->status.transfer_bytes[r]||
     (p->status.dma_status[r]&0x770)||!(p->status.dma_status[r]&8)) {
   abort_job(p,-EIO);goto out;
  }
 p->status.end_ns=ktime_get_ns();p->status.state=DAPHNE_AFE_COMPLETE;
 cancel_delayed_work(&p->watchdog);wake_up_all(&p->wait);
out: mutex_unlock(&p->lock);
}
static void watchdog(struct work_struct *work)
{
 struct afe_job *p=container_of(to_delayed_work(work),struct afe_job,watchdog);
 mutex_lock(&p->lock);
 if(!p->removed&&p->status.state==DAPHNE_AFE_RUNNING) {
  if(readl(p->control+HW_ERROR)) abort_job(p,-EIO);
  else if(ktime_get_ns()-p->status.start_ns>=(u64)p->config.timeout_ms*1000000)
   abort_job(p,-ETIMEDOUT);
  else schedule_delayed_work(&p->watchdog,msecs_to_jiffies(10));
 }
 mutex_unlock(&p->lock);
}
static int prepare(struct afe_job *p,const struct daphne_afe_dma_config *cfg)
{
 u64 ticks,total=0,bytes[3],allocation;
 unsigned int r,i,k;
 int err;
 if(p->status.state==DAPHNE_AFE_RUNNING||p->poisoned) return -EBUSY;
 if(cfg->abi!=1||!cfg->channel_mask||(cfg->channel_mask>>40)||
    !cfg->length||!cfg->count||cfg->timeout_ms<10||cfg->timeout_ms>600000||
    (cfg->flags&~3U)||!(cfg->flags&3U)) return -EINVAL;
 ticks=(u64)cfg->length*cfg->count;
 if(ticks>U32_MAX) return -EOVERFLOW;
 for(r=0;r<3;r++) {
  k=hweight64((cfg->channel_mask>>(r*16))&0xffff);
  bytes[r]=ticks*k*2;
  if(bytes[r]>MAX_ROUTE_BYTES) return -E2BIG;
  for(allocation=0;allocation<ALIGN(bytes[r],16);allocation+=BLOCK_BYTES)
   total+=PAGE_ALIGN(min_t(u64,BLOCK_BYTES,ALIGN(bytes[r],16)-allocation)+2*GUARD_BYTES);
 }
 if(total>((u64)max_pool_mib<<20)) return -ENOMEM;
 err=identify(p,cfg->expected_build_id);if(err) return err;
 /* A rejected allocation/config never changes the shared stream mux. */
 if(p->route[0].chan) {err=halt(p);if(err) return err;release_buffers(p);}
 for(r=0;r<3;r++) {
  struct afe_route *route=&p->route[r];
  char name[4];snprintf(name,sizeof(name),"rx%u",r);
  route->chan=dma_request_chan(p->dev,name);
  if(IS_ERR(route->chan)) {err=PTR_ERR(route->chan);route->chan=NULL;goto fail;}
  route->dma_dev=dmaengine_get_dma_device(route->chan);
  if(!route->dma_dev->dma_mask||*route->dma_dev->dma_mask!=DMA_BIT_MASK(40)||
     route->dma_dev->coherent_dma_mask!=DMA_BIT_MASK(40)) {err=-EPROTO;goto fail;}
 }
 p->control_owned=true;
 err=halt(p);if(err) return err;
 memset(&p->status,0,sizeof(p->status));p->status.abi=1;p->status.format=1;
 p->status.build_id=cfg->expected_build_id;p->status.channel_mask=cfg->channel_mask;p->status.flags=cfg->flags;
 p->config=*cfg;
 for(r=0;r<3;r++) {
  struct afe_route *route=&p->route[r];
  p->status.valid_bytes[r]=bytes[r];p->status.transfer_bytes[r]=ALIGN(bytes[r],16);
  if(!bytes[r]) continue;
  p->status.active_routes|=BIT(r);
  route->nblocks=DIV_ROUND_UP_ULL(p->status.transfer_bytes[r],BLOCK_BYTES);
  route->blocks=kcalloc(route->nblocks,sizeof(*route->blocks),GFP_KERNEL);
  route->sg=kcalloc(route->nblocks,sizeof(*route->sg),GFP_KERNEL);
  if(!route->blocks||!route->sg) {err=-ENOMEM;goto fail;}
  for(i=0;i<route->nblocks;i++) {
   struct afe_block *b=&route->blocks[i];
   b->offset=(u64)i*BLOCK_BYTES;b->length=min_t(u64,BLOCK_BYTES,p->status.transfer_bytes[r]-b->offset);
   b->allocation=PAGE_ALIGN(b->length+2*GUARD_BYTES);
   b->cpu=dma_alloc_coherent(route->dma_dev,b->allocation,&b->dma,GFP_KERNEL);
   if(!b->cpu) {err=-ENOMEM;goto fail;}
   p->status.allocated_bytes+=b->allocation;
   if((b->dma&15)||b->dma+b->allocation-1>DMA_BIT_MASK(40)) {err=-ERANGE;goto fail;}
   memset(b->cpu,0xa5,b->allocation);
  }
 }
 p->status.state=DAPHNE_AFE_PREPARED;return 0;
fail:
 release_buffers(p);p->status.state=DAPHNE_AFE_ERROR;p->status.error=err;return err;
}
static int start(struct afe_job *p)
{
 unsigned int r,i;
 int err;
 u32 value;
 if(p->status.state!=DAPHNE_AFE_PREPARED) return -EINVAL;
 err=identify(p,p->config.expected_build_id);if(err) return err;
 writel(4,p->control+HW_COMMAND);
 err=readl_poll_timeout(p->control+HW_STATUS,value,value&0x20,10,100000);
 if(err) return err;
 writel(1,p->control+HW_MODE);
 if(readl(p->control+HW_MODE)!=1) return -EBUSY;
 writel(p->config.flags,p->control+HW_FLAGS);
 writel(lower_32_bits(p->config.channel_mask),p->control+HW_MASK_LO);
 writel(upper_32_bits(p->config.channel_mask),p->control+HW_MASK_HI);
 writel(p->config.length,p->control+HW_L);writel(p->config.count,p->control+HW_C);
 err=readl_poll_timeout(p->control+HW_STATUS,value,value&0x20,10,100000);
 if(err) return err;
 p->status.state=DAPHNE_AFE_RUNNING;
 for(r=0;r<3;r++) if(p->status.active_routes&BIT(r)) {
  struct afe_route *route=&p->route[r];
  struct dma_async_tx_descriptor *tx;
  dma_cookie_t cookie;
  route->completed=false;atomic_set(&route->callback_ready,0);
  sg_init_table(route->sg,route->nblocks);
  for(i=0;i<route->nblocks;i++) {
   sg_dma_address(&route->sg[i])=route->blocks[i].dma+GUARD_BYTES;
   sg_dma_len(&route->sg[i])=route->blocks[i].length;
  }
  dma_wmb();
  tx=dmaengine_prep_slave_sg(route->chan,route->sg,route->nblocks,DMA_DEV_TO_MEM,
                           DMA_PREP_INTERRUPT|DMA_CTRL_ACK);
  if(!tx) {err=-ENOMEM;goto fail;}
  tx->callback_result=callback;tx->callback_param=route;cookie=dmaengine_submit(tx);
  if(dma_submit_error(cookie)) {err=dma_submit_error(cookie);goto fail;}
  dma_async_issue_pending(route->chan);
 }
 if(!(p->config.flags&1)&&!(readl(p->control+0x4c)&8)) {err=-ENOLINK;goto fail;}
 p->status.start_ns=ktime_get_ns();writel(1,p->control+HW_COMMAND);
 value=readl(p->control+HW_STATUS);
 if(value&4) {err=-EIO;goto fail;}
 schedule_delayed_work(&p->watchdog,msecs_to_jiffies(10));return 0;
fail: abort_job(p,err);return err;
}
static int job_open(struct inode *inode,struct file *file)
{
 struct afe_job *p=container_of(file->private_data,struct afe_job,misc);
 int err=0;
 mutex_lock(&p->lock);
 if(p->removed||p->poisoned) err=-ENODEV;
 else if(p->opened) err=-EBUSY;
 else {p->opened=true;p->read_route=0;kref_get(&p->ref);file->private_data=p;}
 mutex_unlock(&p->lock);return err;
}
static int job_release(struct inode *inode,struct file *file)
{
 struct afe_job *p=file->private_data;
 mutex_lock(&p->lock);
 if(!p->removed&&!p->poisoned&&p->route[0].chan) abort_job(p,0);
 mutex_unlock(&p->lock);
 cancel_delayed_work_sync(&p->watchdog);cancel_work_sync(&p->completion);
 mutex_lock(&p->lock);
 if(!p->poisoned) {
  release_buffers(p);
  if(!p->removed&&p->control_owned) {
   writel(4,p->control+HW_COMMAND);writel(0,p->control+HW_MODE);p->control_owned=false;
  }
  p->status.state=DAPHNE_AFE_IDLE;
 }
 p->opened=false;mutex_unlock(&p->lock);kref_put(&p->ref,destroy);return 0;
}
static long job_ioctl(struct file *file,unsigned int cmd,unsigned long arg)
{
 struct afe_job *p=file->private_data;
 struct daphne_afe_dma_config cfg;
 u32 route;
 int err=0;
 mutex_lock(&p->lock);
 if(p->removed) {err=-ENODEV;goto out;}
 if(p->poisoned&&cmd!=DAPHNE_AFE_STATUS) {err=-EIO;goto out;}
 if(!p->poisoned) {
  /* Identity admission precedes every controller access, including cold
   * STATUS/failed PREPARE cleanup. Old firmware has no B0080000 slave.
   */
  err=identify(p,readl(p->identity+0x1c));if(err) goto out;
 }
 switch(cmd) {
 case DAPHNE_AFE_PREPARE:
  if(copy_from_user(&cfg,(void __user *)arg,sizeof(cfg))) err=-EFAULT;
  else {err=prepare(p,&cfg);if(!err) file->f_pos=0;}break;
 case DAPHNE_AFE_START: err=start(p);break;
 case DAPHNE_AFE_ABORT: if(p->route[0].chan&&!p->poisoned) abort_job(p,0);break;
 case DAPHNE_AFE_STATUS:
  if(!p->poisoned&&(p->status.state==DAPHNE_AFE_RUNNING||p->status.state==DAPHNE_AFE_IDLE)) snapshot(p);
  if(copy_to_user((void __user *)arg,&p->status,sizeof(p->status))) err=-EFAULT;
  break;
 case DAPHNE_AFE_SELECT_ROUTE:
  if(copy_from_user(&route,(void __user *)arg,sizeof(route))) err=-EFAULT;
  else if(route>2||!(p->status.active_routes&BIT(route))) err=-EINVAL;
  else {p->read_route=route;file->f_pos=0;}break;
 default: err=-ENOTTY;
 }
out: mutex_unlock(&p->lock);return err;
}
static ssize_t job_read(struct file *file,char __user *target,size_t size,loff_t *pos)
{
 struct afe_job *p=file->private_data;
 struct afe_route *route;
 ssize_t copied=0;
 unsigned int i;
 mutex_lock(&p->lock);
 if(p->removed||p->poisoned) {copied=-ENODEV;goto out;}
 if(p->status.state!=DAPHNE_AFE_COMPLETE) {copied=-EBUSY;goto out;}
 route=&p->route[p->read_route];dma_rmb();
 for(i=0;i<route->nblocks&&size&&*pos<p->status.valid_bytes[p->read_route];i++) {
  struct afe_block *b=&route->blocks[i];size_t offset,n;
  if(*pos>=b->offset+b->length) continue;
  offset=*pos-b->offset;n=min(size,b->length-offset);
  n=min_t(u64,n,p->status.valid_bytes[p->read_route]-*pos);
  if(copy_to_user(target+copied,b->cpu+GUARD_BYTES+offset,n)) {if(!copied) copied=-EFAULT;break;}
  *pos+=n;copied+=n;size-=n;
 }
out: mutex_unlock(&p->lock);return copied;
}
static __poll_t job_poll(struct file *file,poll_table *wait)
{
 struct afe_job *p=file->private_data;__poll_t mask=0;
 poll_wait(file,&p->wait,wait);mutex_lock(&p->lock);
 if(p->removed||p->poisoned||p->status.state==DAPHNE_AFE_ERROR) mask=EPOLLERR;
 else if(p->status.state==DAPHNE_AFE_COMPLETE) mask=EPOLLIN|EPOLLRDNORM;
 else if(p->status.state==DAPHNE_AFE_ABORTED) mask=EPOLLHUP;
 mutex_unlock(&p->lock);return mask;
}
static const struct file_operations operations={
 .owner=THIS_MODULE,.open=job_open,.release=job_release,.unlocked_ioctl=job_ioctl,
 .compat_ioctl=compat_ptr_ioctl,.read=job_read,.poll=job_poll
};
static int validate_dt(struct platform_device *pdev)
{
 unsigned int r;
 for(r=0;r<5;r++) {
  struct resource *res=platform_get_resource(pdev,IORESOURCE_MEM,r);
  resource_size_t base=r==0?0xb0080000ULL:r==1?0x940000e0ULL:0xb0020030ULL+(r-2)*0x20000;
  resource_size_t size=r==0?0x1000:r==1?0x20:8;
  if(!res||res->start!=base||resource_size(res)!=size) return -EINVAL;
 }
 if(platform_get_resource(pdev,IORESOURCE_MEM,5)) return -EINVAL;
 for(r=0;r<3;r++) {
  struct of_phandle_args spec;
  struct device_node *node,*child;
  struct resource res;
  u32 width,length;
  unsigned int children=0;
  int err=of_parse_phandle_with_args(pdev->dev.of_node,"dmas","#dma-cells",r,&spec);
  if(err) return err;
  err=-EINVAL;
  if(spec.args_count!=1||spec.args[0]!=1||
     !of_device_is_compatible(spec.np,"xlnx,axi-dma-1.00.a")||of_address_to_resource(spec.np,0,&res)||
     res.start!=0xb0020000ULL+r*0x20000||resource_size(&res)!=0x10000||
     of_property_read_u32(spec.np,"xlnx,addrwidth",&width)||width!=40||
     of_property_read_u32(spec.np,"xlnx,sg-length-width",&length)||length!=26||
     !of_property_read_bool(spec.np,"xlnx,include-sg")) goto invalid;
  for(node=of_node_get(spec.np);node;node=of_get_next_parent(node))
   if(of_property_read_bool(node,"dma-coherent")) {of_node_put(node);goto invalid;}
  for_each_available_child_of_node(spec.np,child) {
   if(!of_device_is_compatible(child,"xlnx,axi-dma-s2mm-channel")||
      of_property_read_u32(child,"xlnx,datawidth",&width)||width!=128||
      of_property_read_bool(child,"xlnx,include-dre")) {of_node_put(child);goto invalid;}
   children++;
  }
  if(children==1) err=0;
invalid:
  of_node_put(spec.np);if(err) return err;
 }
 return 0;
}
static int probe(struct platform_device *pdev)
{
 struct afe_job *p;
 unsigned int r;
 int err;
 if(!max_pool_mib||max_pool_mib>480) return -EINVAL;
 err=validate_dt(pdev);if(err) return dev_err_probe(&pdev->dev,err,"invalid AFE DMA DT contract\n");
 p=kzalloc(sizeof(*p),GFP_KERNEL);if(!p) return -ENOMEM;
 p->dev=get_device(&pdev->dev);kref_init(&p->ref);mutex_init(&p->lock);init_waitqueue_head(&p->wait);
 INIT_WORK(&p->completion,complete_work);INIT_DELAYED_WORK(&p->watchdog,watchdog);
 p->control=devm_platform_ioremap_resource(pdev,0);
 if(IS_ERR(p->control)) {err=PTR_ERR(p->control);goto fail;}
 /* Identity/monitors are shared READ-ONLY and overlap existing providers.
  * Never request their region or write DMA registers directly.
  */
 {
  struct resource *res=platform_get_resource(pdev,IORESOURCE_MEM,1);
  p->identity=devm_ioremap(&pdev->dev,res->start,resource_size(res));
 }
 if(!p->identity) {err=-ENOMEM;goto fail;}
 for(r=0;r<3;r++) {
  struct resource *res=platform_get_resource(pdev,IORESOURCE_MEM,r+2);
  p->monitor[r]=devm_ioremap(&pdev->dev,res->start,resource_size(res));
  if(!p->monitor[r]) {err=-ENOMEM;goto fail;}
  p->route[r].job=p;atomic_set(&p->route[r].callback_ready,0);
 }
 p->status.abi=1;p->status.format=1;
 p->misc.minor=MISC_DYNAMIC_MINOR;p->misc.name="daphne-afe-dma";p->misc.fops=&operations;p->misc.parent=&pdev->dev;
 p->misc.mode=0600;
 err=misc_register(&p->misc);if(err) goto fail;
 platform_set_drvdata(pdev,p);return 0;
fail: kref_put(&p->ref,destroy);return err;
}
static void remove_device(struct platform_device *pdev)
{
 struct afe_job *p=platform_get_drvdata(pdev);
 misc_deregister(&p->misc);mutex_lock(&p->lock);
 if(!p->poisoned&&p->route[0].chan) abort_job(p,-ENODEV);
 p->removed=true;mutex_unlock(&p->lock);
 cancel_delayed_work_sync(&p->watchdog);cancel_work_sync(&p->completion);
 mutex_lock(&p->lock);release_buffers(p);mutex_unlock(&p->lock);kref_put(&p->ref,destroy);
}
static const struct of_device_id match[]={ {.compatible="daphne,afe-dma-capture-v1"},{} };
MODULE_DEVICE_TABLE(of,match);
static struct platform_driver afe_driver={ .probe=probe,.remove=remove_device,
 .driver={.name="daphne-afe-dma",.of_match_table=match} };
module_platform_driver(afe_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("DAPHNE finite common-start AFE DMA chunk client");
