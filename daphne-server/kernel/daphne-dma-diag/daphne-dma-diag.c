// SPDX-License-Identifier: GPL-2.0
/* Finite diagnostic jobs only. Xilinx DMAengine owns all DMA register writes,
 * IRQs and hardware descriptors. This client owns producer writes and payloads.
 * One packet per transaction preserves completion accounting during STOP.
 */
#include <linux/dmaengine.h>
#include <linux/dma-mapping.h>
#include <linux/fs.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/kref.h>
#include <linux/ktime.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/overflow.h>
#include <linux/platform_device.h>
#include <linux/poll.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/workqueue.h>
#include <linux/compat.h>
#include <linux/version.h>
#include "daphne_dma_uapi.h"
#include "dma_layout.h"

#define P_MAGIC 0x00
#define P_ABI 0x04
#define P_PATH 0x08
#define P_COMMAND 0x0c
#define P_BEATS 0x10
#define P_PACKETS 0x14
#define P_SEED 0x18
#define P_NUM 0x1c
#define P_DEN 0x20
#define P_STATUS 0x24
#define P_ACCEPT_LO 0x28
#define P_ACCEPT_HI 0x2c
#define P_COMPLETED 0x30
#define P_BUSY BIT(0)
#define P_DONE BIT(1)
#define P_ERROR BIT(2)
#define P_DIAG BIT(3)
#define D_HALTED BIT(0)
#define D_SG BIT(3)
#define D_ERRORS 0x770U
#define D_RUN BIT(0)
#define D_RESET BIT(2)

struct capture_block {
 void *cpu;
 dma_addr_t dma;
 size_t allocation;
 u32 length;
 u64 offset;
};
struct dma_path {
 struct miscdevice misc;
 struct device *dev, *dma_dev;
 struct kref ref;
 struct mutex lock;
 struct work_struct completion_work;
 struct delayed_work timeout_work;
 wait_queue_head_t wait;
 void __iomem *producer, *identity, *monitor;
 struct dma_chan *chan;
 struct capture_block *buffer;
 struct scatterlist *sg;
 struct daphne_dma_config config;
 struct daphne_dma_status status;
 u32 blocks_per_packet;
 bool opened, removed, armed, poisoned;
 /* Callback publishes result before scheduling work; mutex protects the job. */
 struct dmaengine_result result;
 atomic_t callback_ready;
};

static unsigned int max_pool_mib = 448;
module_param(max_pool_mib, uint, 0444);
MODULE_PARM_DESC(max_pool_mib, "Aggregate payload allocation limit (1..480 MiB)");
static DEFINE_MUTEX(pool_lock);
static u64 pool_used;

static bool active(struct dma_path *p)
{
 return p->status.state == DAPHNE_DMA_RUNNING ||
        p->status.state == DAPHNE_DMA_STOPPING;
}

static void path_destroy(struct kref *ref)
{
 struct dma_path *p = container_of(ref, struct dma_path, ref);
 put_device(p->dev);
 kfree(p->misc.name);
 kfree(p);
}

/* Called with the path mutex, after admission to a raw-dma overlay. */
static void snapshot(struct dma_path *p)
{
 u32 hi, lo, again;
 do {
  hi = readl(p->producer + P_ACCEPT_HI);
  lo = readl(p->producer + P_ACCEPT_LO);
  again = readl(p->producer + P_ACCEPT_HI);
 } while (hi != again);
 p->status.accepted_beats = ((u64)hi << 32) | lo;
 p->status.producer_packets = readl(p->producer + P_COMPLETED);
 p->status.producer_status = readl(p->producer + P_STATUS);
 p->status.dma_control = readl(p->monitor);
 p->status.dma_status = readl(p->monitor + 4);
}

static int identify(struct dma_path *p)
{
 p->status.capabilities = readl(p->identity);
 p->status.magic = readl(p->identity + 0x10);
 p->status.gateware_abi = readl(p->identity + 0x14);
 p->status.variant = readl(p->identity + 0x18);
 p->status.build_id = readl(p->identity + 0x1c);
 if (p->status.magic != 0x44415048 ||
     p->status.gateware_abi != 0x00020000 ||
     p->status.variant != 3 || (p->status.build_id & 0xf0000000) ||
     p->status.capabilities != 0x00000520)
  return -EPROTO;
 if (readl(p->producer + P_MAGIC) != 0x444d4150 ||
     readl(p->producer + P_ABI) != 1 ||
     readl(p->producer + P_PATH) != p->status.path)
  return -EPROTO;
 return 0;
}

