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

提交 `2f59f6f` 的 [GitHub Actions run 34422830379](https://github.com/MarlinDiary/luanti/actions/runs/34422830379) 已在 `windows-latest` 实际完成锁定源码准备、CLANG64 编译、DLL 收集、ZIP 打包和制品上传。下载后复核得到 441 个文件、29 个 DLL、`PE32+ x86-64` 的 `bin/luanti.exe`，ZIP SHA-256 为 `b186f3a11c60d8940648e1c44a3ebe1786f5f3a2e4f62cfcfe369d7a04212145`，与生成清单一致。

这证明 Windows 原生 runner 可构建并产生完整包，不等同于真实学生机器上的 GUI 运行。后续仍需一台 Windows 实机执行启动、连接、Agent 控制、人工接管和焦点测试。

## 发行步骤

```sh
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m pip wheel --no-deps . -w dist
```

macOS runner 另外执行安装、`tools/package_macos.py` 和 ZIP；Windows runner 执行 `tools/package_windows.py`。两端均上传客户端；`sdk` job 单独上传同一版本 wheel。

同一次 run 的 macOS ZIP 含 649 个条目，解包后为 arm64 Mach-O；10 个非系统动态库均位于 app 内，外部 Homebrew/用户目录加载路径为 0，`codesign --verify --deep --strict` 通过。ZIP SHA-256 为 `ef0ae5cd007486ed32b3ef3508e87fead2f7a8dfeb7e66c7a7792264a4bf0452`。wheel 版本为 0.12.0，可直接执行 `python -m luanti_course --version`，SHA-256 为 `d1145697c088ccf2269d0086954dd5b1267c237dfce424750955bb12a153aaa7`。
