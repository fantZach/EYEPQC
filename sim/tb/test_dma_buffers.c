#include "dma_buffers.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    struct dma_buffer slots[2]={{DMA_FREE,0},{DMA_FREE,0}};
    unsigned i;
    for(i=0;i<10000;i++) {
        int first=dma_buffer_begin(slots), second=dma_buffer_begin(slots);
        assert(first==0 && second==1 && dma_buffer_begin(slots)==-1);
        assert(dma_buffer_complete(&slots[0],0)==-1);
        assert(dma_buffer_complete(&slots[0],DMA_FRAME_CAPACITY+1)==-1);
        assert(dma_buffer_advance(&slots[0],DMA_FREE)==-1);
        assert(dma_buffer_complete(&slots[0],1+i%DMA_FRAME_CAPACITY)==0);
        assert(dma_buffer_complete(&slots[0],1)==-1);
        assert(dma_buffer_advance(&slots[0],DMA_ENCRYPTING)==0);
        dma_buffers_abort(slots);
        assert(slots[0].owner==DMA_ENCRYPTING && slots[1].owner==DMA_FREE);
        assert(dma_buffer_begin(slots)==1);
        assert(dma_buffer_complete(&slots[1],DMA_FRAME_CAPACITY)==0);
        assert(dma_buffer_advance(&slots[1],DMA_SENDING)==0);
        assert(dma_buffer_advance(&slots[1],DMA_CAPTURING)==-1);
        assert(dma_buffer_advance(&slots[0],DMA_SENDING)==0);
        dma_buffers_abort(slots);
        assert(slots[0].owner==DMA_SENDING && slots[1].owner==DMA_SENDING);
        assert(dma_buffer_begin(slots)==-1);
        assert(dma_buffer_advance(&slots[0],DMA_FREE)==0);
        assert(dma_buffer_advance(&slots[1],DMA_FREE)==0);
    }
    puts("DMA_BUFFERS_PASS rounds=10000 no_owned_buffer_overwrite");
    return 0;
}
