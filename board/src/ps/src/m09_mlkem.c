/* Portable, deterministic-only ML-KEM-512, shared by PC and Cortex-A9. */
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_NO_ENCAPS_API
#include "mlkem/mlkem_native.c"
