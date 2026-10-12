#ifndef EYEPQC_DMA_BUFFERS_H
#define EYEPQC_DMA_BUFFERS_H
#include <stdint.h>
#define DMA_FRAME_CAPACITY 65536U
enum dma_owner { DMA_FREE, DMA_CAPTURING, DMA_READY, DMA_ENCRYPTING, DMA_SENDING };
struct dma_buffer { enum dma_owner owner; uint32_t length; };

static inline int dma_buffer_begin(struct dma_buffer slots[2])
{
    unsigned i;
    for (i=0;i<2;i++) if(slots[i].owner==DMA_FREE) {
        slots[i].owner=DMA_CAPTURING; slots[i].length=0; return (int)i;
    }
    return -1;
}
static inline int dma_buffer_complete(struct dma_buffer *slot, uint32_t length)
{
    if(slot->owner!=DMA_CAPTURING || !length || length>DMA_FRAME_CAPACITY) return -1;
    slot->length=length; slot->owner=DMA_READY; return 0;
}
static inline int dma_buffer_advance(struct dma_buffer *slot, enum dma_owner next)
{
    if(!((slot->owner==DMA_READY && (next==DMA_ENCRYPTING || next==DMA_SENDING)) ||
         (slot->owner==DMA_ENCRYPTING && next==DMA_SENDING) ||
         (slot->owner==DMA_SENDING && next==DMA_FREE))) return -1;
    slot->owner=next;
    if(next==DMA_FREE) slot->length=0;
    return 0;
}
// Caller must first confirm DMA reset/stop completion. Preserve consumer-owned buffers.
static inline void dma_buffers_abort(struct dma_buffer slots[2])
{
    unsigned i;
    for(i=0;i<2;i++) if(slots[i].owner==DMA_CAPTURING) {
        slots[i].owner=DMA_FREE; slots[i].length=0;
    }
}
#endif
