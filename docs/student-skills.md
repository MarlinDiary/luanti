# 学生技能边界（SDK 0.12.0 / 可见客户端 0.9.0）

**SDK 把一个动作做好；学生决定为什么做、何时做、下一步做什么。**
不为了留作业而把寻路、采集、合成故意拆碎；也不默认接管“从空手到钻石”的整条策略。

## 功能清单

| 能力 | SDK 完整处理 | 学生保留的决策 |
|---|---|---|
| `observe` / `find_resource` | 结构化观察，有限半径探索，寻找可接近目标 | 搜索什么、搜索区域、何时换地方；未知矿层不自动透视 |
| `navigate_to` / `navigate_route` | 路径规划、连续移动、转向、门/梯/水与避障；显式允许后可挖路、消耗背包材料搭建 | 目的地与途经点、是否允许改地形、材料与预算 |
| `collect(resource, count)` | 接近目标、选择已有合适工具、挖掘与拾取，以库存增量确认 | 收集种类/数量；缺工具时决定升级，不自动开整条矿业链 |
| `craft(item, count)` | 使用已有材料合成中间件、放工作台、必要的熔炼依赖、实际格子操作 | 决定成品；缺原料先返回，不自行采矿伐木 |
| `smelt(item, count)` | 普通熔炉、原料/燃料装入、等待取出及实际数量确认 | 烧什么、数量、原料/燃料来源与炉子选择 |
| `dig_down(depth)` | 自动生成安全性检查后的下降台阶，清净空，走到末端，记录入口与路线 | 下挖多深、在哪里挖、何时停；不是“找钻石” |
| `dig_tunnel(length, direction=...)` | 按方向开可行走隧道，清净空、前进、记录路线 | 方向/长度、分支与找矿布局 |
| `return_to_entrance()` / `go_to_surface()` | 沿本次挖掘记录返回入口；也可传已知地表坐标 | 何时返回；若最初在洞里，应明确提供真正的地表点 |
| `bridge_to(target)` | 使用指定已有材料，以普通放置动作铺可行路线并到达 | 目标、材料、预算；指定造型用 `build` |
| `build` / `build_ladder` | 逐块施工、支撑检查、库存确认、架梯攀爬 | 图纸/位置、材料准备 |
| `equip` / `eat` / 箱子存取 | 选已有装备、吃指定已有食物、按数量存取、物品守恒 | 装备选择、饮食时机、物资管理 |
| `eat_best_food` / `equip_best_gear` | 按当前饥饿和已有物品选择食物/装备；成功优选进食后恢复原持物 | 获取食物/装备、禁食策略、显式调用或启用快速反应 |
| `attack_entity` / `defend_self` / `flee_from` | 目标绑定攻击、有界接近/自卫/动态撤离，重新观察移动威胁 | 攻击谁、避敌还是自卫、血线与动作预算 |
| `attack_ranged` / `block_with_shield` | 用已有弓箭/盾牌，以弹药或可见 HUD 确认动作 | 武器获取、目标与交战策略 |
| `avoid_projectile` / `survive_blast` | 根据可见轨迹侧移或举盾；对可见爆炸威胁举盾/撤离 | 风险偏好、是否继续原任务 |
| `recover_air` / `escape_hazard` / `extinguish_fire` / `survival` | 恢复呼吸、离开接触危险、到已观察水域灭火；显式启用的生存反应可抢占普通任务 | 后续任务重新规划；没有水时处理 blocked 结果 |
| `Agent` / `CommandPlanner` | 严格执行一个白名单技能并把真实结果交给下一轮 | 目标分解、提示词、模型选择和最终策略 |
| `SkillResult` / `stop` / `resume` | 结构化结果、停止释放输入、显式检查点续做 | 如何处理阻塞、是否继续、是否改变计划 |

新增 [决策辅助](decision-support.md)：`recipes_for` / `plan_craft`、命名地点、`inspect_container`；没有接管资源采购策略。

## 最小使用方式

```python
from luanti_course import Game, Traversal

with Game.connect() as game:  # 先在可见课程客户端中进入世界
    with game.control():
        result = game.collect("mcl_core:tree", 3)
        if result.ok:
            result = game.craft("wooden_pickaxe")
        print(result.to_dict())
```

三个原木可覆盖新工作台、木棍和一把木镐；这是脚本明确选择的两项任务，不是 SDK 暗中决定发展路线。正常画面可一直看，F8 显式人工接管，Esc 紧急停止。不需模型 SDK、Node.js 或 Docker。

## 下挖、隧道与返回是三个完整动作

```python
# 先备好能挖当前方块的工具；路径/深度由学生决定。
result = game.dig_down(6, checkpoint="tasks/descent.json")
if result.ok:
    result = game.dig_tunnel(4, direction=(0, 0, 1))
# 仍在同一 Game 连接中，包含隧道的整次路线都保留着：
return_result = game.return_to_entrance()
```

