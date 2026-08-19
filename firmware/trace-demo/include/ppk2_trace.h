/*
 * PPK2 trace markers — C API.
 *
 * Two GPIO markers wired to the PPK2's D0/D1 logic inputs, declared
 * in the board overlay as `zephyr,user` properties:
 *
 *     / {
 *         zephyr,user {
 *             ppk2-d0-gpios = <&gpio1 12 GPIO_ACTIVE_HIGH>;
 *             ppk2-d1-gpios = <&gpio1 13 GPIO_ACTIVE_HIGH>;
 *         };
 *     };
 *
 * The PPK2 samples the logic pins with every current sample
 * (100 kSPS), so a marker held high during a code region lets the
 * host attribute energy to that region with 10 µs granularity.
 *
 * Header-only; include from C or C++. For C++ scope guards on top of
 * these markers, see ppk2_trace.hpp.
 */
#ifndef PPK2_TRACE_H
#define PPK2_TRACE_H

#include <stdbool.h>

#include <zephyr/drivers/gpio.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PPK2_TRACE_NODE DT_PATH(zephyr_user)
BUILD_ASSERT(DT_NODE_HAS_PROP(PPK2_TRACE_NODE, ppk2_d0_gpios),
	     "board overlay must define zephyr,user ppk2-d0-gpios");
BUILD_ASSERT(DT_NODE_HAS_PROP(PPK2_TRACE_NODE, ppk2_d1_gpios),
	     "board overlay must define zephyr,user ppk2-d1-gpios");

static const struct gpio_dt_spec ppk2_trace_pins[2] = {
	GPIO_DT_SPEC_GET(PPK2_TRACE_NODE, ppk2_d0_gpios),
	GPIO_DT_SPEC_GET(PPK2_TRACE_NODE, ppk2_d1_gpios),
};

/* Configure both marker pins as outputs, driven low. 0 on success. */
static inline int ppk2_trace_init(void)
{
	for (int i = 0; i < 2; i++) {
		if (!gpio_is_ready_dt(&ppk2_trace_pins[i])) {
			return -1;
		}
		int err = gpio_pin_configure_dt(&ppk2_trace_pins[i], GPIO_OUTPUT_INACTIVE);
		if (err) {
			return err;
		}
	}
	return 0;
}

/* Drive marker `ch` (0 = PPK2 D0, 1 = PPK2 D1) high or low. */
static inline void ppk2_trace_set(int ch, bool on)
{
	(void)gpio_pin_set_dt(&ppk2_trace_pins[ch & 1], on ? 1 : 0);
}

#ifdef __cplusplus
}
#endif

#endif /* PPK2_TRACE_H */
