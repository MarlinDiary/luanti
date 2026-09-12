// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <algorithm>
#include <cmath>

// Camera interpolation runs once per rendered frame, not once per Python call.
// Translation still uses Luanti's normal analog controls and collision physics.
struct CourseSteering {
    bool active = false;
    float heading = 0, move_heading = 0, pitch = 0, speed = 0;
    float yaw_velocity = 0, pitch_velocity = 0;
    bool swim = false;
    float swim_y = 0;
    void clear() {
        active = false;
        speed = 0;
        swim = false;
        yaw_velocity = pitch_velocity = 0;
    }
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
    static float advance(float current, float target, float &velocity, float dt, bool circular) {
        float delta = circular ? angle(target-current) : target-current;
        dt = std::clamp(dt, 0.0f, 0.1f);
        if (dt == 0)
            return current;

        // A target change is not a reason to snap immediately to the maximum
        // turn rate.  Accelerate and brake like a deliberate human head turn;
        // retaining velocity across steering renewals also prevents tiny path
        // updates from producing a succession of visible camera starts.
        // Keep a little headroom below the externally observed 255 deg/s
        // contract: render/telemetry clocks are sampled independently and can
        // otherwise turn an exact 240 deg/s native cap into a 256 deg/s sample.
        constexpr float max_speed = 225.0f;
        constexpr float max_acceleration = 900.0f;
        // Only clamp once the remaining sub-frame movement and the current
        // speed can both settle without exceeding the acceleration limit.
        // Clamping an ordinary overshoot directly to zero is itself a jerk.
        if (std::abs(delta) <= max_acceleration * dt * dt &&
                std::abs(velocity) <= max_acceleration * dt &&
                (velocity * delta >= 0 || std::abs(velocity) < 0.001f)) {
            velocity = 0;
            return current + delta;
        }

        float acceleration = 0;
        if (std::abs(delta) < 0.001f) {
            if (std::abs(velocity) > 0.001f)
                acceleration = -std::copysign(max_acceleration, velocity);
        } else if (velocity * delta > 0 &&
                velocity * velocity / (2.0f * max_acceleration) +
                        3.0f * std::abs(velocity) * dt >= std::abs(delta)) {
            acceleration = -std::copysign(max_acceleration, velocity);
        } else if (std::abs(velocity) < max_speed) {
            acceleration = std::copysign(max_acceleration, delta);
        }
        velocity = std::clamp(velocity + acceleration * dt, -max_speed, max_speed);
        return current + velocity * dt;
    }
    void step(float &yaw, float &camera_pitch, float dt) {
        if (!active) return;
        yaw = advance(yaw, heading, yaw_velocity, dt, true);
        camera_pitch = advance(camera_pitch, pitch, pitch_velocity, dt, false);
    }
};
