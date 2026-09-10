# 决策辅助（SDK 0.9 / 可见客户端 0.6）

这些接口让学生获得信息，再决定下一步。不是一键找钻石的策略器；既有完整技能不拆碎。安装新的 Python wheel 即可使用，原生客户端无需重启。

## 1. 配方和材料计划：不接管、不移动、不采集

```python
from luanti_course import Game

with Game.connect() as game:
    print(game.recipes_for("wooden_pickaxe"))
    plan = game.plan_craft("wooden_pickaxe", count=1)
    print(plan.to_dict())
    if not plan.materials_ready:
        print("建议补充的原料：", plan.missing)
        # 由学生决定是否收集这些原料、从哪里取得或换目标。
```

- `recipes_for(item)` 返回固定版本 catalog 中的普通合成/烹饪配方和来源，不询问服务器、不进入界面。未知物品返回空配方列表。
- `plan_craft(item, count=1, radius=0)` 观察自己的库存，只计算计划。`count` 为 **1–64 件新增产物**，不是希望背包达到的总量；多产物配方可能多做一些。
- `radius=0` 默认不扫描地形；若服务器允许，可设 `radius=6` 识别附近已观察工作台。未观察到工作台时，计划可能计入新工作台材料。
- `materials_ready` 仅表示配方输入（含所需中间件/工作台）可由已持有材料满足。**不代表现在一定做得出来**：普通熔炉和燃料、工具、可达性、背包空间、服务器实际配方仍在执行时检查。`requirements` 明确列出这些未检查项。
- 缺原料时 `missing` 是 catalog 规划器提出的一份采购清单，不保证唯一、最省或附近确实存在；`steps` 中的 `collect` 只是计划数据，**没有执行采集**。含熔炼时清单不包含炉子/燃料采购。
- `missing_complete=False` 表示规划未完整完成，结合 `reason` / `diagnostic` 处理；空字典不等于无需材料。`source` 指明版本来源。
- 库存只计主背包、合成格和已产出的合成结果；不把预测结果、表单镜像或已装备物品当作自由原料。

执行仍由脚本显式选择，例如在准备好材料后进入 `game.control()`，调用 `craft(...)`。默认 `gather=False`、`allow_tool_crafting=False` 不变。

## 2. 命名地点：明确保存、明确返回

```python
with Game.connect() as game:
    game.remember_location("基地")  # 记下当前观察到的脚底坐标，不移动
    game.save_locations("tasks/places.json")
    print(game.saved_locations())
    # 可以完成学生自己选择的其他任务。
    with game.control():
        result = game.go_to_location("基地")
        print(result.to_dict())
```

重新连接同一运行中的客户端时，先 `game.load_locations("tasks/places.json")`。保存的文件绑定客户端 endpoint；**只在同一客户端进程、同一世界使用**。它不是跨服务器坐标库，当前接口没有自动识别世界切换。换世界/重新启动客户端应使用新文件，避免旧坐标误导。

`load_locations` 验证完整文件后才替换内存中的地点；失败不清空已有记录。`save_locations` 不覆盖其他客户端/其他格式文件。地点名称支持中文，长度 1–64，最多 128 个；`forget_location(name)` 显式删除。文件以 UTF-8 读写。

`go_to_location` 委托现有连续导航，继承通常的地形策略和参数；默认范围 64、超时 90 秒。远处地点可显式增大 `search_radius` / `timeout`。未知名称返回 `location_unknown`，不移动；不会自动选择基地或探索一条无限远道路。

## 3. 箱子检查：查看内容，不进行存取

```python
with Game.connect() as game:
    with game.control():
        result = game.inspect_container((12, 100, 4))
        if result.ok:
            print(result.details["counts"])
            print(result.details["lists"])
        else:
            print(result.reason)
```

使用既有普通/陷阱单箱、双箱的 VoxeLibre 表单适配器。返回物品计数以及实际显示的各列表/槽位、磨损、`stack_key`、`form_id` 和观察帧；结束关闭仍由该技能持有的界面。没有 `deposit` / `withdraw` 操作，`items_transferred=0`。