- `depth` / `length` 为 1–64 格；方向是水平单位向量。下挖省略方向时会尝试局部可行方向，不直挖脚底。
- **下挖结束留在下面**，不立刻返回。`excavate(route)` 的老默认仍为挖完返回，不改旧 API 语义。
- 普通工具/材料、稳定底面、落沙、流体、危险邻接与身体净空都检查；遇到危险或预算耗尽，会保留已完成步骤和世界变化并报告原因。
- 默认编辑总预算 32；需要更长任务可显式传 `Traversal(edit_budget=64)`（最大 128）。下挖一层可能需要清多个方块，深度不等于编辑次数。一次技能仍受时间、范围和观察上限约束。
- 返回的默认目标是**记录的挖掘入口**，不是自动判断天空。若从洞穴内部开始，请用 `game.go_to_surface(known_surface_position)`；没有入口/坐标时返回 `surface_unknown`，不猜海拔。
- `bridge_to` 是“借助搭建到达”，可利用已有道路，并不强制造出某个桥形。`max_blocks` 与传入/全局地形预算取较小者；门交互也计入总编辑预算。
- `reset_mining_trip()` 显式开始另一趟挖掘，不删除文件。不要将旧路线用在另一个世界。

## 取消、重新连接与续做

```python
# 取消或 Python 断开后，保持同一客户端、同一世界：
with Game.connect() as game:
    with game.control():
        result = game.return_to_entrance(checkpoint="tasks/descent.json")
        if result.ok:
            result = game.resume("tasks/descent.json")
```

挖掘检查点记录已确认步数和真实走过的路线；返回后继续会先走回已确认末端，再挖剩余部分。完成的检查点再次续做为空操作，不多挖一层。每个下挖/隧道任务用一个新文件；后续隧道若需要跨连接返回，给隧道也指定新检查点（包含当时整趟入口路线），恢复时用最新文件。没有检查点时，路线只在当前 `Game` 对象里保存。

检查点不冻结世界：外部变更可能阻断返程；不会瞬移、穿墙、重放不明结果。新客户端进程/切换世界应新建检查点。

## 进食的确认边界

```python
game.eat("mcl_core:apple", 2)
```

只吃指定已有的可食用物品，不自动找食物；使用普通右键、正常进食时间与冷却，以库存减少确认 `consumed`。吃满了或服务端未消费会在有界等待后返回 `food_not_consumed`，保留已吃数量。超时/停止后释放按键。客户端 0.8.0 从已显示的 HUD 导出饥饿值；HUD 缺失或不唯一时为未知，不猜隐藏饱和度。`eat_best_food()` 按现有食物选择，成功后恢复原持物；`with game.survival():` 可自动判断饮食时机，仍不自动找食物。特殊食物的正常副作用由游戏决定；创意模式不扣物品时不据此报告消费成功。

## 历史检查点升级注意（0.7–0.9）

- `craft(..., gather=False)` 现在是默认值。已有材料的中间件/工作台/熔炼依赖仍完整处理；不是要求学生摆每个合成格。
- `collect` / `craft` 默认 `allow_tool_crafting=False`。`recover=True` 继续处理有限重试、背包合堆和确认后的重新规划，**不再隐含工具升级**。
- 高级/教师脚本可显式开 `gather=True`、`allow_tool_crafting=True`。后者还需 `recover=True`，可能连带采集工具原料。它们是分开的选择，应由课程确定是否对作业开放。
- **0.7 的 `collect` / `craft` 检查点缺少新增工具策略字段，会报告 `checkpoint_conflict`，不自动迁移。** 0.9 提供显式 `upgrade_checkpoint(old, new)`：校验客户端/数量后复制升级，保留旧文件与在途熔炼；此后只续做新文件。详见 [决策辅助与迁移](decision-support.md)。0.8 检查点续做保留自己的原请求（包括显式 `gather=True`），不会套用新的默认值。
- 当前已提供近战、远程、盾牌、投射物/爆炸反应和持续燃烧处理，详见 [生存 API](survival.md) 与 [课程版收尾](course-completion.md)。种植、交易、多角色协作尚无完整专用 API；一键通关策略不由 SDK 接管。模型无关的 [参考 Agent](reference-agent.md) 只展示 observe/skill/result/replan 接线。

## 验证与平台

`tests/integration/student_skills.py` 仅连接隔离的持久测试会话，不启动/重启 GUI；与基础技能、扩展工作流和 30/60 FPS 地形套件一起验证。完整命令、字面输出、失败探索与最终结果在发布 evidence 中。场景覆盖不是“任意地形保证成功”。实机验证使用 macOS Apple Silicon + 固定 VoxeLibre；真实课程服只验证现场可安全执行的普通玩家动作。Windows 有固定构建/打包 workflow 和 ZIP 单测，原生 runner/实机验收仍单独列为待验。当前汇总见 [课程版收尾](course-completion.md)，历史通过项和失败轨迹保留在各版本证据中。
