/* SPDX-License-Identifier: GPL-2.0 */
#ifndef AFE_SESSION_CONTRACT_H
#define AFE_SESSION_CONTRACT_H
#include "daphne_afe_session_uapi.h"
#include <linux/errno.h>
enum afe_slot_state { AFE_SLOT_FREE,AFE_SLOT_READY,AFE_SLOT_OWNED,AFE_SLOT_RELEASING };
#define SESSION_CAP_BIT 7
#define S_API 0x200
#define S_MAGIC 0x204
#define S_FEATURES 0x208
#define S_SLOTS 0x20c
#define S_COMMAND 0x210
#define S_REJECT 0x214
#define S_FLAGS 0x218
#define S_CONFIG 0x240
#define S_EVENT 0x280
#define S_RELEASE 0x2e0
#define S_REPLY 0x2fc
#define S_STATUS 0x300
#define S_COMPLETED 0x360
#define S_EXPORTED 0x368
#define S_SNAPSHOT_FLAGS 0x370
#define S_REGIONS 0x380
/* Ordered payload prefixes, ownership, IRQ, bound regions, live DMA quiet proof. */
#define S_REQUIRED_FEATURES 31U
#define S_START 1
#define S_CANCEL 2
#define S_RESET 4
#define S_SNAPSHOT 8
#define S_POP 16
#define S_ACK_RELEASE 32
#define S_POP_REPLY 64
#define S_SW_TRIGGER 256
/* Bit codecs use shifts on values returned by readl, independent of CPU endian.
 * All fields are at most 64 bits; reserved fields are separately checked.
 */
