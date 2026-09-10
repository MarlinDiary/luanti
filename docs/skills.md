# 学生动作接口（SDK 0.12.0 / 客户端 0.9.0）

使用课程客户端 0.9.0 和 Python SDK 0.12.0。学生不需要 C++、Node.js、Docker 或模型供应商 SDK。正常游戏画面一直可见；Agent 模式不抓鼠标。F8 显式切换人工，Esc 紧急停止。

```python
from luanti_course import Game

with Game.connect() as game:
    with game.control():
        result = game.craft("wooden_pickaxe")
        if result.ok:
            print(game.collect("mcl_core:cobble", count=3).to_dict())
```

`count` 是**新增**数量，不是背包目标总量。一次配方产出多件时可能略多于请求数量。失败前已产生的正常游戏变化会保留。

默认不自动采购原料或升级工具；[完整边界与新增动作](student-skills.md)。工作流见 [熔炼、容器、续做、施工和长路线](skill-workflows.md)。

0.9 新增 [配方与缺料查询、命名地点、箱子检查、旧检查点复制升级](decision-support.md)。这些帮助学生做决定，不含 LLM 决策器。

## 高层动作

| API | 行为 |
| --- | --- |
| `navigate_to((x,y,z), timeout=90)` | A* 地形规划、连续跟随和转向、遇阻重规划。坐标是角色脚底位置，与 `observe().position` 一致。 |
| `find_resource("group:tree", search_radius=32)` | 搜索可接近的匹配方块，必要时探索；不挖掘。结果 `position` 为方块坐标，`player_position` 单独给出角色位置。 |
| `collect("mcl_core:cobble", count=3, recover=True)` | 优先拾取已有掉落物，选择能覆盖多个目标的站位，批量挖掘附近方块，再按实际掉落物位置拾取；以背包增量确认。 |
| `craft("wooden_pickaxe", count=1, gather=False, recover=True)` | 用已有材料规划中间件、工作台和真实合成格；相邻相同配方合批，复用已打开的合成界面。 |
| `equip("wooden_pickaxe")` | 按名称选到手上；主背包中的物品会自动移入快捷栏。 |
| `equip("mcl_armor:helmet_iron", destination="armor")` | 放入相应护甲槽；旧装备移回背包。也支持 `destination="offhand"`。服务端装备规则照常生效。 |
| `place_block("mcl_core:cobble", (2,100,0))` | 接近目标、寻找可用表面、瞄准放置一块；确认目标方块和库存消耗。坐标为整数方块坐标。 |
| `organize_inventory()` | 合并可腾出空槽的相同物品堆；保留数量、磨损及自定义标签等元数据，不丢弃物品、不打乱独特物品。 |

可用完整物品 ID、资源分组（如 `group:tree`）及常用别名：`wooden_pickaxe` / `木镐`、`crafting_table` / `工作台`、`stick` / `木棍`。装备、放置和合成通常使用具体物品 ID。

## 普通 Python 循环也能连续移动

单次 `move()` 在返回时停止，保留“一次有界动作”的语义。需要连接多个短动作时，显式使用连续作用域：

```python
with game.motion() as motion:
    for _ in range(10):
        motion.move("forward", seconds=0.1)  # 中间不释放移动输入
# 正常结束、异常退出都会停止
```

反馈控制可以直接更新世界朝向与模拟摇杆速度：

```python
with game.motion() as motion:
    motion.steer(heading=90, speed=0.5, lease=0.4)
    # 读取 game.observe()，在租约到期前按观察更新 steer。
```

- `steer()` 非阻塞，`speed` 为 0–1，`heading` / `pitch` 为角度，可传 `jump` / `sneak`。这不是瞬移。
- 没有后台线程无限续租：脚本停滞会在租约到期后停止。默认 400 ms，最大 1 s。
- `motion` 内可观察或紧急停止；高层技能需在退出该作用域后执行，避免两套控制器争用同一角色。
- `look()` / `look_at()` 默认逐帧平滑转向并等待到达，默认超时 2 s；需要旧版即时语义时显式传 `instant=True`。连续移动与转向一起控制时用 `motion.steer()`。

