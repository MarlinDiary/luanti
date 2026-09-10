# 跨平台构建与学生交付

## 学生侧目标

学生只需要两个产物：课程客户端和 Python wheel。客户端负责显示同一个角色并暴露本地受限接口；脚本可以是普通循环，也可以接任意 Agent。学生不需要 C++、Node.js、Docker 或服务端安装权限。

## macOS

本轮从固定 Luanti 提交构建 `RUN_IN_PLACE=FALSE` 应用，补齐私有动态库、删除 Homebrew/用户目录加载路径、ad-hoc 签名，再以后台静音配置启动。验证检查：

- 应用可从自身 bundle 找到字体与资源；
- `codesign --verify --deep --strict` 通过；
- 非系统动态库全部位于 `Contents/Frameworks`；
- Agent 控制时没有 SDL 相对鼠标模式或 warp；
- 本地夹具观察到 `focused=false`、`audio_enabled=false`；真实服后台验收另用
  50 ms 操作系统前台采样，确认 Luanti 从未成为 frontmost app。测试注入的
  LSUIElement 包和焦点守护不进入学生发行包。

ad-hoc 签名适合课程内部测试；公开分发仍需 Developer ID 签名、公证和最低 macOS 版本实机矩阵。

## Windows

`.github/workflows/course-release.yml` 在 Windows runner 上按固定上游提交执行 MSYS2 CLANG64 构建，收集所需 DLL，并调用 `tools/package_windows.py` 生成 ZIP 和 SHA-256 清单。打包脚本会拒绝缺少 `bin/luanti.exe` 的输入，不会改动构建树。

本仓库当前已自动测试 ZIP 结构、哈希清单和 workflow 关键步骤；还没有在本机伪装 Windows 实机通过。Windows 结论以 CI runner 的实际构建和后续一台真实 Windows 机器的启动/控制/焦点测试为准。

## 发行步骤

```sh
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m pip wheel --no-deps . -w dist
```

macOS runner 另外执行安装、`tools/package_macos.py` 和 ZIP；Windows runner 执行 `tools/package_windows.py`。两端均上传客户端；`sdk` job 单独上传同一版本 wheel。