static inline __u64 afe_bits(const __u32 *words, unsigned int bit, unsigned int width)
{
 __u64 value=0;
 unsigned int i;
 for(i=0;i<width;i++) value|=(__u64)((words[(bit+i)/32]>>((bit+i)%32))&1)<<i;
 return value;
}
static inline void afe_put_bits(__u32 *words,unsigned int bit,unsigned int width,__u64 value)
{
 unsigned int i;
 for(i=0;i<width;i++) {
  __u32 mask=(__u32)1<<((bit+i)%32);
  words[(bit+i)/32]=(words[(bit+i)/32]&~mask)|(((value>>i)&1)?mask:0);
 }
}
static inline unsigned int afe_channels(__u64 mask,unsigned int route)
{
 unsigned int n=0,c;
 for(c=route*16;c<40&&c<route*16+16;c++) n+=(mask>>c)&1;
 return n;
}
static inline int afe_same_id(const struct daphne_afe_event_id *a,const struct daphne_afe_event_id *b)
{
 return !a->reserved&&!b->reserved&&a->session==b->session&&a->sequence==b->sequence&&
        a->generation==b->generation&&a->slot==b->slot;
}
static inline void afe_start_words(const struct daphne_afe_session_config *c,__u32 words[12])
{
 unsigned int i;
 for(i=0;i<12;i++) words[i]=0;
 afe_put_bits(words,0,64,c->session);afe_put_bits(words,64,64,c->target_events);
 afe_put_bits(words,128,40,c->channel_mask);afe_put_bits(words,168,32,c->length);
 afe_put_bits(words,200,32,c->pretrigger);afe_put_bits(words,232,32,c->period_ticks);
 for(i=0;i<3;i++) afe_put_bits(words,264+32*i,32,c->ring_ticks[i]);
 afe_put_bits(words,360,2,c->source);afe_put_bits(words,362,1,!!(c->flags&4));
}
static inline void afe_release_words(const struct daphne_afe_event_id *id,__u32 words[7])
{
 unsigned int i;
 for(i=0;i<7;i++) words[i]=0;
 afe_put_bits(words,0,64,id->session);afe_put_bits(words,64,64,id->sequence);
 afe_put_bits(words,128,32,id->slot);afe_put_bits(words,160,64,id->generation);
}
static inline void afe_event_words(const __u32 words[22],struct daphne_afe_session_event *e)
{
 unsigned int r;
 e->id.session=afe_bits(words,0,64);e->id.sequence=afe_bits(words,64,64);
 e->id.slot=(__u32)afe_bits(words,128,32);e->id.generation=afe_bits(words,160,64);e->id.reserved=0;
 e->first_cursor=afe_bits(words,224,64);e->fence_end=afe_bits(words,288,64);
 e->trigger_index=afe_bits(words,352,64);e->timestamp=afe_bits(words,416,64);
 e->segment=afe_bits(words,480,64);e->channel_mask=afe_bits(words,544,40);
 e->length=(__u32)afe_bits(words,584,32);e->pretrigger=(__u32)afe_bits(words,616,32);
 e->source=(__u32)afe_bits(words,648,2);e->timestamp_valid=(__u32)afe_bits(words,650,1);
 e->hardware_error=0;e->reserved=0;
 for(r=0;r<3;r++) e->valid_bytes[r]=(__u64)e->length*2*afe_channels(e->channel_mask,r);
 for(r=0;r<4;r++) e->ignored[r]=0;
}
static inline int afe_geometry(struct daphne_afe_session_config *c,__u64 pool,unsigned int page_size,__u64 *allocation)
{
 __u64 minimum,ring,total=0;
 unsigned int r,explicit_ring=0;
 if(!page_size||(page_size&(page_size-1))) return -EINVAL;
 if(c->abi!=1||c->reserved||c->slots||c->session||!c->target_events||!c->channel_mask||
    (c->channel_mask>>40)||!c->length||c->pretrigger>=c->length||c->source>2||
    (c->flags&~7U)||!(c->flags&3)||((c->flags&4)&&c->source!=0)||
    c->period_ticks<8||c->period_ticks>1048576||(c->period_ticks&(c->period_ticks-1))) return -EINVAL;
 if((c->trigger_timeout_ms&&(c->trigger_timeout_ms<10||c->trigger_timeout_ms>600000))||
    (c->pressure_timeout_ms&&(c->pressure_timeout_ms<10||c->pressure_timeout_ms>600000))) return -EINVAL;
 if(!c->trigger_timeout_ms) c->trigger_timeout_ms=30000;
 minimum=((__u64)c->length+3ULL*c->period_ticks-1)&~((__u64)c->period_ticks-1);
 ring=minimum;
 for(r=0;r<3;r++) if(afe_channels(c->channel_mask,r)&&c->ring_ticks[r]) {
  if(c->ring_ticks[r]<minimum||c->ring_ticks[r]%c->period_ticks) return -EINVAL;
  explicit_ring=1;
  if(c->ring_ticks[r]>ring) ring=c->ring_ticks[r];
 }
 if(!explicit_ring&&ring<8ULL*c->period_ticks) ring=8ULL*c->period_ticks;
 if(ring>0xffffffffULL||ring/c->period_ticks>512) return -E2BIG;
 for(r=0;r<3;r++) {
  __u64 bytes=ring*afe_channels(c->channel_mask,r)*2;
  if(bytes>(256ULL<<20)) return -E2BIG;
  c->ring_ticks[r]=bytes?(__u32)ring:0;
  if(bytes) total+=(bytes+128+page_size-1)&~((__u64)page_size-1);
 }
 if(total>pool||(c->budget_bytes&&total>c->budget_bytes)) return -ENOMEM;
 *allocation=total;return 0;
}
static inline int afe_release_check(const struct daphne_afe_event_id *wanted,
    const struct daphne_afe_event_id *actual,enum afe_slot_state state,unsigned int readers,__u64 sequence)
{
 if(state!=AFE_SLOT_OWNED||actual->sequence!=sequence||!afe_same_id(wanted,actual)) return -ESTALE;
 return readers?-EBUSY:0;
}
static inline int afe_read_range(__u64 first,__u32 ring,unsigned int channels,__u64 valid,
    __u64 offset,__u32 length,__u64 *physical,__u32 *first_length)
{
 __u64 bytes,base;
 if(!ring||!channels||!valid||!length||length>DAPHNE_AFE_SESSION_READ_MAX||
    offset>valid||length>valid-offset) return -ERANGE;
 bytes=(__u64)ring*channels*2;
 if(valid>bytes) return -ERANGE;
 base=(first%ring)*channels*2;
 *physical=(base+offset)%bytes;
 *first_length=bytes-*physical<length?(__u32)(bytes-*physical):length;
 return 0;
}
#endif