static bool guards_valid(struct dma_path *p)
{
 u32 i;
 dma_rmb();
 for (i = 0; p->buffer && i < p->status.blocks; ++i) {
  struct capture_block *b = &p->buffer[i];
  if (memchr_inv(b->cpu, DAPHNE_DMA_GUARD_VALUE, DAPHNE_DMA_GUARD_BYTES) ||
      memchr_inv(b->cpu + DAPHNE_DMA_GUARD_BYTES + b->length,
                 DAPHNE_DMA_GUARD_VALUE,
                 b->allocation - DAPHNE_DMA_GUARD_BYTES - b->length))
   return false;
 }
 return true;
}

/* Never free payloads, driver descriptors or the channel on an unproven halt.
 * Pin the module and device until reboot rather than enable use-after-free DMA.
 */
static void quarantine(struct dma_path *p)
{
 if (!p->poisoned) {
  p->poisoned = true;
  __module_get(THIS_MODULE);
  kref_get(&p->ref);
 }
 p->status.state = DAPHNE_DMA_QUARANTINED;
 p->status.error = -EIO;
 dev_crit(p->dev, "path %u: halt/reset not proven; buffers quarantined, reboot required\n",
          p->status.path);
 wake_up_all(&p->wait);
}

static int halt_dma_path(struct dma_path *p)
{
 u32 value;
 int err;
 if (!p->chan)
  return 0;
 err = dmaengine_terminate_sync(p->chan);
 /* Some Xilinx versions ignore stop/reset errors in their return value. */
 if (!err)
  err = readl_poll_timeout(p->monitor + 4, value,
                           value & D_HALTED, 10, 100000);
 if (!err)
  err = readl_poll_timeout(p->monitor, value,
                           !(value & (D_RUN | D_RESET)), 10, 100000);
 if (!err)
  err = readl_poll_timeout(p->producer + P_STATUS, value,
                           !(value & P_BUSY), 10, 100000);
 p->armed = false;
 snapshot(p);
 if (err)
  quarantine(p);
 return err;
}

static void free_buffers(struct dma_path *p)
{
 u32 i;
 if (p->poisoned)
  return;
 for (i = 0; p->buffer && i < p->status.blocks; ++i) {
  struct capture_block *b = &p->buffer[i];
  if (b->cpu)
   dma_free_coherent(p->dma_dev, b->allocation, b->cpu, b->dma);
 }
 kfree(p->buffer);
 kfree(p->sg);
 p->buffer = NULL;
 p->sg = NULL;
 mutex_lock(&pool_lock);
 pool_used -= p->status.allocated_bytes;
 mutex_unlock(&pool_lock);
 p->status.allocated_bytes = 0;
 p->status.blocks = 0;
}

static void abort_job(struct dma_path *p, int error)
{
 struct daphne_dma_status before_reset;
 /* Mark terminal before terminate_sync: late callback work cannot rearm. */
 p->status.state = error ? DAPHNE_DMA_ERROR : DAPHNE_DMA_ABORTED;
 p->status.error = error;
 cancel_delayed_work(&p->timeout_work);
 snapshot(p); /* Retain progress prior to producer reset in the log below. */
 before_reset = p->status;
 dev_dbg(p->dev, "abort path %u: accepted=%llu packets=%u\n", p->status.path,
          p->status.accepted_beats, p->status.producer_packets);
 halt_dma_path(p);
 if (!p->poisoned)
  p->status = before_reset; /* Freeze the failure evidence, not reset counters. */
 p->status.end_ns = ktime_get_ns();
 if (!p->poisoned && p->buffer)
  p->status.guards_ok = guards_valid(p);
 wake_up_all(&p->wait);
}

static void transfer_callback(void *context, const struct dmaengine_result *result)
{
 struct dma_path *p = context;
 /* A driver without callback_result/residue support cannot qualify lengths. */
 if (result)
  p->result = *result;
 else {
  p->result.result = DMA_TRANS_ABORTED;
  p->result.residue = 0;
 }
 atomic_set_release(&p->callback_ready, 1);
 schedule_work(&p->completion_work);
}

