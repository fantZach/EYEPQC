#ifndef EYEPQC_SESSION_H
#define EYEPQC_SESSION_H

#include <stddef.h>
#include <stdint.h>

enum eye_session_state {
    EYE_STATE_IDLE, EYE_STATE_HANDSHAKE, EYE_STATE_CONFIRM,
    EYE_STATE_STREAMING, EYE_STATE_REKEY, EYE_STATE_ERROR
};
enum eye_session_result {
    EYE_SESSION_OK = 0, EYE_SESSION_INPUT = -1, EYE_SESSION_STATE = -2,
    EYE_SESSION_AUTH = -3, EYE_SESSION_ROTATE = -4
};

struct eye_session {
    uint8_t pinned_pk_hash[32], last_transcript[32], transcript_hash[32];
    uint8_t video_key[16], control_key[32];
    uint32_t nonce_prefix, session_id;
    uint64_t packet_sequence, command_sequence, receive_high, receive_mask;
    uint8_t receive_started, board_finished_sent, host_finished_verified, state;
};

_Static_assert(sizeof(struct eye_session) == 192U &&
               offsetof(struct eye_session, transcript_hash) == 64U &&
               offsetof(struct eye_session, video_key) == 96U &&
               offsetof(struct eye_session, control_key) == 112U &&
               offsetof(struct eye_session, nonce_prefix) == 144U &&
               offsetof(struct eye_session, receive_started) == 184U &&
               offsetof(struct eye_session, state) == 187U,
               "G6 session DDR readback layout changed");

int eye_sha256(uint8_t out[32], const uint8_t *data, size_t length);
int eye_hmac_sha256(uint8_t out[32], const uint8_t *key, size_t key_length,
                    const uint8_t *data, size_t length);
int eye_hkdf56(uint8_t out[56], const uint8_t shared[32], const uint8_t salt[32]);
int eye_session_init(struct eye_session *s, const uint8_t pk[800]);
int eye_session_begin(struct eye_session *s, const uint8_t shared[32],
                      const uint8_t hello[48], const uint8_t ack[48],
                      const uint8_t kem[780]);
/* The Finished record output is cleared on error when a destination is supplied. */
int eye_session_board_finished(struct eye_session *s, uint8_t out[44]);
int eye_session_verify_host_finished(struct eye_session *s, const uint8_t message[44]);
int eye_session_command(struct eye_session *s, const uint8_t message[52]);
/* Rejected or exhausted nonce requests clear the output when supplied. */
int eye_session_next_nonce(struct eye_session *s, uint8_t out[12]);
/* Call only AFTER AES-GCM authentication succeeds. */
int eye_session_accept_authenticated_packet(struct eye_session *s,
                                            uint32_t session_id, uint64_t sequence);
void eye_session_rekey(struct eye_session *s);
void eye_session_error(struct eye_session *s);
void eye_session_reset(struct eye_session *s);

#endif
