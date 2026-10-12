/* SPDX-License-Identifier: GPL-2.0 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include "daphne_afe_dma_uapi.h"
#include "afe_session_contract.h"
_Static_assert(sizeof(struct daphne_afe_dma_config)==32,"finite ABI");
_Static_assert(sizeof(struct daphne_afe_dma_status)==208,"finite status ABI");
_Static_assert(sizeof(struct daphne_afe_trigger_config)==48,"trigger ABI");
_Static_assert(sizeof(struct daphne_afe_trigger_status)==272,"trigger status ABI");
_Static_assert(sizeof(struct daphne_afe_session_config)==88,"session config ABI");
_Static_assert(sizeof(struct daphne_afe_event_id)==32,"ID ABI");
_Static_assert(sizeof(struct daphne_afe_session_event)==160,"event ABI");
_Static_assert(sizeof(struct daphne_afe_session_status)==184,"session status ABI");
_Static_assert(sizeof(struct daphne_afe_session_read)==64,"read ABI");
_Static_assert(sizeof(struct daphne_afe_session_batch)==24,"batch ABI");
_Static_assert(sizeof(struct daphne_afe_session_caps)==56,"caps ABI");
_Static_assert(offsetof(struct daphne_afe_session_config,session)==80,"config alignment");
_Static_assert(offsetof(struct daphne_afe_session_read,buffer)==56,"compat pointer");
_Static_assert(_IOC_NR(DAPHNE_AFE_ARM)==0x46,"existing ioctl unchanged");
_Static_assert(_IOC_SIZE(DAPHNE_AFE_SESSION_READ)==64,"ioctl size");
static unsigned int seed=20261011;
static unsigned int random32(void) {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
int main(void)
{
 unsigned int i,b,width,bit,r;
 __u32 words[24],before[24],release[7];
 __u64 value,total,physical;
 __u32 first_length;
 struct daphne_afe_session_config c={.abi=1,.flags=5,.length=17,.pretrigger=5,.period_ticks=8,
  .channel_mask=0xffffffffffULL,.target_events=100000,.session=0x1020304050607080ULL};
 struct daphne_afe_session_event e={};
 struct daphne_afe_event_id id={.session=99,.sequence=0x100000001ULL,.generation=0x40000001ULL,.slot=0},bad;
 for(i=0;i<50000;i++) {
  for(b=0;b<24;b++) before[b]=words[b]=random32();
  width=random32()%64+1;bit=random32()%(768-width+1);
  value=((__u64)random32()<<32)|random32();
  afe_put_bits(words,bit,width,value);
  assert(afe_bits(words,bit,width)==(width==64?value:value&((1ULL<<width)-1)));
  for(b=0;b<768;b++) if(b<bit||b>=bit+width) assert(((words[b/32]^before[b/32])&(1U<<(b%32)))==0);
 }
 c.ring_ticks[0]=64;c.ring_ticks[1]=80;c.ring_ticks[2]=96;
 afe_start_words(&c,words);
 assert(afe_bits(words,0,64)==c.session&&afe_bits(words,64,64)==100000);
 assert(afe_bits(words,128,40)==0xffffffffffULL&&afe_bits(words,168,32)==17);
 assert(afe_bits(words,200,32)==5&&afe_bits(words,232,32)==8);
 for(r=0;r<3;r++) assert(afe_bits(words,264+32*r,32)==c.ring_ticks[r]);
 assert(afe_bits(words,360,3)==4&&afe_bits(words,363,21)==0);
 memset(words,0,sizeof(words));afe_release_words(&id,release);memcpy(words,release,sizeof(release));
 afe_put_bits(words,224,64,65530);afe_put_bits(words,288,64,65552);
 afe_put_bits(words,352,64,70005);afe_put_bits(words,416,64,0xfedcba9876543210ULL);
 afe_put_bits(words,480,64,17);afe_put_bits(words,544,40,0x8000020001ULL);
 afe_put_bits(words,584,32,17);afe_put_bits(words,616,32,5);afe_put_bits(words,648,2,2);afe_put_bits(words,650,1,1);
 afe_event_words(words,&e);
 assert(afe_same_id(&e.id,&id)&&e.first_cursor==65530&&e.fence_end==65552&&e.trigger_index==70005);
 assert(e.timestamp==0xfedcba9876543210ULL&&e.segment==17&&e.source==2&&e.timestamp_valid);
 assert(e.valid_bytes[0]==34&&e.valid_bytes[1]==34&&e.valid_bytes[2]==34);
 assert(afe_release_check(&id,&id,AFE_SLOT_OWNED,0,id.sequence)==0);
 assert(afe_release_check(&id,&id,AFE_SLOT_OWNED,1,id.sequence)==-EBUSY);
 assert(afe_release_check(&id,&id,AFE_SLOT_READY,0,id.sequence)==-ESTALE);
 assert(afe_release_check(&id,&id,AFE_SLOT_RELEASING,0,id.sequence)==-ESTALE);
 bad=id;bad.generation++;assert(afe_release_check(&bad,&id,AFE_SLOT_OWNED,0,id.sequence)==-ESTALE);
 bad=id;bad.session++;assert(afe_release_check(&bad,&id,AFE_SLOT_OWNED,0,id.sequence)==-ESTALE);
 bad=id;bad.slot++;assert(afe_release_check(&bad,&id,AFE_SLOT_OWNED,0,id.sequence)==-ESTALE);
 bad=id;bad.reserved=1;assert(afe_release_check(&bad,&id,AFE_SLOT_OWNED,0,id.sequence)==-ESTALE);
 assert(afe_release_check(&id,&id,AFE_SLOT_OWNED,0,id.sequence+1)==-ESTALE);
 c.session=0;c.ring_ticks[0]=64;c.ring_ticks[1]=80;c.ring_ticks[2]=96;
 assert(afe_geometry(&c,448ULL<<20,4096,&total)==0&&c.ring_ticks[0]==96&&c.ring_ticks[2]==96&&total==12288);
 c.budget_bytes=total-1;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-ENOMEM);c.budget_bytes=0;
 c.channel_mask=1ULL<<39;memset(c.ring_ticks,0,sizeof(c.ring_ticks));
 assert(afe_geometry(&c,448ULL<<20,4096,&total)==0&&total==4096&&c.ring_ticks[0]==0&&c.ring_ticks[2]==64);
 assert(afe_geometry(&c,448ULL<<20,65536,&total)==0&&total==65536);
 c.target_events=0;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-EINVAL);c.target_events=1;
 c.channel_mask=1ULL<<40;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-EINVAL);c.channel_mask=1;
 c.source=1;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-EINVAL);c.source=0;
 c.pretrigger=c.length;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-EINVAL);c.pretrigger=5;
 c.period_ticks=12;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-EINVAL);c.period_ticks=8;
 c.length=0xffffffffU;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-E2BIG);c.length=17;
 c.ring_ticks[0]=4096;assert(afe_geometry(&c,448ULL<<20,4096,&total)==0); // 512 periods
 c.ring_ticks[0]=4104;assert(afe_geometry(&c,448ULL<<20,4096,&total)==-E2BIG);
 for(r=8;r<=64;r+=8) for(b=1;b<=16;b++) for(bit=0;bit<r;bit++) for(width=1;width<=r;width++) {
  unsigned int length=width*b*2;
  assert(afe_read_range(0x100000000ULL+bit,r,b,length,0,length,&physical,&first_length)==0);
  assert(physical==((0x100000000ULL+bit)%r)*b*2&&first_length<=length&&physical+first_length<=r*b*2);
  assert(first_length==length||first_length+(length-first_length)==length);
 }
 assert(afe_read_range(63,64,2,68,0,68,&physical,&first_length)==0&&physical==252&&first_length==4);
 assert(afe_read_range(63,64,2,68,68,1,&physical,&first_length)==-ERANGE);
 assert(afe_read_range(63,64,2,68,~0ULL,1,&physical,&first_length)==-ERANGE);
 assert(afe_read_range(63,64,0,68,0,1,&physical,&first_length)==-ERANGE);
 puts("AFE_DMA_SESSION_CONTRACT_PASS randomized_codecs=50000 layouts=11 ownership=1 ring_reads=1");
 return 0;
}
