#include "protocol.h"
#include <string.h>

static void put_be(uint8_t *p, uint64_t value, unsigned bytes)
{
    while (bytes) { p[--bytes] = (uint8_t)value; value >>= 8; }
}

static uint64_t get_be(const uint8_t *p, unsigned bytes)
{
    uint64_t value = 0;
    while (bytes--) value = (value << 8) | *p++;
    return value;
}

int eye_video_validate(const struct eye_video_header *h)
{
    uint32_t count, expected;
    if (!h || h->version != EYE_VERSION || h->flags > EYE_ENCRYPTED ||
        h->header_length != EYE_HEADER_SIZE || h->reserved != 0 ||
        h->jpeg_length < 4 || h->jpeg_length > EYE_MAX_JPEG) return EYE_INVALID;
    count = (h->jpeg_length + EYE_MAX_PAYLOAD - 1) / EYE_MAX_PAYLOAD;
    if (h->packet_count != count || h->packet_id >= count) return EYE_INVALID;
    expected = h->jpeg_length - h->packet_id * EYE_MAX_PAYLOAD;
    if (expected > EYE_MAX_PAYLOAD) expected = EYE_MAX_PAYLOAD;
    return h->payload_length == expected ? EYE_OK : EYE_INVALID;
}

int eye_video_encode(uint8_t *out, size_t capacity, const struct eye_video_header *h)
{
    if (!out || capacity < EYE_HEADER_SIZE) return EYE_LENGTH;
    if (eye_video_validate(h) != EYE_OK) return EYE_INVALID;
    out[0] = h->version; out[1] = h->flags;
    put_be(out + 2, h->header_length, 2);
    put_be(out + 4, h->session_id, 4); put_be(out + 8, h->frame_id, 4);
    put_be(out + 12, h->packet_id, 2); put_be(out + 14, h->packet_count, 2);
    put_be(out + 16, h->jpeg_length, 4); put_be(out + 20, h->payload_length, 2);
    put_be(out + 22, h->reserved, 2); put_be(out + 24, h->timestamp, 8);
    put_be(out + 32, h->packet_sequence, 8);
    return EYE_OK;
}

int eye_video_decode(struct eye_video_header *h, const uint8_t *in, size_t length)
{
    struct eye_video_header decoded;
    if (!h || !in || length != EYE_HEADER_SIZE) return EYE_LENGTH;
    decoded.version = in[0]; decoded.flags = in[1];
    decoded.header_length = (uint16_t)get_be(in + 2, 2);
    decoded.session_id = (uint32_t)get_be(in + 4, 4);
    decoded.frame_id = (uint32_t)get_be(in + 8, 4);
    decoded.packet_id = (uint16_t)get_be(in + 12, 2);
    decoded.packet_count = (uint16_t)get_be(in + 14, 2);
    decoded.jpeg_length = (uint32_t)get_be(in + 16, 4);
    decoded.payload_length = (uint16_t)get_be(in + 20, 2);
    decoded.reserved = (uint16_t)get_be(in + 22, 2);
    decoded.timestamp = get_be(in + 24, 8);
    decoded.packet_sequence = get_be(in + 32, 8);
    if (eye_video_validate(&decoded) != EYE_OK) return EYE_INVALID;
    *h = decoded;
    return EYE_OK;
}

int eye_datagram_validate(const struct eye_video_header *h, size_t length,
                          int allow_plaintext)
{
    size_t expected;
    if (eye_video_validate(h) != EYE_OK) return EYE_INVALID;
    if (!h->flags && !allow_plaintext) return EYE_INVALID;
    expected = EYE_HEADER_SIZE + h->payload_length + (h->flags ? EYE_TAG_SIZE : 0);
    return length == expected ? EYE_OK : EYE_LENGTH;
}

int eye_nonce_encode(uint8_t *out, size_t capacity, uint32_t epoch, uint64_t sequence)
{
    if (!out || capacity < 12) return EYE_LENGTH;
    put_be(out, epoch, 4); put_be(out + 4, sequence, 8);
    return EYE_OK;
}

