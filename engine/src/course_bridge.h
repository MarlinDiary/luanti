// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <json/json.h>
#include <atomic>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <memory>

// Loopback-only transport. It never touches Game, Client, or Lua off-thread.
class CourseBridge {
public:
    struct Request { uint64_t session; Json::Value value; };
    explicit CourseBridge(const std::string &profile);
    ~CourseBridge();
    CourseBridge(const CourseBridge &) = delete;
    CourseBridge &operator=(const CourseBridge &) = delete;
    uint64_t session() const { return m_session.load(); }
    std::deque<Request> take();
    void reply(uint64_t session, const Json::Value &value);
    static void manualTakeover() { ++s_manual_epoch; }
    static void toggleManual() { ++s_toggle_epoch; }
    static uint64_t toggleEpoch() { return s_toggle_epoch.load(); }
    static void blockHumanInput(bool block) { s_block_human.store(block); }
    static bool humanInputBlocked() { return s_block_human.load(); }
    static uint64_t manualEpoch() { return s_manual_epoch.load(); }
private:
    struct State;
    std::unique_ptr<State> m_state;
    std::thread m_thread;
    std::atomic<bool> m_stop{false}, m_overflow{false};
    std::atomic<uint64_t> m_session{0};
    static std::atomic<uint64_t> s_manual_epoch, s_toggle_epoch;
    static std::atomic<bool> s_block_human;
    std::mutex m_mutex;
    std::deque<Request> m_requests;
    std::deque<std::pair<uint64_t, std::string>> m_replies;
    void run();
};
