"""Prompt 模板：把「终端命令 + 真实输出」转成结构化文档片段。

核心约束（这是整个项目的立身之本）：
- LLM 只负责"解释"，不负责"编造"
- 每条输出都必须能在原始日志里找到出处（source_output 必须逐字出现）
- 不确定的宁可留空，也不让模型猜
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- 系统提示
SYSTEM_PROMPT = """你是一个 Linux 实验文档撰写助手，服务于计算机专业学生的上机实验报告。

你的任务：根据给定的「命令」和「真实终端输出」，生成该步骤在实验报告中的结构化描述。

【铁律】
1. 只描述你看到的内容。输出里没出现的信息，一律不要写。
2. `source_output` 字段必须从给定的真实输出中【逐字复制】一段连续的原文，用来证明你的描述有据可依。
3. 术语要平实易懂，面向刚学这门课的学生，避免生僻解释。
4. 不要写"运行成功""一切正常"这类空话，要写清楚具体结果是什么。

【输出格式】严格输出一个 JSON 对象，不要任何解释文字或代码围栏：
{
  "meaning": "这条命令的作用，1-3 句，用平实的话解释",
  "result": "执行结果的实际内容，1-2 句，写清楚具体数字或状态",
  "source_output": "从真实输出中逐字复制的原文片段（20-120 字）"
}
"""


# ---------------------------------------------------------------- 用户提示
def build_user_prompt(
    *,
    command: str,
    output: str,
    context: str = "",
    step_title: str = "",
) -> str:
    """组装单条命令的 user prompt。"""
    parts: list[str] = []
    if step_title:
        parts.append(f"【实验步骤】{step_title}")
    parts.append(f"【执行的命令】\n{command}")
    parts.append(f"【真实终端输出】\n{output.strip()}")
    if context:
        parts.append(f"【补充说明】\n{context}")
    parts.append(
        "请根据以上内容输出 JSON（包含 meaning / result / source_output 三个字段）。"
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 批量提示
BATCH_SYSTEM_PROMPT = """你是一个 Linux 实验文档撰写助手。

你的任务：为一组实验步骤批量生成实验报告中的结构化描述。

【铁律】
1. 只描述你看到的内容，输入里没出现的信息一律不写。
2. 每一条的 `source_output` 必须从对应步骤的真实输出中【逐字复制】。
3. 每条输出的 index 必须与输入的 index 一一对应，不得增删、不得改序。
4. 术语平实易懂，��向初学者。

【输出格式】严格输出一个 JSON 对象：
{
  "items": [
    {"index": 0, "meaning": "...", "result": "...", "source_output": "..."}
  ]
}
items 的数量必须与输入步骤数完全一致。
"""


def build_batch_prompt(steps: list[dict[str, Any]]) -> str:
    """组装批量处理的 user prompt。

    steps: [{"index": int, "title": str, "command": str, "output": str}]
    """
    lines: list[str] = []
    for s in steps:
        lines.append(
            f"--- index {s['index']} ---\n"
            f"标题：{s.get('title', '')}\n"
            f"命令：{s['command']}\n"
            f"输出：\n{s['output'].strip()}"
        )
    lines.append(f"共 {len(steps)} 个步骤，请输出包含 {len(steps)} 条 items 的 JSON。")
    return "\n\n".join(lines)


# ---------------------------------------------------------------- 结构化模型
def parse_items(
    payload: dict[str, Any],
    expected_indices: list[int],
) -> list[dict[str, Any]]:
    """解析批量响应并做基础结构校验。

    这里做**宽松**解析：数量不匹配时按 index 对齐，缺的留空。
    严格的一致性校验交给 validator 模块（那里能拿到原始输出做交叉比对）。

    expected_indices: 本批步骤的**全局** index 列表，如 [5, 6, 7, 8]。

    两种 index 约定都要兼容：
    1. 模型返回全局 index（本项目的 prompt 给的是全局 index，DeepSeek 等
       模型会如实回填）—— 直接按返回值匹配
    2. 模型返回批内序号 0..N-1 —— 按位置回退匹配
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise TypeError(f"响应缺少 items 数组，实际类型：{type(items).__name__}")

    raw_by_index: dict[int, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        raw_by_index[idx] = {
            "meaning": (raw.get("meaning") or "").strip(),
            "result": (raw.get("result") or "").strip(),
            "source_output": (raw.get("source_output") or "").strip(),
        }

    empty = {"meaning": "", "result": "", "source_output": "", "missing": True}
    out: list[dict[str, Any]] = []
    for pos, global_idx in enumerate(expected_indices):
        # 优先按模型返回的 index 精确匹配；匹配不到再按批内序号回退
        item = raw_by_index.get(global_idx)
        if item is None:
            item = raw_by_index.get(pos, dict(empty))
        else:
            item = dict(item)
        item["index"] = global_idx
        out.append(item)
    return out
