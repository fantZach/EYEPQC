#ifndef EYEPQC_PROTOCOL_H
#define EYEPQC_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#define EYE_VERSION 1u
#define EYE_SUITE 1u
#define EYE_ENCRYPTED 1u
#define EYE_HEADER_SIZE 40u
#define EYE_TAG_SIZE 16u
#define EYE_MAX_PAYLOAD 1400u
#define EYE_MAX_JPEG (2u * 1024u * 1024u)
#define EYE_CONTROL_HEADER_SIZE 12u
#define EYE_MAX_CONTROL 1024u

enum eye_message_type {
    EYE_HELLO = 1, EYE_HELLO_ACK, EYE_KEM_CIPHERTEXT,
    EYE_FINISHED_BOARD, EYE_FINISHED_HOST, EYE_START, EYE_STOP,
    EYE_REKEY, EYE_ERROR
};

enum eye_status { EYE_OK = 0, EYE_INVALID = -1, EYE_LENGTH = -2 };

/* In-memory representation only; serialize each field, never send this struct. */
struct eye_video_header {
    uint8_t version, flags;
    uint16_t header_length;
    uint32_t session_id, frame_id;
    uint16_t packet_id, packet_count;
    uint32_t jpeg_length;
    uint16_t payload_length, reserved;
    uint64_t timestamp, packet_sequence;
};

int eye_video_validate(const struct eye_video_header *h);
int eye_video_encode(uint8_t *out, size_t capacity, const struct eye_video_header *h);
int eye_video_decode(struct eye_video_header *h, const uint8_t *in, size_t length);
int eye_datagram_validate(const struct eye_video_header *h, size_t length,
                          int allow_plaintext);
int eye_nonce_encode(uint8_t *out, size_t capacity, uint32_t epoch, uint64_t sequence);
int eye_control_encode(uint8_t *out, size_t capacity, uint8_t type,
                        const uint8_t *body, size_t length);
/* Parse the prefix before allocating/receiving its bounded body. */
int eye_control_prefix(uint8_t *type, uint32_t *body_length,
                       const uint8_t *in, size_t length);
int eye_control_decode(uint8_t *type, const uint8_t **body, uint32_t *body_length,
                       const uint8_t *in, size_t length);

#endif
