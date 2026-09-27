# Vendored Secworks AES

Source: https://github.com/secworks/aes
Pinned commit: `80dc4718e1dcbbdb4b0dd1bdb393d8f7b98981dc`.
License: BSD-2-Clause; see LICENSE and the original source headers.

These six `src/rtl` files are copied unchanged. No build/package manager is required.
The local AXI4-Lite wrapper ties `encdec=1` and `keylen=0`; synthesis removes
unused decryption/AES-256 logic. The decrypt sources remain for resolving the
unchanged upstream hierarchy, not for board-side decryption.

This is not a masked/side-channel-hardened implementation. Use only for the
isolated bring-up MVP until the project's production security review is complete.
