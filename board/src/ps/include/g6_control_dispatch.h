#ifndef EYEPQC_G6_CONTROL_DISPATCH_H
#define EYEPQC_G6_CONTROL_DISPATCH_H

#include <stdint.h>

typedef int (*eye_g6_control_take_fn)(void *context, uint8_t *out,
                                      unsigned capacity);
typedef int (*eye_g6_control_handle_fn)(void *context, const uint8_t *message,
                                        unsigned length);

static inline void eye_g6_control_wipe(void *memory, unsigned length)
{
    volatile uint8_t *bytes = (volatile uint8_t *)memory;
    while (length--) *bytes++ = 0;
}

/* Return 0 when there is no input, 1 after handling a message, and -1 when
 * take/handling fails. A nonzero take result always consumes and clears the
 * full CPU-local buffer, including partial writes on a failed take. */
static inline int eye_g6_control_dispatch(
    uint8_t *buffer, unsigned capacity, eye_g6_control_take_fn take,
    eye_g6_control_handle_fn handle, void *context)
{
    int length = take(context, buffer, capacity);
    int status;

    if (length == 0) return 0;
    if (length < 0 || (unsigned)length > capacity) {
        eye_g6_control_wipe(buffer, capacity);
        return -1;
    }

    status = handle(context, buffer, (unsigned)length);
    eye_g6_control_wipe(buffer, capacity);
    return status ? -1 : 1;
}

#endif
