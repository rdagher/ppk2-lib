/*
 * nRF54LM20 PPK2 bench-DUT.
 *
 * Toggles two GPIOs at fixed rates so the PPK2's digital inputs see
 * a deterministic reference signal during HIL captures:
 *
 *   D0: 5 Hz   (toggle every 100 ms -> 200 ms period, 50 % duty)
 *   D1: 0.5 Hz (toggle every 1000 ms -> 2 s period,   50 % duty)
 *
 * Two Zephyr kernel timers fire from the system tick: toggles run in
 * ISR context so there's no scheduler jitter on the edge timing.
 *
 * The main thread is the workload: it busy-waits while D0 is high and
 * sleeps while it is low, so the current trace has two plateaus that
 * follow the marker.
 */

#include <errno.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

#define D0_NODE DT_ALIAS(ppk2_d0)
#define D1_NODE DT_ALIAS(ppk2_d1)

#if !DT_NODE_EXISTS(D0_NODE) || !DT_NODE_EXISTS(D1_NODE)
#error "Both ppk2-d0 and ppk2-d1 aliases must be defined in the board overlay."
#endif

static const struct gpio_dt_spec d0 = GPIO_DT_SPEC_GET(D0_NODE, gpios);
static const struct gpio_dt_spec d1 = GPIO_DT_SPEC_GET(D1_NODE, gpios);

/* Half-periods (timers fire on every toggle). */
#define D0_HALF_PERIOD K_MSEC(100)
#define D1_HALF_PERIOD K_MSEC(1000)

static volatile bool d0_high;
static K_SEM_DEFINE(d0_rose, 0, 1);

static void d0_toggle(struct k_timer *timer)
{
	ARG_UNUSED(timer);
	d0_high = !d0_high;
	(void)gpio_pin_set_dt(&d0, d0_high);
	if (d0_high) {
		k_sem_give(&d0_rose);
	}
}

static void d1_toggle(struct k_timer *timer)
{
	ARG_UNUSED(timer);
	(void)gpio_pin_toggle_dt(&d1);
}

K_TIMER_DEFINE(d0_timer, d0_toggle, NULL);
K_TIMER_DEFINE(d1_timer, d1_toggle, NULL);

int main(void)
{
	if (!gpio_is_ready_dt(&d0) || !gpio_is_ready_dt(&d1)) {
		return -ENODEV;
	}

	int err = gpio_pin_configure_dt(&d0, GPIO_OUTPUT_INACTIVE);
	if (err) {
		return err;
	}
	err = gpio_pin_configure_dt(&d1, GPIO_OUTPUT_INACTIVE);
	if (err) {
		return err;
	}

	/* Start both timers with zero initial delay so the first toggle
	 * lands one half-period from boot. Period == half-period because
	 * the timer callback toggles the pin every fire. */
	k_timer_start(&d0_timer, D0_HALF_PERIOD, D0_HALF_PERIOD);
	k_timer_start(&d1_timer, D1_HALF_PERIOD, D1_HALF_PERIOD);

	for (;;) {
		k_sem_take(&d0_rose, K_FOREVER);
		while (d0_high) {
			k_busy_wait(100);
		}
	}
	return 0;
}
