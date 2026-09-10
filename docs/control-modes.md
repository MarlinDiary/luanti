# 控制模式与鼠标

课程客户端把**看画面**和**控制角色**分开。观看不需要捕获鼠标。

| 模式 | 角色由谁控制 | 系统鼠标 | 切换方式 |
| --- | --- | --- | --- |
| WATCHING / observe（默认） | 暂无输入控制者 | 自由 | Python `game.take_control()` 或游戏窗口内按 F8 |
| AGENT / agent | 当前 Python 连接 | 自由；屏蔽人工移动、视角、点击与背包操作 | Esc 停止；游戏界面无菜单时 F8 先停止 Agent，再转人工 |
| MANUAL / manual | 人工键鼠 | 正常游戏捕获 | Esc 或 F8 回到观看；切到其他窗口也回到观看 |

Mac 的功能键设置不同，F8 可能需要按 **Fn + F8**。

- 登录、选服务器和进入世界仍在原生界面进行。
- Python 的 `Game.connect()` 默认只连接、观察，不接管角色。
- 人工模式下 Python 申请接管会返回 `manual_control_active`，而非抢走控制权。
- `game.stop()` 停止当前动作但保留 Agent 所有权；`game.release_control()` 回到观看。
- Python 正常结束、连接断开后释放 Agent 输入，回到观看；不会自动切成人工或抓鼠标。
- Esc 是本机紧急停止，不需要等待 Python 返回。在 Agent 打开的背包界面中也能生效。
- F8 只在游戏窗口有焦点、没有打开菜单时进入人工。先关闭菜单，再按 F8。
- 观看模式下再次按 Esc 可打开原生暂停菜单。关闭菜单不会自动开启人工控制。
- 这些是客户端输入模式，并不暂停多人服务器的物理模拟：重力、惯性、怪物和其他玩家仍可能影响角色。

## 学生脚本

```python
from luanti_course import Game

with Game.connect() as game:
    print(game.observe().control)  # observe / agent / manual
    with game.control():
        game.look(yaw=0, pitch=0)
        game.move(seconds=0.5)
    # 回到观看，游戏窗口继续保留。
```

## 回归检查

- `tests/native/camera_regression.py` 编译实际的 `Game::updateCameraDirection` 方法，使用假的窗口／鼠标记录捕获与归中调用；不会碰桌面鼠标。
- 原生 `TestCourseInput` 通过实际输入接收器验证 Agent 屏蔽物理输入、Esc / F8 生效及按键重复去抖。
- macOS 实机验收可注入 `tests/native/cursor_audit_macos.c`：记录并阻挡捕获／归中请求和音频设备打开，避免测试回归干扰使用者；合格要求请求数均为零。该测试库不随客户端打包。
- 当前修复在 macOS Apple Silicon 验证；Windows 尚待实机验收。

Agent 后台运行时使用前台帧率上限，避免切到编辑器后画面降到默认的 10 FPS；释放控制后恢复原来的后台帧率策略。
