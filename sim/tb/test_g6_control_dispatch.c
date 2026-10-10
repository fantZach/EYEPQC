#include "g6_control_dispatch.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define CAPACITY 1036U

typedef struct {
    int take_result;
    int handle_result;
    unsigned take_calls;
    unsigned handle_calls;
    unsigned written;
    uint8_t expected[8];
} mock_control;

static int mock_take(void *opaque, uint8_t *out, unsigned capacity)
{
    mock_control *mock = (mock_control *)opaque;
    unsigned n = mock->written;
    ++mock->take_calls;
    assert(n <= capacity);
    if (n) memcpy(out, mock->expected, n);
    return mock->take_result;
}

static int mock_handle(void *opaque, const uint8_t *message, unsigned length)
{
    mock_control *mock = (mock_control *)opaque;
    ++mock->handle_calls;
    assert(length == mock->written);
    assert(memcmp(message, mock->expected, length) == 0);
    return mock->handle_result;
}

static int all_bytes(const uint8_t *buffer, unsigned length, uint8_t value)
{
    for (unsigned i = 0; i < length; ++i)
        if (buffer[i] != value) return 0;
    return 1;
}

static void fill_mock(mock_control *mock, int take_result, int handle_result,
                      unsigned written)
{
    memset(mock, 0, sizeof *mock);
    mock->take_result = take_result;
    mock->handle_result = handle_result;
    mock->written = written;
    for (unsigned i = 0; i < sizeof mock->expected; ++i)
        mock->expected[i] = (uint8_t)(0x31U + i);
}

int main(void)
{
    uint8_t buffer[CAPACITY];
    mock_control mock;

    fill_mock(&mock, 4, 0, 4);
    memset(buffer, 0xa5, sizeof buffer);
    assert(eye_g6_control_dispatch(buffer, sizeof buffer, mock_take,
                                  mock_handle, &mock) == 1);
    assert(mock.take_calls == 1 && mock.handle_calls == 1);
    assert(all_bytes(buffer, sizeof buffer, 0));

    fill_mock(&mock, 3, 1, 3);
    memset(buffer, 0xa5, sizeof buffer);
    assert(eye_g6_control_dispatch(buffer, sizeof buffer, mock_take,
                                  mock_handle, &mock) == -1);
    assert(mock.take_calls == 1 && mock.handle_calls == 1);
    assert(all_bytes(buffer, sizeof buffer, 0));

    /* A failed take can have copied only a prefix before reporting failure. */
    fill_mock(&mock, -1, 0, 5);
    memset(buffer, 0xa5, sizeof buffer);
    assert(eye_g6_control_dispatch(buffer, sizeof buffer, mock_take,
                                  mock_handle, &mock) == -1);
    assert(mock.take_calls == 1 && mock.handle_calls == 0);
    assert(all_bytes(buffer, sizeof buffer, 0));

    /* Zero means no message; this idle path must not scan/wipe the buffer. */
    fill_mock(&mock, 0, 0, 0);
    memset(buffer, 0xa5, sizeof buffer);
    assert(eye_g6_control_dispatch(buffer, sizeof buffer, mock_take,
                                  mock_handle, &mock) == 0);
    assert(mock.take_calls == 1 && mock.handle_calls == 0);
    assert(all_bytes(buffer, sizeof buffer, 0xa5));

    /* Reject impossible lengths and clear any partial payload without dispatch. */
    fill_mock(&mock, (int)sizeof buffer + 1, 0, 6);
    memset(buffer, 0xa5, sizeof buffer);
    assert(eye_g6_control_dispatch(buffer, sizeof buffer, mock_take,
                                  mock_handle, &mock) == -1);
    assert(mock.take_calls == 1 && mock.handle_calls == 0);
    assert(all_bytes(buffer, sizeof buffer, 0));

    puts("G6_CONTROL_DISPATCH normal=PASS handler_failure=PASS take_partial_failure=PASS idle=PASS oversized=PASS");
    return 0;
}