0.10 的倒走搭桥、固定扫向施工、连续返程和独立移动视角见 [连续动作](fluency.md)。

## 地形策略（客户端与 SDK 0.6）

```python
# 普通地形和门默认开启；可能改变世界的动作分别显式同意。
result = game.navigate_to(target,
    allow_swim=True, allow_climb=True, allow_jump_gaps=True,
    allow_dive=False, allow_interact=True,
    allow_dig=True, build_with="mcl_core:cobble",
    max_gap=2, max_drop=1, edit_budget=24)
print(result.to_dict())
```

- 规划使用引擎逐节点旋转/连接后的碰撞盒、角色实际宽度/高度和移动物理。窄门以偏移后的净空点通过，不缩小角色或穿过碰撞盒。连续路径前视检查真实支撑，不把“这个格子中心可站”当作整格都可走。
- 门和栅栏门使用普通右键，并确认节点或碰撞盒确实变化；双扇/上下半门每次交互后重新观察，失败后将其视为障碍并尝试绕行。活板门等带同类 group 的节点走同一机制，但不同模组仍需验收。
- `allow_dig` 默认 False；选择真实可用工具，拒绝脚下支撑、落沙/流体危险顶板。`build_with` 默认 None；指定背包里的稳定整块材料。搭桥通过正常蹲伏、对准侧面和放置，垫台阶通过正常方块面放置。每一步均核对实际节点和库存，再重新规划。
- `edit_budget` 默认 32，范围 0–128，限制开门/挖掘/放置的总确认次数。缺工具/材料或服务器拒绝操作会得到结构化结果；不凭空生成方块。已完成的世界改变留在 `terrain_changes`，失败也保留部分进度。
- `allow_jump_gaps` 默认 False；`max_gap` 默认 2，允许 1–3，但仍受实际速度/跳跃速度/重力、已知落点和净空约束。较宽沟壑会检查助跑；缺少助跑区时报告受阻。不是承诺任意三格跳跃。
- `max_drop` 默认 1，允许 0–3；更大的悬崖需要绕行或搭建路线。改变服务器重力后的落差风险仍需对应服务器验收。
- 水中使用正常跳跃/下潜输入和原生重力/浮力；没有直接改位置、速度或做装饰性正弦起伏。上岸提前抬升并释放水中跳跃，避免出水后额外蹦起。垂直上/下游时，不为几厘米的水平误差来回转头；水面模式也可从已经发生的被动下沉恢复。
- 水面目标脚底比水面低约 0.45 格；潜水目标按实际脚底深度解释。`allow_dive=True` 需要 `allow_swim=True`。低气量时最多两次沿已观察路线返回水面、确认补气，再继续原目标；没有已知空气路线时明确停止，不保证任意长度的水下任务。
- 技能结束/取消/断线会释放输入，水里随后仍会自然下沉。学生需要持续游泳时使用 `game.motion()` 的 `steer(..., swim_y=高度)`，不要同时指定 jump/sneak。测试则在结束后重置到陆地待命。
- `observe()` 新增 `physics`；`node_defs` 新增节点 `groups`。`inspect_item` 只读检查待用建筑材料的实际客户端定义，仍遵守服务器观察限制。
- 覆盖是已测用例，不是“任意地形百分之百成功”；详见 [覆盖矩阵](terrain-coverage.md)。

## 有界恢复，而不是盲目重试

`recover=True` 默认启用：

