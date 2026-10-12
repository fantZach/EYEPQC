/* Isolated ML-KEM-512 x4 sponge integration. */
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_FIPS202_CUSTOM_HEADER "mlkem_fips202_custom.h"
#define MLK_CONFIG_FIPS202X4_CUSTOM_HEADER "mlkem_sponge_fips202x4_custom.h"
