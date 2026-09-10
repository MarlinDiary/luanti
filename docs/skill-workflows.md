# 技能工作流（SDK 0.12.0，客户端 0.9.0）

本次补齐的是确定性技能层，不是替学生编写 LLM 决策器。依旧只需 Python 标准库；复用正在显示画面的课程客户端，无需重启原生客户端。

## 1. 同一套地形策略用于整条技能链

```python
from luanti_course import Game, Traversal, ExplorationMemory

with Game.connect() as game:
    game.traversal = Traversal(
        allow_swim=True, allow_jump_gaps=True,
        allow_dig=True, build_with="mcl_core:cobble", edit_budget=64,
    )
    game.exploration_memory = ExplorationMemory(ttl=60)
    with game.control():
        result = game.collect("group:tree", 3)
        print(result.to_dict())
```

`find_resource`、`collect`、`craft`、`place_block`、熔炼、箱子存取、施工、挖掘、路线执行都读取 `game.traversal`，也接受单次 `traversal=Traversal(...)` 覆盖。`navigate_to` 保留旧版显式地形参数，显式传入的字段覆盖继承策略；例如 `allow_dig=False, build_with=None` 会关闭本次挖路和搭建，不受全局配置影响。挖路、施工默认关闭；启用后消耗正常工具和材料。动作预算在一次复合技能内共享，不因内部调用自动重置。

游泳默认关闭，需要像上例一样显式设置 `Traversal(allow_swim=True)`。`recover_air` 的紧急浮出水面不改变后续采集/导航的地形策略；要从水中继续上岸采集，仍需明确允许游泳。

跨水不等于停在水面上操作：需要静止瞄准/开界面的交互会寻找实际有支撑的站位，避免游到射程边缘后停止输入、自然下沉导致挖掘失败。

## 2. 熔炼、燃料与制作链

默认 `gather=False`，先由学生决定采什么、何时升级工具。下面 `gather=True` 是显式的高级组合选项，不是默认学生模式。

```python
result = game.smelt("mcl_core:iron_ingot", 3, gather=True)
# 或只使用指定炉子和已有原料、燃料：
result = game.smelt("mcl_core:iron_ingot", 3,
                    furnace=(12, 100, 4), fuel="mcl_core:coal_lump")
# craft 自动安排材料依赖中的熔炼步骤：
result = game.craft("mcl_tools:pick_iron", gather=True)
```

- 普通 VoxeLibre 熔炉适配器：接近/放置炉子、打开实际界面、装入原料与燃料、等待、取出产物；燃烧时间来自固定版本导出数据。
- `gather=True` 可补原料、制作并放置熔炉、补基本燃料。默认选煤/木材，不自动拿工具或带容器的燃料烧掉；可显式指定 catalog 支持的燃料。
- 优先直接熔炼所需数量，避免为了三个铁锭走“先凑九个原矿压块再拆块”的路线。
- 只使用空闲炉子，或检查点记录的同一在途任务；已有不明原料/成品会返回 `furnace_busy`。服务器产物、双方库存变化是完成依据，不用睡够几秒推定成功。
- 装入的剩余燃料保留在炉中；取消时炉子按游戏规则继续燃烧。错误/取消时关闭仍由 Agent 持有的工作站界面，保留物品。
- 目前是普通熔炉与正常烹饪配方，不包含酿造、锻造、特殊模组机器或任意自定义界面。

## 3. 箱子存取

0.9 可先 `game.inspect_container(position)` 检查实际显示的槽位，不转移物品；它仍需接管以接近和打开箱子，见 [决策辅助](decision-support.md)。

```python
game.deposit((12, 100, 4), "mcl_core:cobble", 32)
game.withdraw((12, 100, 4), "mcl_core:cobble", 16)
game.restock((12, 100, 4), "mcl_core:cobble", target_count=32)  # 只取缺口
```

适配普通/陷阱单箱与双箱的 VoxeLibre 表单。每次使用当前 form_id 与实际显示的槽位；确认来源减少、目的增加，保留物品元数据。不会把玩家背包的同名 `main` 列表误认成箱子。缺物品、满箱、满背包、表单变化会返回结构化原因和已转移数量，不丢物品、不盲目重放。箱子的选择及满包时存什么仍由学生决定。

## 4. 明确的检查点与续做

```python
result = game.craft("mcl_tools:pick_iron", checkpoint="tasks/iron-pick.json")
# 本次 Python 运行结束、取消后：重新连接同一客户端，再显式接管。
with Game.connect() as game:
    with game.control():
        result = game.resume("tasks/iron-pick.json", timeout=300)
```

`collect`、`craft`、`smelt` 支持 `checkpoint=路径`。新增挖掘检查点见 [学生技能](student-skills.md)，它记录路线/步数，不是物品增量账本。一个文件代表一个固定的“新增 N 件”目标：

