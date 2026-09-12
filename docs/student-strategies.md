# 学生策略示例

SDK 只负责有边界、可验证的技能。`examples/` 中的普通 Python 决定何时以及为何调用它们，便于学生直接阅读、改写或换成自己的 Agent/LLM。

## 1. 第一份有界策略

[`student_first_project.py`](../examples/student_first_project.py) 执行：

```text
观察 → 接管 → 记住起点 → 采集 3 个原木 → 合成木镐 → 返回起点
```

```sh
python examples/student_first_project.py
```

它适合先确认安装、连接和 SkillResult 分支。死亡至多显式重生一次；受阻后把原因交给学生，不自动重放。

## 2. 默认无限循环的自主矿工

[`student_autonomous_miner.py`](../examples/student_autonomous_miner.py) 是完整参考策略：

```sh
python examples/student_autonomous_miner.py
```

默认没有动作数或循环数上限。F8 人工接管、Ctrl-C、断线或无法完成的生存反应会停止；“无限”指策略持续观察和重新规划，并非绕过服务器规则或保证角色永远不死。

策略每轮都从真实状态重新选择一个完整技能：

1. 低氧、接触危险、燃烧、严重饥饿优先；长技能期间另有 `SurvivalConfig(enemies="avoid")` 快速反应。
2. 地表保留木材；木镐 → 石镐 → 铁镐 → 钻石镐逐级升级。
3. `wear >= 52000` 的镐视为即将耗尽，在长挖掘前先制作替代品；中途真的损坏也会根据新背包回到同一升级链。
4. 缺煤、铁或钻石时先在当前范围寻找；找不到才下降到目标高度或开一条 12 格水平矿道。
5. 东西向长矿道之间用 3 格短连接段形成蛇形分支，避免等长四边形回到旧路；默认每趟最多 8 条长分支。找到 3 颗新钻石、背包将满或分支预算用完时，沿真实记录路线返回入口。
6. 返回命名起点，重置本趟路线；背包整理后仍将满时，只丢弃一整组低价值矿道方块并确认真实库存变化，保护矿物、钻石、木材、工具、武器、护甲和食物。
7. 补齐材料并开始下一趟。死亡后显式重生、丢弃已失效路线并从新状态规划。
8. 每个决定、SkillResult、生存事件、回退等待和最终原因都输出 JSON，便于学生保存轨迹或接入模型。

它不打开 `collect(..., allow_tool_crafting=True)` 或 `craft(..., gather=True)`：采集技能不会暗中升级工具，合成技能不会暗中寻找整个资源链。自动熔炼只发生在铁镐的既有材料计划里；寻找矿层、何时收集、制作哪个工具和失败后的下一步都在本脚本中可见。

### 有界演示与参数

```sh
# 只看 10 个成功技能，适合课堂演示
python examples/student_autonomous_miner.py --max-actions 10

# 完成一次下矿/返程周期后结束
python examples/student_autonomous_miner.py --max-cycles 1

# 改目标高度、分支长度和每趟分支数
python examples/student_autonomous_miner.py \
  --target-y -48 --tunnel-length 16 --branch-spacing 3 --branches-per-trip 12
```

`--no-survival` 只用于受控本地实验。正常服务器运行保持快速生存层开启。所有动作仍受可见客户端观察范围、背包、工具、碰撞、危险、网络、世界边界和普通服务器权限约束。

## 3. 为什么保留两份

入门脚本用于讲清 `observe → decide → act → inspect result`；自主矿工展示长期状态、工具耐久、资源依赖、矿道布局、生存抢占、死亡恢复和失败退避。把它们合成一个巨型“第一课”会让学生难以区分 SDK 机械能力和自己要实现的策略，因此文件保持两个明确层级。