static int control_length(uint8_t type, uint32_t length)
{
    static const uint16_t lengths[] = {0, 36, 36, 768, 32, 32, 40, 40, 40, 0, 864, 832};
    if (length > EYE_MAX_CONTROL || type < EYE_HELLO || type > EYE_EPHEMERAL_REPLY)
        return EYE_INVALID;
    if (type == EYE_ERROR) return length >= 2 && length <= 258 ? EYE_OK : EYE_INVALID;
    return length == lengths[type] ? EYE_OK : EYE_INVALID;
}

/* Reject malformed/overlong UTF-8, surrogate values and values above U+10FFFF. */
static int valid_utf8(const uint8_t *p, size_t length)
{
    size_t i = 0;
    while (i < length) {
        uint32_t cp, minimum;
        unsigned count;
        uint8_t first = p[i++];
        if (first < 0x80) continue;
        if (first >= 0xc2 && first <= 0xdf) { cp = first & 31; count = 1; minimum = 0x80; }
        else if (first >= 0xe0 && first <= 0xef) { cp = first & 15; count = 2; minimum = 0x800; }
        else if (first >= 0xf0 && first <= 0xf4) { cp = first & 7; count = 3; minimum = 0x10000; }
        else return 0;
        if (length - i < count) return 0;
        while (count--) {
            uint8_t next = p[i++];
            if ((next & 0xc0) != 0x80) return 0;
            cp = (cp << 6) | (next & 63);
        }
        if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return 0;
    }
    return 1;
}

static int control_body(uint8_t type, const uint8_t *body, uint32_t length)
{
    if (type == EYE_HELLO || type == EYE_HELLO_ACK) {
        if (body[0] > EYE_VERSION || body[1] < EYE_VERSION ||
            (get_be(body + 2, 2) != EYE_SUITE &&
             get_be(body + 2, 2) != EYE_SUITE_EPHEMERAL)) return EYE_INVALID;
        if (type == EYE_HELLO_ACK && (body[0] != EYE_VERSION || body[1] != EYE_VERSION))
            return EYE_INVALID;
    }
    if (type == EYE_ERROR && (get_be(body, 2) < 1 || get_be(body, 2) > 7 ||
        !valid_utf8(body + 2, length - 2))) return EYE_INVALID;
    return EYE_OK;
}

int eye_control_encode(uint8_t *out, size_t capacity, uint8_t type,
                        const uint8_t *body, size_t length)
{
    if (length > EYE_MAX_CONTROL || control_length(type, (uint32_t)length) != EYE_OK)
        return EYE_INVALID;
    if (!out || !body || capacity < EYE_CONTROL_HEADER_SIZE + length) return EYE_LENGTH;
    if (control_body(type, body, (uint32_t)length) != EYE_OK) return EYE_INVALID;
    memcpy(out, "EYPQ", 4); out[4] = EYE_VERSION; out[5] = type;
    put_be(out + 6, 0, 2); put_be(out + 8, length, 4);
    memcpy(out + EYE_CONTROL_HEADER_SIZE, body, length);
    return EYE_OK;
}

int eye_control_prefix(uint8_t *type, uint32_t *body_length,
                       const uint8_t *in, size_t length)
{
    uint32_t size;
    if (!type || !body_length || !in || length != EYE_CONTROL_HEADER_SIZE) return EYE_LENGTH;
    if (memcmp(in, "EYPQ", 4) || in[4] != EYE_VERSION || get_be(in + 6, 2)) return EYE_INVALID;
    size = (uint32_t)get_be(in + 8, 4);
    if (control_length(in[5], size) != EYE_OK) return EYE_INVALID;
    *type = in[5]; *body_length = size;
    return EYE_OK;
}

int eye_control_decode(uint8_t *type, const uint8_t **body, uint32_t *body_length,
                       const uint8_t *in, size_t length)
{
    uint8_t decoded_type;
    uint32_t size;
    int status;
    if (!type || !body || !body_length || !in || length < EYE_CONTROL_HEADER_SIZE)
        return EYE_LENGTH;
    status = eye_control_prefix(&decoded_type, &size, in, EYE_CONTROL_HEADER_SIZE);
    if (status != EYE_OK) return status;
    if (length != EYE_CONTROL_HEADER_SIZE + size) return EYE_LENGTH;
    if (control_body(decoded_type, in + EYE_CONTROL_HEADER_SIZE, size) != EYE_OK)
        return EYE_INVALID;
    *type = decoded_type; *body_length = size; *body = in + EYE_CONTROL_HEADER_SIZE;
    return EYE_OK;
}
