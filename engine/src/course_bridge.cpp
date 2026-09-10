// SPDX-License-Identifier: LGPL-2.1-or-later
#include "course_bridge.h"
#include "porting.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <cstring>
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <process.h>
#include <io.h>
#include <fcntl.h>
#include <sys/stat.h>
using Socket = SOCKET;
static constexpr Socket invalid_socket = INVALID_SOCKET;
static void closeSocket(Socket s) { if (s != invalid_socket) closesocket(s); }
static bool wouldBlock() { return WSAGetLastError() == WSAEWOULDBLOCK; }
static bool nonblocking(Socket s) { u_long on = 1; return ioctlsocket(s, FIONBIO, &on) == 0; }
#else
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <cerrno>
using Socket = int;
static constexpr Socket invalid_socket = -1;
static void closeSocket(Socket s) { if (s >= 0) close(s); }
static bool wouldBlock() { return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR; }
static bool nonblocking(Socket s) { return s < FD_SETSIZE && fcntl(s, F_SETFL, fcntl(s, F_GETFL) | O_NONBLOCK) == 0; }
#endif
static constexpr size_t MAX_LINE = 8192, MAX_QUEUE = 32, MAX_OUTPUT = 512 * 1024;
std::atomic<uint64_t> CourseBridge::s_manual_epoch{0}, CourseBridge::s_toggle_epoch{0};
std::atomic<bool> CourseBridge::s_block_human{false};

static std::string encode(const Json::Value &value)
{
    Json::StreamWriterBuilder w; w["indentation"] = "";
    return Json::writeString(w, value) + "\n";
}
static bool parse(const std::string &line, Json::Value &q)
{
    Json::CharReaderBuilder b;
    b["rejectDupKeys"] = true; b["failIfExtra"] = true;
    b["allowComments"] = false; b["stackLimit"] = 32;
    std::unique_ptr<Json::CharReader> r(b.newCharReader());
    std::string err;
    return r->parse(line.data(), line.data() + line.size(), &q, &err) && q.isObject();
}
static int writeSocket(Socket s, const std::string &buffer)
{
#ifdef MSG_NOSIGNAL
    return send(s, buffer.data(), (int)buffer.size(), MSG_NOSIGNAL);
#else
    return send(s, buffer.data(), (int)buffer.size(), 0);
#endif
}
struct CourseBridge::State {
    Socket listener = invalid_socket;
    std::string token, path;
    ~State() { closeSocket(listener); if (!path.empty()) std::remove(path.c_str()); }
};

CourseBridge::CourseBridge(const std::string &profile) : m_state(new State)
{
    auto &s = *m_state;
    unsigned char random[32];
    if (!porting::secure_rand_fill_buf(random, sizeof(random)))
        throw std::runtime_error("Course control: random source unavailable");
    std::ostringstream token;
    for (auto b : random) token << std::hex << std::setw(2) << std::setfill('0') << (unsigned)b;
    s.token = token.str();
    s.listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s.listener == invalid_socket || !nonblocking(s.listener))
        throw std::runtime_error("Course control: socket creation failed");
    sockaddr_in address{};
    address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = 0;
    if (bind(s.listener, (sockaddr *)&address, sizeof(address)) || listen(s.listener, 4))
        throw std::runtime_error("Course control: loopback binding failed");
#ifdef _WIN32
    int size = sizeof(address); int pid = _getpid();
#else
    socklen_t size = sizeof(address); int pid = getpid();
#endif
    if (getsockname(s.listener, (sockaddr *)&address, &size))
        throw std::runtime_error("Course control: socket address unavailable");
    s.path = profile + "/course-control-" + std::to_string(pid) + ".json";
    Json::Value info;
    info["protocol"] = 1; info["course_version"] = "0.9.0";
    info["host"] = "127.0.0.1"; info["port"] = ntohs(address.sin_port);
    info["pid"] = pid; info["token"] = s.token;
    const std::string temp = s.path + ".tmp";
#ifdef _WIN32
    int fd = _open(temp.c_str(), _O_CREAT | _O_EXCL | _O_WRONLY | _O_BINARY, _S_IREAD | _S_IWRITE);
    FILE *file = fd < 0 ? nullptr : _fdopen(fd, "wb");
#else
    int fd = open(temp.c_str(), O_CREAT | O_EXCL | O_WRONLY, 0600);
    FILE *file = fd < 0 ? nullptr : fdopen(fd, "wb");
