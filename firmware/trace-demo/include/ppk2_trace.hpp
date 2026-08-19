/*
 * PPK2 trace markers — C++ RAII layer on top of ppk2_trace.h.
 *
 * A TraceScope raises a marker on construction and lowers it on
 * destruction, so the marked region survives early returns and
 * exceptions-disabled error paths alike:
 *
 *     {
 *         ppk2::TraceScope mark{ppk2::D0};
 *         run_inference();
 *     }   // D0 drops here, whatever run_inference did
 *
 * trace_scope() is the lambda-shaped convenience for one-liners:
 *
 *     ppk2::trace_scope(ppk2::D1, [&] { whole_sweep(); });
 */
#ifndef PPK2_TRACE_HPP
#define PPK2_TRACE_HPP

#include "ppk2_trace.h"

namespace ppk2 {

inline constexpr int D0 = 0;
inline constexpr int D1 = 1;

class TraceScope {
public:
	explicit TraceScope(int ch) : m_ch(ch) { ppk2_trace_set(m_ch, true); }
	~TraceScope() { ppk2_trace_set(m_ch, false); }

	TraceScope(const TraceScope &) = delete;
	TraceScope &operator=(const TraceScope &) = delete;

private:
	int m_ch;
};

/* Run `body` with marker `ch` held high; lowered on scope exit. */
template <typename Body>
inline void trace_scope(int ch, Body &&body)
{
	TraceScope guard{ch};
	body();
}

} /* namespace ppk2 */

#endif /* PPK2_TRACE_HPP */
