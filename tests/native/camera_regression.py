#!/usr/bin/env python3
"""Compile the actual camera method with a fake device: no OS mouse is touched.

Use --source to test the preserved baseline and the modified method identically.
The fake cursor records capture/warp calls, rather than assuming a mode label
proves what the engine does.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, required=True)
a = p.parse_args()
source = a.source.read_text()
start = source.index('void Game::updateCameraDirection(')
brace = source.index('{', start)
depth = 1
end = brace + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
method = source[start:end]
stub = r'''
#include <iostream>
#include "course_control.h"
struct CameraOrientation {};
struct Cursor {
    bool visible = true, relative = false;
    int capture_calls = 0;
    void setRelativeMode(bool v) { relative = v; capture_calls += v; }
    void setVisible(bool v) { visible = v; }
    bool isVisible() { return visible; }
};
struct Device {
    Cursor cursor;
    bool active = true, focused = true;
    Cursor *getCursorControl() { return &cursor; }
    bool isWindowActive() { return active; }
    bool isWindowFocused() { return focused; }
};
struct Input {
    int warps = 0;
    bool isRandom() { return false; }
    void setMousePos(int, int) { ++warps; }
};
struct Driver {
    struct Size { int Width = 1100, Height = 720; };
    Size getScreenSize() { return {}; }
};
void *g_touchcontrols = nullptr;
bool menu = false;
bool isMenuActive() { return menu; }
struct Game {
    Device device_storage; Input input_storage; Driver driver_storage;
    Device *device = &device_storage; Input *input = &input_storage;
    Driver *driver = &driver_storage;
    CourseControl m_course_control;
    bool m_course_owned = false; // Historical baseline field, not used by fixed code.
    bool m_first_loop_after_window_activation = true;
    int camera_updates = 0;
    void updateCameraDirection(CameraOrientation *, float);
    void updateCameraOrientation(CameraOrientation *, float) { ++camera_updates; }
};
'''
main = r'''
int main() {
    int failures = 0;
    auto check = [&](const char *name, bool pass) {
        std::cout << (pass ? "PASS " : "FAIL ") << name << '\n';
        failures += !pass;
    };
    CameraOrientation cam;
    Game g; g.m_course_control.enable();
    auto tick = [&] { g.updateCameraDirection(&cam, 0.016f); };
    tick(); tick();
    check("startup_observe_no_capture", !g.device->cursor.relative && g.device->cursor.visible);
    check("startup_observe_no_warp_or_human_camera", g.input->warps == 0 && g.camera_updates == 0);
    g.m_course_control.acquire(g.m_course_control.epoch()); g.m_course_owned = true;
    tick(); tick();
    check("agent_no_capture", !g.device->cursor.relative && g.device->cursor.visible);
    check("agent_no_warp_or_human_camera", g.input->warps == 0 && g.camera_updates == 0);
    g.device->focused = false; tick(); g.device->focused = true; tick();
    check("refocus_does_not_grab_mouse", g.device->cursor.capture_calls == 0 && g.input->warps == 0);
    auto old = g.m_course_control.epoch();
    g.m_course_control.disconnected(); g.m_course_owned = false; tick();
    check("disconnect_observe", !g.m_course_control.agent() && !g.m_course_control.humanInput());
    check("disconnect_no_capture_or_warp", !g.device->cursor.relative && g.input->warps == 0);
    check("stale_agent_rejected", !g.m_course_control.acquire(old));
    g.m_course_control.toggleManual(); tick();
    check("explicit_manual_captures", g.device->cursor.relative && !g.device->cursor.visible);
    check("agent_cannot_take_manual_owner", !g.m_course_control.acquire(g.m_course_control.epoch()));
    g.m_course_control.disconnected();
    check("observer_disconnect_preserves_manual", g.m_course_control.manual());
    int warps = g.input->warps;
    g.m_course_control.observe(); tick();
    check("escape_releases_without_warp", !g.device->cursor.relative && g.device->cursor.visible && g.input->warps == warps);
    check("escape_blocks_human_input", !g.m_course_control.humanInput());
    // Original, non-course client semantics remain available when explicitly disabled.
    Game original; original.updateCameraDirection(&cam, .016f);
    check("course_disabled_retains_original_input", original.device->cursor.relative);
    return failures ? 1 : 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    cpp = Path(tmp)/'camera.cpp'
    binary = Path(tmp)/'camera-test'
    cpp.write_text(stub + method + main)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-I', str(ROOT/'engine/src'), str(cpp), '-o', str(binary)], check=True)
    raise SystemExit(subprocess.run([str(binary)]).returncode)