#endif
    if (!file) throw std::runtime_error("Course control: private session file creation failed");
    std::string data = encode(info);
    bool written = fwrite(data.data(), 1, data.size(), file) == data.size();
    bool closed = fclose(file) == 0;
    if (!written || !closed || std::rename(temp.c_str(), s.path.c_str())) {
        std::remove(temp.c_str());
        throw std::runtime_error("Course control: session file write failed");
    }
    m_thread = std::thread(&CourseBridge::run, this);
}
CourseBridge::~CourseBridge()
{
    m_stop = true;
    if (m_thread.joinable()) m_thread.join(); // select has a 50 ms bound.
}
std::deque<CourseBridge::Request> CourseBridge::take()
{
    std::lock_guard<std::mutex> lock(m_mutex);
    std::deque<Request> result;
    // Bound work per frame, including observe snapshots.
    for (size_t i = 0; i < 8 && !m_requests.empty(); ++i) {
        result.push_back(std::move(m_requests.front())); m_requests.pop_front();
    }
    return result;
}
void CourseBridge::reply(uint64_t session, const Json::Value &value)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    std::string line = encode(value);
    if (m_replies.size() >= MAX_QUEUE || line.size() > MAX_OUTPUT) { m_overflow = true; return; }
    m_replies.emplace_back(session, std::move(line));
}
void CourseBridge::run()
{
    Socket peer = invalid_socket;
    std::string incoming, outgoing;
    bool authenticated = false;
    uint64_t next_session = 0;
    auto accepted_at = std::chrono::steady_clock::now();
    auto drop = [&]() {
        m_session = 0; closeSocket(peer); peer = invalid_socket;
        incoming.clear(); outgoing.clear(); authenticated = false;
        std::lock_guard<std::mutex> lock(m_mutex);
        m_requests.clear(); m_replies.clear(); m_overflow = false;
    };
    try {
        while (!m_stop) {
            if (m_overflow || (peer != invalid_socket && !authenticated &&
                    std::chrono::steady_clock::now() - accepted_at > std::chrono::seconds(3))) drop();
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                while (!m_replies.empty()) {
                    auto &reply = m_replies.front();
                    if (reply.first == m_session && authenticated) outgoing += reply.second;
                    m_replies.pop_front();
                }
            }
            if (outgoing.size() > MAX_OUTPUT) drop();
            fd_set reads, writes; FD_ZERO(&reads); FD_ZERO(&writes);
            FD_SET(m_state->listener, &reads);
            Socket highest = m_state->listener;
            if (peer != invalid_socket) {
                FD_SET(peer, &reads); highest = std::max(highest, peer);
                if (!outgoing.empty()) FD_SET(peer, &writes);
            }
            // Bound controller latency while connected, without busy spinning.
            timeval timeout{0, authenticated ? 5000 : 50000};
            int ready = select((int)highest + 1, &reads, &writes, nullptr, &timeout);
            if (ready < 0) { if (wouldBlock()) continue; break; }
            if (FD_ISSET(m_state->listener, &reads)) {
                Socket fresh = accept(m_state->listener, nullptr, nullptr);
                if (fresh != invalid_socket) {
                    if (peer != invalid_socket || !nonblocking(fresh)) closeSocket(fresh);
                    else {
                        peer = fresh; accepted_at = std::chrono::steady_clock::now();
                        int no_delay = 1;
                        setsockopt(peer, IPPROTO_TCP, TCP_NODELAY,
                            reinterpret_cast<const char *>(&no_delay), sizeof(no_delay));
#ifdef SO_NOSIGPIPE
                        int enabled = 1; setsockopt(peer, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled));
#endif
                    }
                }
            }
            if (peer != invalid_socket && FD_ISSET(peer, &writes) && !outgoing.empty()) {
                int sent = writeSocket(peer, outgoing);
                if (sent > 0) outgoing.erase(0, sent);
                else if (!wouldBlock()) { drop(); continue; }
            }
            if (peer == invalid_socket || !FD_ISSET(peer, &reads)) continue;
            char buffer[4096]; int count = recv(peer, buffer, sizeof(buffer), 0);
            if (count == 0 || (count < 0 && !wouldBlock())) { drop(); continue; }
            if (count < 0) continue;
            incoming.append(buffer, count);
            size_t end;
            while (peer != invalid_socket && (end = incoming.find('\n')) != std::string::npos) {
                if (end > MAX_LINE) { drop(); break; }
                std::string line = incoming.substr(0, end); incoming.erase(0, end + 1);
                Json::Value q;
                if (!parse(line, q)) { drop(); break; }
                if (!authenticated) {
                    if (!q["token"].isString() || q["token"].asString() != m_state->token ||
                            !q["protocol"].isInt() || q["protocol"].asInt() != 1) { drop(); break; }
                    authenticated = true; m_session = ++next_session;
                    Json::Value hello; hello["status"] = "connected"; hello["protocol"] = 1;
                    hello["session"] = Json::UInt64(next_session); outgoing += encode(hello);
                } else {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    if (m_requests.size() >= MAX_QUEUE) { m_overflow = true; break; }
                    m_requests.push_back({m_session, std::move(q)});
                }
            }
            if (incoming.size() > MAX_LINE) drop();
        }
    } catch (...) { /* A malformed or disconnected controller must not terminate the game. */ }
    drop();
}