static int arm_packet(struct dma_path *p)
{
 struct dma_async_tx_descriptor *tx;
 dma_cookie_t cookie;
 u32 i, first = p->status.completed_packets * p->blocks_per_packet;
 sg_init_table(p->sg, p->blocks_per_packet);
 for (i = 0; i < p->blocks_per_packet; ++i) {
  struct capture_block *b = &p->buffer[first + i];
  /* These coherent allocations already have DMA API addresses. They must
   * not be dma_map_sg'ed a second time. No CPU physical address is invented.
   */
  sg_dma_address(&p->sg[i]) = b->dma + DAPHNE_DMA_GUARD_BYTES;
  sg_dma_len(&p->sg[i]) = b->length;
 }
 dma_wmb();
 tx = dmaengine_prep_slave_sg(p->chan, p->sg, p->blocks_per_packet,
                             DMA_DEV_TO_MEM, DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
 if (!tx)
  return -ENOMEM;
 tx->callback_result = transfer_callback;
 tx->callback_param = p;
 cookie = dmaengine_submit(tx);
 if (dma_submit_error(cookie))
  return dma_submit_error(cookie);
 p->armed = true;
 dma_async_issue_pending(p->chan);
 return 0;
}

static void finish_job(struct dma_path *p)
{
 u32 ps;
 int err = readl_poll_timeout(p->producer + P_STATUS, ps,
                              !(ps & P_BUSY), 1, 10000);
 snapshot(p);
 p->status.end_ns = ktime_get_ns();
 p->status.guards_ok = guards_valid(p);
 if (err || !(ps & P_DONE) || (ps & P_ERROR) ||
     !(p->status.dma_status & D_SG) || (p->status.dma_status & D_ERRORS) ||
     !p->status.guards_ok ||
     p->status.producer_packets != p->status.completed_packets ||
     p->status.accepted_beats * 16 != p->status.received_bytes) {
  abort_job(p, -EIO);
  return;
 }
 p->status.state = p->status.state == DAPHNE_DMA_STOPPING ?
                    DAPHNE_DMA_STOPPED : DAPHNE_DMA_COMPLETE;
 cancel_delayed_work(&p->timeout_work);
 wake_up_all(&p->wait);
}

static void completion_work(struct work_struct *work)
{
 struct dma_path *p = container_of(work, struct dma_path, completion_work);
 u64 packet_bytes;
 int err;
 mutex_lock(&p->lock);
 if (p->removed || !active(p) || !atomic_read_acquire(&p->callback_ready))
  goto out;
 atomic_set(&p->callback_ready, 0);
 p->armed = false;
 packet_bytes = (u64)p->config.beats * 16;
 if (p->result.result != DMA_TRANS_NOERROR || p->result.residue) {
  abort_job(p, -EIO);
  goto out;
 }
 p->status.completed_packets++;
 p->status.received_bytes += packet_bytes;
 /* STOP may arrive while the producer holds the first beat of the NEXT
  * packet under backpressure. Supply that packet's buffers to drain it.
  */
 if (p->status.completed_packets == p->config.packets ||
     (p->status.state == DAPHNE_DMA_STOPPING &&
      !(readl(p->producer + P_STATUS) & P_BUSY)))
  finish_job(p);
 else {
  err = arm_packet(p);
  if (err)
   abort_job(p, err);
 }
out:
 mutex_unlock(&p->lock);
}

static void timeout_work(struct work_struct *work)
{
 struct dma_path *p = container_of(to_delayed_work(work), struct dma_path, timeout_work);
 mutex_lock(&p->lock);
 if (!p->removed && active(p)) {
  u64 deadline = p->status.start_ns + (u64)p->config.timeout_ms * 1000000;
  u64 now = ktime_get_ns();
  if (now >= deadline)
   abort_job(p, -ETIMEDOUT);
  else
   schedule_delayed_work(&p->timeout_work,
                         nsecs_to_jiffies(deadline - now) + 1);
 }
 mutex_unlock(&p->lock);
}

static int prepare(struct dma_path *p, const struct daphne_dma_config *cfg)
{
 struct daphne_dma_layout layout;
 u64 packet, blocks, allocation, requested;
 u32 i;
 int err;
 if (active(p) || p->poisoned)
  return -EBUSY;
 err = daphne_dma_layout(cfg, PAGE_SIZE, &layout);
 if (err)
  return err;
 packet = layout.packet_bytes;
 blocks = layout.blocks_per_packet;
 requested = layout.requested_bytes;
 allocation = layout.allocated_bytes;
 err = identify(p);
 if (err || p->status.build_id != cfg->expected_build_id)
  return err ?: -ESTALE;
 if (p->chan) {
  err = halt_dma_path(p);
  if (err)
   return err;
  free_buffers(p);
 } else {
  p->chan = dma_request_chan(p->dev, "rx");
  if (IS_ERR(p->chan)) {
   err = PTR_ERR(p->chan);
   p->chan = NULL;
   return err;
  }
  p->dma_dev = dmaengine_get_dma_device(p->chan);
  if (!p->dma_dev->dma_mask || *p->dma_dev->dma_mask != DMA_BIT_MASK(40) ||
      p->dma_dev->coherent_dma_mask != DMA_BIT_MASK(40)) {
   err = -EPROTO;
   goto release_channel;
  }
  err = halt_dma_path(p);
  if (err)
   return err;
 }
 mutex_lock(&pool_lock);
 if (allocation > ((u64)max_pool_mib << 20) - pool_used) {
  mutex_unlock(&pool_lock);
  err = -ENOMEM;
  goto release_channel;
 }
 pool_used += allocation;
 mutex_unlock(&pool_lock);
 p->status.allocated_bytes = allocation;
 p->status.blocks = blocks * cfg->packets;
 p->blocks_per_packet = blocks;
 p->status.requested_bytes = requested;
 p->status.received_bytes = 0;
 p->status.completed_packets = 0;
 p->status.start_ns = p->status.end_ns = 0;
 p->status.guards_ok = 0;
 p->status.error = 0;
 p->config = *cfg;
 p->buffer = kcalloc(p->status.blocks, sizeof(*p->buffer), GFP_KERNEL);
 p->sg = kcalloc(blocks, sizeof(*p->sg), GFP_KERNEL);
 if (!p->buffer || !p->sg) {
  err = -ENOMEM;
  goto free;
 }
 for (i = 0; i < p->status.blocks; ++i) {
  struct capture_block *b = &p->buffer[i];
  u32 segment = i % p->blocks_per_packet;
  b->length = min_t(u64, packet - (u64)segment * DAPHNE_DMA_CHUNK_BYTES,
                         DAPHNE_DMA_CHUNK_BYTES);
  b->offset = (u64)(i / p->blocks_per_packet) * packet +
              (u64)segment * DAPHNE_DMA_CHUNK_BYTES;
  b->allocation = PAGE_ALIGN(b->length + 2 * DAPHNE_DMA_GUARD_BYTES);
  b->cpu = dma_alloc_coherent(p->dma_dev, b->allocation, &b->dma, GFP_KERNEL);
  if (!b->cpu) {
   err = -ENOMEM;
   goto free;
  }
  if ((b->dma & 15) || b->dma + b->allocation - 1 > DMA_BIT_MASK(40)) {
   err = -ERANGE;
   goto free;
  }
  memset(b->cpu, DAPHNE_DMA_GUARD_VALUE, b->allocation);
 }
 atomic_set(&p->callback_ready, 0);
 p->status.state = DAPHNE_DMA_PREPARED;
 snapshot(p);
 return 0;
free:
 /* Nothing was submitted; all partial allocations are CPU-owned. */
 free_buffers(p);
release_channel:
 dma_release_channel(p->chan);
 p->chan = NULL;
 p->status.state = DAPHNE_DMA_ERROR;
 p->status.error = err;
 return err;
}

static int path_open(struct inode *inode, struct file *file)
{
 struct dma_path *p = container_of(file->private_data, struct dma_path, misc);
 int err = 0;
 mutex_lock(&p->lock);
 if (p->removed || p->poisoned)
  err = -ENODEV;
 else if (p->opened)
  err = -EBUSY;
 else {
  p->opened = true;
  kref_get(&p->ref);
  file->private_data = p;
 }
 mutex_unlock(&p->lock);
 return err;
}

static int path_release(struct inode *inode, struct file *file)
{
 struct dma_path *p = file->private_data;
 mutex_lock(&p->lock);
 if (!p->removed && p->chan && !p->poisoned)
  abort_job(p, 0);
 mutex_unlock(&p->lock);
 /* Do not wait for work while holding the mutex it needs. */
 cancel_delayed_work_sync(&p->timeout_work);
 cancel_work_sync(&p->completion_work);
 mutex_lock(&p->lock);
 if (!p->poisoned) {
  free_buffers(p);
  if (p->chan)
   dma_release_channel(p->chan);
  p->chan = NULL;
  p->status.state = DAPHNE_DMA_IDLE;
 }
 p->opened = false;
 mutex_unlock(&p->lock);
 kref_put(&p->ref, path_destroy);
 return 0;
}

static long path_ioctl(struct file *file, unsigned int command, unsigned long arg)
{
 struct dma_path *p = file->private_data;
 struct daphne_dma_config cfg;
 struct daphne_dma_block_info block;
 u32 ps;
 int err = 0;
 mutex_lock(&p->lock);
 if (p->removed) {
  err = -ENODEV;
  goto out;
 }
 if (p->poisoned && command != DAPHNE_DMA_STATUS) {
  err = -EIO;
  goto out;
 }
 switch (command) {
 case DAPHNE_DMA_PREPARE:
  if (copy_from_user(&cfg, (void __user *)arg, sizeof(cfg)))
   err = -EFAULT;
  else {
   err = prepare(p, &cfg);
   if (!err)
    file->f_pos = 0;
  }
  break;
 case DAPHNE_DMA_START:
  if (p->status.state != DAPHNE_DMA_PREPARED) {
   err = -EINVAL;
   break;
  }
  err = identify(p);
  if (err || p->status.build_id != p->config.expected_build_id) {
   err = err ?: -ESTALE;
   break;
  }
  ps = readl(p->producer + P_STATUS);
  if ((ps & P_BUSY) || !(ps & P_DIAG)) {
   err = -EBUSY;
   break;
  }
  writel(4, p->producer + P_COMMAND);
  writel(p->config.beats, p->producer + P_BEATS);
  writel(p->config.packets, p->producer + P_PACKETS);
  writel(p->config.seed, p->producer + P_SEED);
  writel(p->config.rate_num, p->producer + P_NUM);
  writel(p->config.rate_den, p->producer + P_DEN);
  p->status.state = DAPHNE_DMA_RUNNING;
  err = arm_packet(p);
  if (err) {
   abort_job(p, err);
   break;
  }
  p->status.start_ns = ktime_get_ns();
  writel(1, p->producer + P_COMMAND);
  schedule_delayed_work(&p->timeout_work, msecs_to_jiffies(p->config.timeout_ms));
  break;
 case DAPHNE_DMA_STOP:
  if (active(p)) {
   p->status.state = DAPHNE_DMA_STOPPING;
   writel(2, p->producer + P_COMMAND);
  } else if (p->status.state != DAPHNE_DMA_COMPLETE &&
             p->status.state != DAPHNE_DMA_STOPPED)
   err = -EINVAL;
  break;
 case DAPHNE_DMA_ABORT:
  if (p->chan)
   abort_job(p, 0);
  break;
 case DAPHNE_DMA_STATUS:
  if (active(p) || p->status.state == DAPHNE_DMA_PREPARED ||
      p->status.state == DAPHNE_DMA_IDLE)
   snapshot(p);
  if (copy_to_user((void __user *)arg, &p->status, sizeof(p->status)))
   err = -EFAULT;
  break;
 case DAPHNE_DMA_BLOCK:
  if (copy_from_user(&block, (void __user *)arg, sizeof(block))) {
   err = -EFAULT;
   break;
  }
  if (block.abi != DAPHNE_DMA_ABI || block.reserved ||
      block.index >= p->status.blocks) {
   err = -EINVAL;
   break;
  }
  block.dma_address = p->buffer[block.index].dma + DAPHNE_DMA_GUARD_BYTES;
  block.logical_offset = p->buffer[block.index].offset;
  block.length = p->buffer[block.index].length;
  if (copy_to_user((void __user *)arg, &block, sizeof(block)))
   err = -EFAULT;
  break;
 default:
  err = -ENOTTY;
 }
out:
 mutex_unlock(&p->lock);
 return err;
}

static ssize_t path_read(struct file *file, char __user *target, size_t size, loff_t *pos)
{
 struct dma_path *p = file->private_data;
 ssize_t copied = 0;
 u32 i;
 mutex_lock(&p->lock);
 if (p->removed || p->poisoned) {
  copied = -ENODEV;
  goto out;
 }
 if (p->status.state != DAPHNE_DMA_COMPLETE && p->status.state != DAPHNE_DMA_STOPPED) {
  copied = -EBUSY;
  goto out;
 }
 dma_rmb();
 for (i = 0; i < p->status.blocks && size && *pos < p->status.received_bytes; ++i) {
  struct capture_block *b = &p->buffer[i];
  size_t offset, n;
  if (*pos >= b->offset + b->length)
   continue;
  offset = *pos - b->offset;
  n = min(size, b->length - offset);
  n = min_t(u64, n, p->status.received_bytes - *pos);
  if (copy_to_user(target + copied, b->cpu + DAPHNE_DMA_GUARD_BYTES + offset, n)) {
   if (!copied)
    copied = -EFAULT;
   break;
  }
  *pos += n;
  size -= n;
  copied += n;
 }
out:
 mutex_unlock(&p->lock);
 return copied;
}

static __poll_t path_poll(struct file *file, poll_table *wait)
{
 struct dma_path *p = file->private_data;
 __poll_t result = 0;
 poll_wait(file, &p->wait, wait);
 mutex_lock(&p->lock);
 if (p->removed || p->poisoned || p->status.state == DAPHNE_DMA_ERROR)
  result = EPOLLERR;
 else if (p->status.state == DAPHNE_DMA_COMPLETE || p->status.state == DAPHNE_DMA_STOPPED)
  result = EPOLLIN | EPOLLRDNORM;
 else if (p->status.state == DAPHNE_DMA_ABORTED)
  result = EPOLLHUP;
 mutex_unlock(&p->lock);
 return result;
}

static const struct file_operations path_fops = {
 .owner = THIS_MODULE,
 .open = path_open, .release = path_release,
 .unlocked_ioctl = path_ioctl,
 .compat_ioctl = compat_ptr_ioctl,
 .read = path_read, .poll = path_poll,
};

static int validate_dt(struct platform_device *pdev, u32 path)
{
 struct of_phandle_args spec;
 struct resource r;
 struct device_node *node;
 int err = of_parse_phandle_with_args(pdev->dev.of_node, "dmas", "#dma-cells", 0, &spec);
 if (err)
  return err;
 err = -EINVAL;
 if (spec.args_count != 1 || spec.args[0] != 1 ||
     !of_device_is_compatible(spec.np, "xlnx,axi-dma-1.00.a") ||
     of_address_to_resource(spec.np, 0, &r) ||
     r.start != 0xb0020000ULL + (u64)path * 0x20000 || resource_size(&r) != 0x10000)
  goto out;
 /* HP ports are not coherent, including any inherited DT claim. */
 for (node = of_node_get(spec.np); node; node = of_get_next_parent(node))
  if (of_property_read_bool(node, "dma-coherent")) {
   of_node_put(node);
   goto out;
  }
 {
  u32 width, len;
  if (of_property_read_u32(spec.np, "xlnx,addrwidth", &width) || width != 40 ||
      of_property_read_u32(spec.np, "xlnx,sg-length-width", &len) || len != 26 ||
      !of_property_read_bool(spec.np, "xlnx,include-sg"))
   goto out;
 }
 {
  struct device_node *child;
  unsigned int channels = 0;
  for_each_available_child_of_node(spec.np, child) {
   u32 width;
   if (!of_device_is_compatible(child, "xlnx,axi-dma-s2mm-channel") ||
       of_property_read_u32(child, "xlnx,datawidth", &width) || width != 128 ||
       of_property_read_bool(child, "xlnx,include-dre")) {
    of_node_put(child);
    goto out;
   }
   ++channels;
  }
  if (channels != 1)
   goto out;
 }
 err = 0;
out:
 of_node_put(spec.np);
 return err;
}

static int path_probe(struct platform_device *pdev)
{
 struct dma_path *p;
 struct resource *r;
 u32 path;
 int err;
 if (max_pool_mib < 1 || max_pool_mib > 480 ||
     of_property_read_u32(pdev->dev.of_node, "daphne,path-id", &path) || path > 2)
  return -EINVAL;
 err = validate_dt(pdev, path);
 if (err)
  return dev_err_probe(&pdev->dev, err, "invalid raw-dma DT contract\n");
 p = kzalloc(sizeof(*p), GFP_KERNEL);
 if (!p)
  return -ENOMEM;
 p->dev = get_device(&pdev->dev);
 kref_init(&p->ref);
 mutex_init(&p->lock);
 INIT_WORK(&p->completion_work, completion_work);
 INIT_DELAYED_WORK(&p->timeout_work, timeout_work);
 init_waitqueue_head(&p->wait);
 p->status.abi = DAPHNE_DMA_ABI;
 p->status.path = path;
 p->producer = devm_platform_ioremap_resource_byname(pdev, "producer");
 if (IS_ERR(p->producer)) {
  err = PTR_ERR(p->producer);
  goto fail;
 }
 r = platform_get_resource_byname(pdev, IORESOURCE_MEM, "producer");
 if (r->start != 0xb0030000ULL + (u64)path * 0x20000 || resource_size(r) != 0x1000) {
  err = -EINVAL;
  goto fail;
 }
 /* Identity is shared read-only; monitor overlaps the provider read-only.
  * Do not claim its region or write DMA registers behind DMAengine's back.
  */
 r = platform_get_resource_byname(pdev, IORESOURCE_MEM, "identity");
 if (!r || r->start != 0x940000e0 || resource_size(r) != 0x20) {
  err = -EINVAL;
  goto fail;
 }
 p->identity = devm_ioremap(&pdev->dev, r->start, resource_size(r));
 r = platform_get_resource_byname(pdev, IORESOURCE_MEM, "dma-monitor");
 if (!r || r->start != 0xb0020030ULL + (u64)path * 0x20000 || resource_size(r) != 8) {
  err = -EINVAL;
  goto fail;
 }
 p->monitor = devm_ioremap(&pdev->dev, r->start, resource_size(r));
 if (!p->identity || !p->monitor) {
  err = -ENOMEM;
  goto fail;
 }
 err = identify(p);
 if (err)
  goto fail;
 p->misc.minor = MISC_DYNAMIC_MINOR;
 p->misc.name = kasprintf(GFP_KERNEL, "daphne-dma%u", path);
 p->misc.fops = &path_fops;
 p->misc.parent = &pdev->dev;
 p->misc.mode = 0600;
 if (!p->misc.name) {
  err = -ENOMEM;
  goto fail;
 }
 err = misc_register(&p->misc);
 if (err)
  goto fail;
 platform_set_drvdata(pdev, p);
 return 0;
fail:
 kref_put(&p->ref, path_destroy);
 return err;
}

static void path_remove(struct platform_device *pdev)
{
 struct dma_path *p = platform_get_drvdata(pdev);
 misc_deregister(&p->misc);
 mutex_lock(&p->lock);
 if (p->chan && !p->poisoned)
  abort_job(p, -ENODEV);
 p->removed = true;
 wake_up_all(&p->wait);
 mutex_unlock(&p->lock);
 cancel_delayed_work_sync(&p->timeout_work);
 cancel_work_sync(&p->completion_work);
 mutex_lock(&p->lock);
 if (!p->poisoned) {
  free_buffers(p);
  if (p->chan)
   dma_release_channel(p->chan);
  p->chan = NULL;
 }
 mutex_unlock(&p->lock);
 kref_put(&p->ref, path_destroy);
}

static const struct of_device_id path_match[] = {
 { .compatible = "daphne,raw-dma-diagnostic-v1" }, {}
};
MODULE_DEVICE_TABLE(of, path_match);
static struct platform_driver path_driver = {
 .probe = path_probe,
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 11, 0)
 .remove_new = path_remove,
#else
 .remove = path_remove,
#endif
 .driver = { .name = "daphne-dma-diag", .of_match_table = path_match,
             .suppress_bind_attrs = true },
};
module_platform_driver(path_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("DAPHNE finite raw-dma diagnostic client (not AFE capture)");
