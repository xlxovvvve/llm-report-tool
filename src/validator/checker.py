"""校验器：把 LLM 输出和原始终端日志做交叉比对。

这一层是整个项目的核心价值 —— LLM 负责"写"，规则负责"验"。

校验分三级：
  ERROR    —— 阻断性问题，必须修（source_output 在原日志里找不到 = 编造）
  WARNING  —— 需人工确认（描述里出现日志中没有的数字）
  INFO     —— 提示（描述过短等）

设计上刻意**不依赖任何 LLM 判断**，全部是确定性的字符串/数字比对，
保证同一份输入每次跑出来的校验结果完全一致（可复现）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# 归一化：把空白、全角标点统一，便于跨行/跨格式比对
_PUNCT_MAP = {
    "，": ",", "。": ".", "；": ";", "：": ":", "（": "(", "）": ")",
    "、": ",", "！": "!", "？": "?", "“": '"', "”": '"', "‘": "'", "’": "'",
    "－": "-", "—": "-", "–": "-",
}


def normalize(text: str) -> str:
    """归一化文本：去空白、统一标点、小写。"""
    if not text:
        return ""
    out = text.strip()
    for k, v in _PUNCT_MAP.items():
        out = out.replace(k, v)
    out = re.sub(r"\s+", "", out)
    return out.lower()


def extract_numbers(text: str) -> set[str]:
    """抽取文本中的所有数字（保留原始字符串形态）。"""
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


@dataclass
class Issue:
    """单条校验问题。"""

    level: str  # ERROR / WARNING / INFO
    code: str
    message: str
    field: str = ""
    step_index: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "step_index": self.step_index,
        }

    def __str__(self) -> str:
        loc = f"[step {self.step_index}] " if self.step_index >= 0 else ""
        return f"{self.level:7s} {loc}{self.code}: {self.message}"


@dataclass
class ValidationReport:
    """一份校验报告。"""

    issues: list[Issue] = field(default_factory=list)
    checked_steps: int = 0
    passed_steps: int = 0

    def add(self, level: str, code: str, message: str, field: str = "", step_index: int = -1) -> None:
        self.issues.append(Issue(level, code, message, field, step_index))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "WARNING"]

    @property
    def ok(self) -> bool:
        """无 ERROR 即视为通过（WARNING 需要人工确认但不阻断）。"""
        return not self.errors

    def summary(self) -> str:
        return (
            f"检查 {self.checked_steps} 个步骤，"
            f"通过 {self.passed_steps} 个，"
            f"ERROR {len(self.errors)} 条，WARNING {len(self.warnings)} 条"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_steps": self.checked_steps,
            "passed_steps": self.passed_steps,
            "summary": self.summary(),
            "issues": [i.to_dict() for i in self.issues],
        }


# ------------------------------------------------------------------ 单步校验
def validate_item(
    item: dict[str, Any],
    original_output: str,
    *,
    step_index: int = -1,
    min_meaning_len: int = 20,
    min_result_len: int = 10,
) -> list[Issue]:
    """校验单条 LLM 输出与原始输出的对应关系。"""
    issues: list[Issue] = []
    meaning = (item.get("meaning") or "").strip()
    result = (item.get("result") or "").strip()
    source = (item.get("source_output") or "").strip()
    out_norm = normalize(original_output)

    # 1) 字段缺失
    for fname, val in (("meaning", meaning), ("result", result), ("source_output", source)):
        if not val:
            issues.append(
                Issue("ERROR", "MISSING_FIELD", f"字段 {fname} 为空", fname, step_index)
            )
    if issues:
        return issues

    # 2) 核心：source_output 必须在原始输出里逐字出现（防编造）
    if normalize(source) not in out_norm:
        issues.append(
            Issue(
                "ERROR",
                "FABRICATED_SOURCE",
                f"source_output 在真实输出中不存在，疑似编造：{source[:60]!r}",
                "source_output",
                step_index,
            )
        )

    # 3) 描述里出现的数字，必须在原始输出里出现过（防止凭空造数据）
    desc_numbers = extract_numbers(meaning) | extract_numbers(result)
    out_numbers = extract_numbers(original_output)
    # 忽略常见的非事实数字（如"1.3"版本号、"2"表示两个），只报明显对不上的
    bogus = {n for n in desc_numbers - out_numbers if len(n) >= 2}
    if bogus:
        issues.append(
            Issue(
                "WARNING",
                "UNVERIFIED_NUMBER",
                f"描述中出现原始输出里没有的数字：{sorted(bogus)[:5]}",
                "meaning/result",
                step_index,
            )
        )

    # 4) 长度合理性
    if len(meaning) < min_meaning_len:
        issues.append(
            Issue("INFO", "MEANING_TOO_SHORT", f"含义描述过短（{len(meaning)} 字）", "meaning", step_index)
        )
    if len(result) < min_result_len:
        issues.append(
            Issue("INFO", "RESULT_TOO_SHORT", f"结果描述过短（{len(result)} 字）", "result", step_index)
        )

    # 5) 空话检测 —— 常见的无信息量表述
    for filler in ("运行成功", "一切正常", "操作成功", "没有问题", "执行完毕"):
        if filler in result and len(result) <= len(filler) + 8:
            issues.append(
                Issue("WARNING", "FILLER_TEXT", f"结果描述疑似空话：{filler!r}", "result", step_index)
            )
            break

    return issues


# ------------------------------------------------------------------ 批量校验
def validate_batch(
    items: Iterable[dict[str, Any]],
    steps: list[dict[str, Any]],
    **kwargs: Any,
) -> ValidationReport:
    """批量校验。

    items: LLM 生成的条目列表
    steps: 原始步骤 [{"index", "title", "command", "output"}]
    """
    report = ValidationReport()
    items = list(items)
    steps = list(steps)
    report.checked_steps = len(steps)

    # 数量一致性 —— 这是整个流水线的核心断言
    if len(items) != len(steps):
        report.add(
            "ERROR",
            "COUNT_MISMATCH",
            f"LLM 返回 {len(items)} 条，期望 {len(steps)} 条",
        )

    by_index = {i: it for i, it in enumerate(items)}

    for step in steps:
        idx = step.get("index", -1)
        item = by_index.get(idx)
        if item is None:
            report.add("ERROR", "MISSING_INDEX", f"缺少 index={idx} 的条目", step_index=idx)
            continue
        if item.get("missing"):
            report.add("ERROR", "MISSING_ITEM", f"index={idx} 未被模型返回", step_index=idx)
            continue

        before = len(report.errors)
        for iss in validate_item(item, step.get("output", ""), step_index=idx, **kwargs):
            report.issues.append(iss)
        if len(report.errors) == before:
            report.passed_steps += 1

    return report


# ------------------------------------------------------------------ 人工终检
def render_review_sheet(
    items: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    report: ValidationReport,
) -> str:
    """生成人工终检清单（Markdown）。

    设计意图：把「需要人来看的部分」集中到一页，人只需要勾选，不用通读全文。
    """
    lines = ["# 人工终检清单", ""]
    lines.append(f"自动校验：{report.summary()}")
    lines.append("")
    lines.append("> 自动校验只做机械比对，语义是否准确仍需人工确认。")
    lines.append("")

    for step in steps:
        idx = step.get("index", -1)
        item = items[idx] if 0 <= idx < len(items) else {}
        step_issues = [i for i in report.issues if i.step_index == idx]
        flag = "OK " if not step_issues else "!! "
        lines.append(f"## {flag} 步骤 {idx + 1}：{step.get('title', '')}")
        lines.append("")
        lines.append(f"- **命令**：`{step.get('command', '').strip()}`")
        lines.append(f"- **含义**：{item.get('meaning', '')}")
        lines.append(f"- **结果**：{item.get('result', '')}")
        lines.append(f"- **原文依据**：`{item.get('source_output', '')}`")
        if step_issues:
            lines.append("- **待确认**：")
            for iss in step_issues:
                lines.append(f"    - [{iss.level}] {iss.code} — {iss.message}")
        lines.append("- [ ] 描述与真实输出相符")
        lines.append("- [ ] 术语表述准确、无臆造")
        lines.append("")
    return "\n".join(lines)
