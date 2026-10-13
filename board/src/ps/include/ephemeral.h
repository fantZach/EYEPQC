#ifndef EYEPQC_EPHEMERAL_H
#define EYEPQC_EPHEMERAL_H
#include "session.h"
#define EYE_EPHEMERAL_OFFER_BYTES 876U
#define EYE_EPHEMERAL_REPLY_BYTES 844U
struct eye_ephemeral {
    uint8_t private_key[1632], offer[EYE_EPHEMERAL_OFFER_BYTES];
    uint8_t active;
};
/* coins64 must be fresh entropy in production; the caller always wipes it. */
int eye_ephemeral_offer(struct eye_ephemeral *e, struct eye_session *s,
                         const uint8_t coins[64]);
int eye_ephemeral_complete(struct eye_ephemeral *e, struct eye_session *s,
                            const uint8_t *reply, size_t length);
void eye_ephemeral_wipe(struct eye_ephemeral *e);
#endif
