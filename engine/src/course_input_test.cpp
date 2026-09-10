// SPDX-License-Identifier: LGPL-2.1-or-later
#include "config.h"
#if BUILD_UNITTESTS
#include "unittest/test.h"
#include "course_bridge.h"
#include "course_control.h"
#include "inputhandler.h"
#include <unordered_map>
extern std::unordered_map<std::string, KeyPress> specialKeyCache;

// Dispatch in-memory events through the production receiver. No desktop input,
// window, mouse cursor or real game server is used by these tests.
class TestCourseInput : public TestBase {
public:
    TestCourseInput() { TestManager::registerTestModule(this); }
    const char *getName() { return "TestCourseInput"; }
    void runTests(IGameDef *) {
        TEST(testExclusiveOwnership);
        TEST(testPhysicalInputBlocked);
        TEST(testEmergencyKeys);
    }
    void testExclusiveOwnership() {
        CourseControl c;
        c.enable();
        UASSERT(!c.humanInput());
        auto stale = c.epoch();
        UASSERT(c.acquire(stale));
        UASSERT(c.agent() && !c.humanInput());
        c.toggleManual();
        UASSERT(c.manual() && !c.agent() && c.humanInput());
        UASSERT(!c.acquire(c.epoch()));
        c.disconnected();
        UASSERT(c.manual());
        c.observe();
        UASSERT(!c.humanInput() && !c.agent());
        UASSERT(!c.acquire(stale));
        UASSERT(c.acquire(c.epoch()));
        c.disconnected();
        UASSERT(!c.humanInput() && !c.agent());
    }
    struct BlockGuard {
        std::unordered_map<std::string, KeyPress> saved_keys = specialKeyCache;
        std::string fullscreen = g_settings->get("keymap_fullscreen");
        std::string close_world = g_settings->get("keymap_close_world");
        BlockGuard() {
            // Supply synthetic physical scancodes rather than asking a desktop
            // rendering device to translate key labels in this headless test.
            specialKeyCache["KEY_ESCAPE"] = KeyPress("SYSTEM_SCANCODE_1001");
            specialKeyCache["KEY_F8"] = KeyPress("SYSTEM_SCANCODE_1002");
            g_settings->set("keymap_fullscreen", "SYSTEM_SCANCODE_2001");
            g_settings->set("keymap_close_world", "SYSTEM_SCANCODE_2002");
            clearKeyCache();
            CourseBridge::blockHumanInput(true);
        }
        ~BlockGuard() {
            CourseBridge::blockHumanInput(false);
            specialKeyCache = saved_keys;
            g_settings->set("keymap_fullscreen", fullscreen);
            g_settings->set("keymap_close_world", close_world);
            clearKeyCache();
        }
    };
    void testPhysicalInputBlocked() {
        BlockGuard block;
        MyEventReceiver receiver{};
        receiver.clearInput();
        for (auto type : {EET_MOUSE_INPUT_EVENT, EET_TOUCH_INPUT_EVENT,
                EET_STRING_INPUT_EVENT, EET_GAMEPAD_BUTTON_EVENT,
                EET_GAMEPAD_AXIS_EVENT, EET_USER_EVENT}) {
            SEvent e{}; e.EventType = type;
            UASSERT(receiver.OnEvent(e));
            UASSERT(!receiver.IsKeyDown(KeyType::FORWARD));
            UASSERT(!receiver.IsKeyDown(KeyType::DIG));
        }
        SEvent e{};
        e.EventType = EET_KEY_INPUT_EVENT;
        e.KeyInput.Key = KEY_KEY_W;
        e.KeyInput.Char = L'w';
        e.KeyInput.SystemKeyCode = 1003;
        e.KeyInput.PressedDown = true;
        UASSERT(receiver.OnEvent(e));
        UASSERT(!receiver.IsKeyDown(KeyType::FORWARD));
    }
    void testEmergencyKeys() {
        BlockGuard block;
        MyEventReceiver receiver{};
        receiver.clearInput();
        SEvent e{};
        e.EventType = EET_KEY_INPUT_EVENT;
        e.KeyInput.Key = KEY_ESCAPE;
        e.KeyInput.SystemKeyCode = 1001;
        e.KeyInput.PressedDown = true;
        auto before = CourseBridge::manualEpoch();
        UASSERT(receiver.OnEvent(e));
        UASSERT(CourseBridge::manualEpoch() == before + 1);
        UASSERT(receiver.OnEvent(e));
        UASSERT(CourseBridge::manualEpoch() == before + 1); // Ignore OS repeat.
        e.KeyInput.PressedDown = false;
        receiver.OnEvent(e);
        e.KeyInput.Key = KEY_F8;
        e.KeyInput.SystemKeyCode = 1002;
        e.KeyInput.PressedDown = true;
        before = CourseBridge::toggleEpoch();
        UASSERT(receiver.OnEvent(e));
        UASSERT(CourseBridge::toggleEpoch() == before + 1);
        UASSERT(receiver.OnEvent(e));
        UASSERT(CourseBridge::toggleEpoch() == before + 1);
    }
};
static TestCourseInput course_input_tests;
#endif
