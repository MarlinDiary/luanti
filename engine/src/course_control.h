// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <cstdint>

// One owner, never a combination of human and agent input. Independent of the
// transport: a failed Python bridge must not unexpectedly capture the mouse.
class CourseControl {
public:
    enum class Mode { Observe, Agent, Manual };
    void enable() { m_enabled = true; observe(); }
    bool enabled() const { return m_enabled; }
    bool agent() const { return m_enabled && m_mode == Mode::Agent; }
    bool manual() const { return m_enabled && m_mode == Mode::Manual; }
    bool humanInput() const { return !m_enabled || manual(); }
    uint64_t epoch() const { return m_epoch; }
    const char *name() const { return agent() ? "agent" : manual() ? "manual" : "observe"; }
    void observe() { m_mode = Mode::Observe; ++m_epoch; }
    void toggleManual() { m_mode = manual() ? Mode::Observe : Mode::Manual; ++m_epoch; }
    bool acquire(uint64_t expected) {
        if (!m_enabled || manual() || expected != m_epoch) return false;
        m_mode = Mode::Agent;
        ++m_epoch;
        return true;
    }
    void disconnected() { if (agent()) observe(); }
private:
    bool m_enabled = false;
    Mode m_mode = Mode::Observe;
    uint64_t m_epoch = 0;
};