**它仍是游戏动作**：需要接管，可能移动到箱子附近并右键打开；沿途继承你允许的地形策略，陷阱箱也可能触发游戏机制。不要把它理解成远程透视箱子或保证完全不改变世界的查询。未支持的节点返回 `station_type_unsupported`。内容是该观察帧的快照，其他玩家之后可能改动。

## 4. 返回入口的明确名称

```python
with game.control():
    game.dig_down(6, checkpoint="tasks/descent.json")
    print(game.return_to_entrance().to_dict())
```

`return_to_entrance(timeout=600, search_radius=4096, traversal=None, checkpoint=None)` 返回记录的挖掘入口。入口可能在洞穴里，不推断天空/海拔。它沿用既有路线与检查点，不新建另一份挖掘策略。跨连接返回可传最新挖掘检查点。

旧名 `go_to_surface()` 保留兼容；只有已知真正地表坐标时使用 `go_to_surface(known_surface_position)`。没有入口记录时，返回明确的 `surface_unknown`。

## 5. 显式复制升级 0.7 数量检查点

0.8 增加了工具策略字段，旧 `collect` / `craft` 文件直接续做会发生 `checkpoint_conflict`。0.9 提供显式迁移，不偷偷改变已有请求：

```python
with Game.connect() as game:
    migrated = game.upgrade_checkpoint(
        "tasks/old-craft.json", "tasks/upgraded-craft.json",
        allow_tool_crafting=False,
    )
    print(migrated)  # 此时仅观察/写新文件，还没继续执行
    with game.control():
        result = game.resume("tasks/upgraded-craft.json")
        print(result.to_dict())
```

- 原文件必须是同一客户端、同一世界中缺少工具策略字段的旧 collect/craft 数量检查点；目的文件必须是新路径。
- 保留初始量、目标量、已确认进度、完成标志、原 `gather` 选择及在途熔炉记录；明确添加工具策略，默认不自动制工具。
- 校验源文件未变化、文件锁、客户端绑定、库存是否低于最后已确认数量。异常时不输出新检查点、不执行任务；不靠重新申请完整数量掩盖旧进度。
- **升级后仅使用新文件续做。旧文件作为备份保留，不要交替执行两份数量账本。** 完成的文件重复续做为空操作；断开不等于熔炉停止燃烧。
- 库存账本不是物品来源证明：不要在中断与续做之间自行丢弃、合成或以同类物品补齐旧数量；先核对旧任务和在途炉子。
- 已含工具策略的 0.8/0.9 文件不需升级，直接用 `resume`；此接口不迁移挖掘/熔炼的其他格式，不修改已安装 Python 环境。

## 验收边界

新增查询、命名地点、单箱检查、部分完成的采集/合成迁移、在途熔炉迁移与返回入口有持久客户端实机测试。双箱沿用原有表单适配器；新增 inspect 接口本次独立实测为普通单箱，不把支持范围当作所有服务器上的实测结论。

本次环境是 macOS Apple Silicon + 固定 VoxeLibre；Windows 原生客户端和真实课程服务器仍待各自验收。0.6 原生接口未导出饥饿值；`eat` 继续按真实库存消费确认，不伪造饥饿观测。没有新增战斗、交易、种植或 LLM 自主决策器。

### 0.9 记录的运动问题（0.10 已修复）

30 FPS 的水岸测试有一次正常到达但岸边峰值达到 100.345（岸面 99.5），未通过 `<99.9` 的无额外上跳门槛。60 FPS 同场景通过；0.8 同输入连续五次均通过，说明问题有时序波动，并非每次复现。本次发布的运动/导航代码与 0.8 保持一致，不据此声称该问题已修好。

尝试提前抬升并在岸边取消游泳跳跃的候选，五次中三次仍未过门槛，因此没有采用。功能到达结果和流畅性结果在验收中分别记录。这个版本可用于新增 SDK 接口开发，完整课堂发布仍应解决/验收这一边界及 Windows、真实课程服务器。

后续状态：SDK 0.10 / 原生客户端 0.7 把游泳反馈移到物理子步，处理一帧内接岸后的按键失效；上面的数字和未采用候选保留为 0.9 历史记录，当前实现与验收见 [连续动作](fluency.md)。
