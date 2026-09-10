// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <algorithm>
#include <cmath>

// Camera interpolation runs once per rendered frame, not once per Python call.
// Translation still uses Luanti's normal analog controls and collision physics.
struct CourseSteering {
    bool active = false;
    float heading = 0, move_heading = 0, pitch = 0, speed = 0;
    bool swim = false;
    float swim_y = 0;
    void clear() { active = false; speed = 0; swim = false; }
    // Feedback at physics substep frequency, not render/Python frequency. Only normal
    // jump/sneak inputs are selected; velocity and physics stay unmodified.
    void swimKeys(float y, float vy, bool wet, bool &jump, bool &sneak, bool can_jump = false) const {
        jump = sneak = false;
        if (!active || !swim || !wet) return;
        const float desired = std::clamp((swim_y-y)*4.0f + 0.20f, -1.5f, 1.5f);
        jump = vy < desired - 0.07f;
        // Landing can occur between render frames. Never turn a swim pulse
        // into a fresh land jump at a bank within ordinary step height.
        if (can_jump && swim_y-y < 0.6f) jump = false;
        sneak = !jump && y > swim_y + 0.15f && vy > desired + 0.1f;
    }
    static float angle(float value) { return std::remainder(value, 360.0f); }
    static float advance(float current, float target, float dt, bool circular) {
        float delta = circular ? angle(target-current) : target-current;
        dt = std::clamp(dt, 0.0f, 0.1f);
        float step = delta * -std::expm1(-14.0f * dt);
        return current + std::clamp(step, -360.0f * dt, 360.0f * dt);
    }
    void step(float &yaw, float &camera_pitch, float dt) const {
        if (!active) return;
        yaw = advance(yaw, heading, dt, true);
        camera_pitch = advance(camera_pitch, pitch, dt, false);
    }
};
