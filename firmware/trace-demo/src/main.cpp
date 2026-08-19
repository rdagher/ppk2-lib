/*
 * PPK2 trace-marker demo — a blinky whose energy you can attribute.
 *
 * Signal shape, repeating forever:
 *
 *   boot:  3 quick D0 pulses (C API)         — sync burst, marks reset
 *   sweep: D1 high for the whole sweep (RAII)
 *            10 × [ D0 high: 600 ms busy-blink workload (RAII)
 *                   D0 low:  150 ms idle gap (k_sleep)        ]
 *   rest:  2 s idle, then the sweep repeats
 *
 * D0 marks each workload, D1 each sweep. Capture with `ppk2 capture`
 * (or the Nordic GUI) and feed the CSV to attribute.py to get
 * per-workload and per-sweep energy.
 *
 * The workload is a busy-wait LED blink: the CPU stays awake, so the
 * current plateau during D0-high is visibly above the k_sleep gaps.
 */
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

#include "ppk2_trace.h"
#include "ppk2_trace.hpp"

#define N_RUNS       10
#define WORKLOAD_MS  600
#define BLINK_MS     100 /* LED toggle interval inside a workload */
#define GAP_MS       150 /* idle gap between workloads */
#define REST_MS      2000 /* idle rest between sweeps */

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);

static void busy_blink_workload(void)
{
	for (int s = 0; s < WORKLOAD_MS / BLINK_MS; s++) {
		gpio_pin_toggle_dt(&led);
		k_busy_wait(BLINK_MS * 1000);
	}
}

/* C-API usage: a recognisable 3-pulse burst right after reset, handy
 * for locating t=0 in a capture that didn't start at power-on. */
static void sync_burst(void)
{
	for (int i = 0; i < 3; i++) {
		ppk2_trace_set(0, true);
		k_busy_wait(1000);
		ppk2_trace_set(0, false);
		k_busy_wait(1000);
	}
}

int main(void)
{
	if (ppk2_trace_init() != 0 || !gpio_is_ready_dt(&led) ||
	    gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE) != 0) {
		return -1;
	}

	sync_burst();

	for (;;) {
		/* C++ RAII usage: D1 brackets the sweep, D0 each workload. */
		ppk2::trace_scope(ppk2::D1, [] {
			for (int i = 0; i < N_RUNS; i++) {
				ppk2::trace_scope(ppk2::D0, [] { busy_blink_workload(); });
				k_sleep(K_MSEC(GAP_MS));
			}
		});
		k_sleep(K_MSEC(REST_MS));
	}
	return 0;
}
