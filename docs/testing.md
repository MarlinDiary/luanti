# 持久可见测试会话

测试脚本连接同一个 Luanti 进程。`/fixture reset` 在测试世界内重置几何、库存、位置和帧率；每次请求有唯一 ID/代次，先确认客户端接收到重置位置，再确认服务端水平位置已同步；等待期间允许垂直方向自然受重力影响。脚本退出只释放动作输入，不退出游戏。正式课程服务器不安装此夹具。

## 一次启动，反复测试

在仓库根目录先编译测试仪器（只在测试进程注入，不打包给学生）：

```sh
mkdir -p build/test-tools
clang -dynamiclib -undefined dynamic_lookup tests/native/cursor_audit_macos.c -o build/test-tools/cursor.dylib
clang -dynamiclib -framework AppKit tests/native/focus_guard_macos.m -o build/test-tools/focus.dylib
python tests/integration/test_session.py start --session build/test-session \
  --client "dist/Luanti Course.app/Contents/MacOS/luanti" \
  --game PATH_TO_VOXELIBRE \
  --audit build/test-tools/cursor.dylib --focus-guard build/test-tools/focus.dylib
python tests/integration/terrain_suite.py --session build/test-session \
  --sdk sdk/src --out build/test-run-1 --cases water_shore,door,bridge --fps 60
# 改 Python 技能/场景后，换一个输出目录再次运行；客户端 PID 不变。
```

首次后台启动设置 SDL 不激活窗口的提示，并注入测试专用的 AppKit 焦点保护。声音设备被测试仪器关闭，鼠标捕获/移动请求被记录和拦截。前台焦点可用 `focus_watch_macos.swift` 独立采样确认；这些仪器不替代生产客户端控制互斥的回归测试。

## 待命与继续

测试套件正常结束把角色放回无危险陆地，释放控制并降低帧率；进程继续运行。手动待命使用：

```sh
python tests/integration/test_session.py park --session build/test-session
python tests/integration/test_session.py status --session build/test-session
# 下次套件连接同一 PID，不打开新窗口。
python tests/integration/terrain_suite.py --session build/test-session \
  --sdk sdk/src --out build/test-run-2 --cases water_shore
```

日常迭代不用 SIGSTOP/SIGCONT：整进程挂起会令恢复后的时间步失真，不适合作为动作测量起点。旧 `pause` / `resume` 命令只保留为 POSIX 诊断工具，历史会话从挂起恢复后先重置场景；不把恢复瞬间的运动当成有效流畅性样本。`park` 仅操作 session.json 标识且进程命令行再次核对过的隔离世界，真实课程服不使用夹具或重置。

只有 C++ 原生二进制改变才需要明确的一次换进程；`start` 不会偷偷杀旧进程或自动重启。进程意外结束时报告错误并保留证据。确实要结束会话时使用 `stop`；停止/重启测试实例不会触碰普通游戏 profile。

输出包含场景输入、SDK 返回、实际位置/速度、生命/气量和同一 PID。正式记录还包含源码哈希、完整命令、原样 stdout/stderr 和退出码。受阻用例和成功通行用例分开统计。

## 错误隔离与流畅性回归（0.10）

Python 在发送前校验场景 ID 和几何边界；Lua 先检查整个几何请求，再改世界。测试命令捕获异常、写入 `reset-error.json` 并返回错误，而不是让游戏进程退出。夹具校验失败保留原场景；不可预期的执行中错误仍可能有部分变化，应检查错误文件和世界，不把它算成通过。

`fluency_suite.py` 保存前后动作指标；`bridge_fluency.py` 检查 30/60 FPS、四方向八格连续搭桥、跨度内视角、材料守恒、预算和取消；`fixture_resilience.py` 检查错误请求后同进程继续工作。`terrain_suite.py` 的上岸自然度是正式通过条件，不再仅写一个辅助标记后仍判绿。

## 连续行为与远程后台测试（0.11.6）

复用已启动的本地 Session，运行 `tests/integration/behavior_repair_audit.py`，指定 `--sdk`、`--session` 和新的 `--output` 目录。包含连续路线、转弯、边缘缓冲、路点之后取消、静止和移动多追兵。夹具操作只用于本地测试世界。

macOS 远程验证要求单独测试应用的 `Contents/Info.plist` 有 `LSUIElement = true`。复制应用到新目录后再修改该字段、独立 bundle identifier 并重新 ad-hoc 签名，学生应用保持原样。本轮已运行的副本及元数据哈希记录在 `build/evidence/behavior-repair-v0.24/background-bundle.json`。

远程验证器核对元数据，显式设置静音和后台环境，持有互斥锁；焦点、声音、人工接管、低血、死亡、超时或观察停滞会终止它自己启动的进程。密码只经 getpass 和匿名继承管道传递。技能成功后仍须检查整套结果和焦点/声音样本，保留失败轨迹，不自动重开窗口、复活或重置课程世界。