- 原子落盘基线、目标总量、最近确认库存、在途熔炼和完成标记；文件锁阻止并发执行同一检查点。
- 重新观察真实库存和合成格，再计算剩余数量；制作中断在熔炼阶段时，先接回炉内在途材料再重新规划。
- 完成后再次 `resume` 是空操作，不再生产；请求不同、客户端不同、已确认产物减少或账本不一致会报告冲突。
- 不自动接管、不自动跨连接错误重放。不保证任意外部修改下的事务“恰好一次”；结果不明时依赖实际世界核对，而不是重播日志。
- 检查点绑定当前运行客户端。保持同一世界，不跨切服/切世界复用；更换客户端进程或新任务使用新文件。探索记忆不是检查点中的全世界地图。

## 5. 阶梯挖掘、施工和架梯

一般学生先用 `dig_down(depth)` / `dig_tunnel(length, direction=...)`；无需逐格填写路线。下面 `excavate(route)` 保留给需要精确形状的脚本。

```python
# 坐标是整数“脚所在的方块格”，比 observe().position 的脚底 y 通常高 0.5。
game.excavate([(0,100,0), (1,99,0), (2,98,0), (3,97,0)])
# 默认挖完返回起点；每步检查已观察的返程路线。
game.build([("mcl_core:cobble", (2,100,0)),
            ("mcl_core:cobble", (2,101,0))])
game.build_ladder((0,100,3), 5, backing=(1,0,0),
                  backing_material="mcl_core:cobble")
```

- `excavate` 支持邻接的水平隧道/一格上下台阶；清理身体扫过的头部净空。检查稳定底面、头顶落沙、侧方/上方流体和危险方块；不直挖脚下，不把盲井当路线。默认核对返程并返回。
- `build` 接受最多 128 个 `(物品ID, 坐标)`，寻找可放置的顺序，逐块实物确认；已是指定方块时跳过，可以重跑部分完成的图纸。真正悬空且没有可达支撑面时明确受阻，可结合搭桥/垫台阶策略施工。
- `build_ladder` 最多 32 格，沿已有墙面放置，或用 `backing_material` 补稳定整块背墙，边架边攀爬，结束下到底部。每块墙/梯子均消耗预算和材料。
- 普通世界依然保留已挖/已放的变化；失败不是回滚游戏世界。

## 6. 分段路线与观察记忆

```python
game.exploration_memory = ExplorationMemory(ttl=60, max_nodes=60000)
game.navigate_route([(20,99.5,0), (20,99.5,20), (0,99.5,0)])
```

- `navigate_route` 连续通过具备已知安全缓冲的中间路点，终点停稳；独立 `navigate_to` 每次返回都停止。转弯、危险、新障碍和等待交互确认仍可减速或停下。
- 一个技能内支持有界分段目标；搜索半径上限 4096、路线最多 256 个目标、一次技能最多 5000 次观察。达到预算会返回明确状态，而不是无限循环。
- 跨技能复用已观察几何、探索访问计数和短期不可交互障碍；默认地图 TTL 60 秒，障碍最长 5 秒，实际节点变化会撤销旧障碍。不同客户端的记忆隔离；可 `game.exploration_memory.clear()`。
- 未知区域逐段观察推进；不会把未知节点当空气。规划过程检查取消/截止时间，几何计算缓存只在单次规划内使用，下一次观察不沿用旧碰撞结果。

## 7. 生存中断后重新规划

使用 [survival_collect.py](../examples/survival_collect.py) 展示“采集 → 生存反应 → 重新观察背包 → 只请求剩余数量”。已有库存增量达标也先等待正在进行的反应、检查事件和控制状态，再报告完成；失败反应返回 `needs_replan`，超时返回 `survival_timeout`。这是示例的显式策略，不是 SDK 自动重播上一个任务。详细语义见 [生存 API](survival.md)。

## 验收

`tests/integration/extended_skills.py` 连接持久测试会话；覆盖六类技能、跨技能组合、物品守恒、取消/重新连接续做、危险条件受阻。沿用 `docs/testing.md` 的静音、不抢焦点、原进程重置/陆地待命机制。具体通过项、失败探索和精确命令见本次 evidence 记录，不把 API 存在或配方数量当作全覆盖证明。

## 8. 接入 LLM，但保留学生策略

```python
from luanti_course import Agent, CommandPlanner

planner = CommandPlanner("python my_model_adapter.py")
result = Agent(game, planner, max_steps=24).run("收集三块木头并制作木镐")
```

适配器每轮从 stdin 接收有界观察、上一步 `SkillResult` 和白名单，stdout 返回一个 `{"name": ..., "args": ...}`。SDK 不接受任意 Python/私有方法名，不缓存旧实体引用，也不会在模型失败后猜一个动作。参考结构与完整边界见 [模型无关参考 Agent](reference-agent.md)。