- 缺工具时默认报告 `suitable_tool_required`，已有合适工具会自动选择。`recover` 不再隐含工具升级。仅在 `collect` / `craft` 显式传 `allow_tool_crafting=True` 且 `recover=True` 时，才启用旧的有界补工具逻辑；它可采集材料，应由课程明确决定是否允许。
- 背包无空间时尝试无损合并。合并仍腾不出空间就报告 `inventory_full`，由学生的上层策略决定存放；不擅自丢弃物品。
- 合成材料中途变化、工作台消失等可确认的状态变化，归还网格材料后重新观察规划，最多重规划三次；只规划剩余目标数量。
- 接近/挖掘受阻有有限次重试；拾取重新观察掉落物位置；临时阻挡在找不到路线时最多再检查两次。
- 原始请求的超时、搜索半径和观察预算始终有效。取消、受伤、死亡、连接中断或结果不明不会触发自动重放。潜水换气是独立的有界导航恢复。
- 服务端合成预览不匹配时直接停止并保留材料，不猜测“已经合成”。`recover=False` 可关闭自动整理、合成重规划以及显式开启的补工具；技能本身的有限路径搜索与目标重试仍存在。

## 结果、数据和边界

`SkillResult.status`：`success`、`blocked`、`cancelled`、`timeout`。含 `reason`、部分完成数量、`trace`、耗时和角色位置。`ok` 仅代表实际目标被确认，不等于动作请求被接收。低层 `Submission` 仍只表示请求已提交。

## 生存补全（0.12）

```python
state = game.observe()
arrow = next((e for e in state.entities if e.projectile), None)
if arrow:
    result = game.avoid_projectile(arrow)

stalker = next((e for e in state.entities if e.explosive), None)
if stalker:
    result = game.survive_blast(stalker)
```

`attack_ranged` 只消耗已有弓箭；`block_with_shield` 只使用已有盾牌；`extinguish_fire` 只去已观察水域。所有目标实体都绑定当前连接的 `(id, instance)`，旧引用、另一连接的实体或错误类型会被拒绝。详见 [课程版收尾](course-completion.md)。

`observe().item_entities` 提供附近、客户端已复制的可见物品形状对象的位置和显示物品名；它们是**拾取候选**，不是服务端实体类型、数量或可拾取性的证明。静止物品也被观察；仅以真实库存增量确认拾取。物品元数据的等价键用于避免错误合堆。

遵守服务器观察限制，不读取全世界地图或服务器内部状态。配方包来自固定 VoxeLibre 源码版本；配方数量不等于验证覆盖率。普通熔炉由独立技能处理，并接入制作依赖；酿造、锻造及任意自定义表单回调不由普通网格合成器处理。工作台会保留在世界中。

同一角色只有一个动作执行者。Esc、切换人工、停止、断线和短租约到期均释放输入；脚本不自动夺回控制权。

## 测试与扩展

- 测试仅使用独立本地 profile/世界。统一设置 `LUANTI_COURSE_TEST_SILENT=1`，关闭音频设备；测试配置的两种音量也为 0。macOS 拦截库审计鼠标捕获/移动请求。不改变系统音量或学生正常配置。
- 当前首选 [持久会话](testing.md) 的 `terrain_suite.py` / `skills_session.py`，不反复启动游戏。以下旧脚本保留用于历史证据复现：
- `tests/integration/high_level.py`：正常任务、批量动作、恢复、装备、放置和地形用例；测试 Lua 不属于学生客户端。
- `tests/integration/action_metrics.py`：同一输入比较合成/采集请求次数、耗时及执行轨迹。
- `tests/integration/smooth_motion.py`：真实位置/速度、停走次数、到达误差及后台帧率回归。
- `RecipeBook(data)` 可替换课程配方包，不执行其中的代码。`navigation.py`、`recipes.py`、`skills.py`、`motion.py` 均不依赖模型厂商。
- 当前本地实机验收为 macOS Apple Silicon + 固定 VoxeLibre；真实教学服务器只验现场可安全执行的普通玩家动作。Windows 构建/ZIP 流程已有自动化，原生 runner/实机启动仍需单列证据。见 [跨平台交付](cross-platform.md)。


### 连续路线（0.11.6）

连续行走时使用一次 `game.navigate_route([p1, p2, p3])`，不要在循环里重复调用短距离 `navigate_to()`：后者每次返回都按契约释放输入。路线的中间路点连续通过、最后一点减速停稳；若下一步规划前没有已知且有支撑的缓冲距离，会正常减速。取消、危险、交互施工和服务端确认仍保留必要停顿。
