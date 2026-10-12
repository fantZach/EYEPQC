#ifndef EYEPQC_G6_REKEY_DIAG_H
#define EYEPQC_G6_REKEY_DIAG_H

#include <stddef.h>
#include <stdint.h>

#define G6_REKEY_DIAG_MAGIC 0x47365244U /* G6RD */
#define G6_REKEY_DIAG_VERSION 2U

/* Candidate-only, non-sensitive snapshot for receiver-exit / REKEY diagnosis.
 * The ABI contains counters and controller status only. It never stores any
 * control payload, session identifier, handshake bytes, or key material. */
struct g6_rekey_diag {
    volatile uint32_t magic;                    /* 0 */
    volatile uint32_t version;                  /* 4 */
    volatile uint32_t size_bytes;               /* 8 */
    volatile uint32_t sequence;                 /* 12: odd while publishing */
    volatile uint32_t phase;                    /* 16: WAIT_HELLO..FAULT = 0..5 */
    volatile uint32_t last_control_type;        /* 20: decoded protocol type */
    volatile uint32_t received_control_count;   /* 24 */
    volatile uint32_t hello_attempt_count;      /* 28 */
    volatile uint32_t hello_ack_send_attempts;  /* 32 */
    volatile uint32_t hello_ack_send_status;    /* 36: UINT32_MAX = not attempted */
    volatile uint32_t cleanup_count;            /* 40 */
    volatile uint32_t cleanup_last_result;      /* 44: UINT32_MAX = in progress */
    volatile uint32_t usb_configured;           /* 48: boolean */
    volatile uint32_t usb_dtr;                  /* 52: boolean */
    volatile uint32_t connection_epoch;         /* 56 */
    volatile uint32_t tx_ready;                 /* 60: boolean */
    volatile uint32_t rx_bytes_buffered;        /* 64: ring occupancy, not payload */
    volatile uint32_t rx_head;                  /* 68 */
    volatile uint32_t rx_tail;                  /* 72 */
    volatile uint32_t rx_bad;                   /* 76: boolean */
    volatile uint32_t ep1_prime;                /* 80: EP1 IN bit snapshot */
    volatile uint32_t ep1_ready;                /* 84: EPRDY EP1 IN bit snapshot */
    volatile uint32_t epcr1;                    /* 88: controller endpoint control */
    volatile uint32_t ep1_completion;           /* 92: EP1 IN bit snapshot */
    volatile uint32_t ep1_flush;                /* 96: EP1 IN bit snapshot */
    volatile uint32_t control_errors;           /* 100 */
    volatile uint32_t fatal_errors;             /* 104 */
    volatile uint32_t transport_errors;         /* 108 */
    volatile uint32_t tx_completion_count;      /* 112 */
    volatile uint32_t tx_completion_status;     /* 116: 0 ok, 4 transfer error, 5 ownership uncertain */
    volatile uint32_t tx_completion_token;      /* 120: raw EP1 IN dTD token */
    volatile uint32_t tx_completion_residual;   /* 124: remaining bytes */
    volatile uint32_t tx_completion_requested; /* 128: SDK request byte count */
    volatile uint32_t tx_completion_expected;   /* 132: caller byte count */
    volatile uint32_t tx_completion_match_flags;/* 136: bit0 callback ptr, bit1 dTD ptr, bit2 slot, bit3 epoch, bit4 size */
    volatile uint32_t sequence_end;             /* 140: equals even sequence */
};

_Static_assert(sizeof(struct g6_rekey_diag) == 144U,
               "G6 rekey diagnostic ABI size changed");
_Static_assert(offsetof(struct g6_rekey_diag, phase) == 16U &&
               offsetof(struct g6_rekey_diag, hello_ack_send_status) == 36U &&
               offsetof(struct g6_rekey_diag, cleanup_last_result) == 44U &&
               offsetof(struct g6_rekey_diag, ep1_prime) == 80U &&
               offsetof(struct g6_rekey_diag, ep1_ready) == 84U &&
               offsetof(struct g6_rekey_diag, epcr1) == 88U &&
               offsetof(struct g6_rekey_diag, tx_completion_count) == 112U &&
               offsetof(struct g6_rekey_diag, tx_completion_match_flags) == 136U &&
               offsetof(struct g6_rekey_diag, sequence_end) == 140U,
               "G6 rekey diagnostic ABI offsets changed");

void usb_cdc_g6_diag_fill(volatile struct g6_rekey_diag *diag);

#endif
