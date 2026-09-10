# 模型无关的参考 Agent

## 它解决什么

课程需要同时展示两层：

1. 客户端和 SDK 提供可观察、可验证的完整动作；
2. 学生或模型负责目标分解、技能选择和失败后的重新规划。

`luanti_course.Agent` 是第二层的最小参考实现，而不是课程答案。它采用固定循环：

```
observe -> planner returns one SkillCall -> execute -> SkillResult -> observe again
```

每一步只允许一个白名单技能。目标实体必须使用当前观察中的 `[id, instance]`，旧引用会被拒绝；技能结果不会被解释成成功，只有 `SkillResult.status == "success"` 才是成功。

## 接模型

最简单的适配器是一个命令：从 stdin 读一行 JSON，从 stdout 只输出一行技能 JSON。

```json
{"name":"collect","args":{"resource":"mcl_core:tree","count":3}}
```

结束时输出：

```json
{"name":"finish","args":{"summary":"目标已完成"}}
```

运行：

```sh
python examples/reference_agent.py \
  "收集三块木头并制作木镐" \
  --planner "python my_planner.py" \
  --max-steps 24
```

`CommandPlanner` 不绑定任何云服务、模型 SDK 或密钥格式；教师可以提供本地模型命令，学生也可以直接传入普通 Python callable。

## 暴露给规划器的数据

- 位置、生命、呼吸、饥饿、燃烧和是否在液体中；
- 有界的非空背包项；
- 有界的可见实体、速度和 hostile/projectile/explosive/attackable 分类；
- 上一步真实技能调用与结果；
- 当前白名单和严格响应结构。

没有隐藏地图、服务器 Lua 状态、矿物坐标或预设钻石路线。导航、下挖、返程和搭桥是可调用的完整能力；何时调用、目标设在哪里、失败后换什么策略仍是学生工作。

## 错误边界

- 非 JSON、额外字段、未知技能、旧实体引用：`PlannerError`；
- 模型进程超时或非零退出：`PlannerError`；
- 技能 blocked/cancelled：原样写入下一轮 `last_result`；
- 到达 `max_steps`：返回 `step_limit`，不偷偷继续。

完整示例在 `examples/reference_agent.py`，核心实现位于 `sdk/src/luanti_course/agent.py`。
