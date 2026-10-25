#!/usr/bin/env python3
"""llm-report-tool 命令行入口。

用法：
  # 生成 + 校验（需要 LLM_API_KEY）
  python -m llm_report.cli --input examples/steps.json --out out/report.md

  # 只做校验（不调 LLM，用已有的生成结果）
  python -m llm_report.cli --input examples/steps.json --items out/items.json --validate-only

  # 跑自检（不需要 API key）
  python -m llm_report.cli --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 允许 `python src/llm_report/cli.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_report import (  # noqa: E402
    BATCH_SYSTEM_PROMPT,
    LLMClient,
    LLMConfig,
    LLMError,
    build_batch_prompt,
    parse_items,
)
from validator import render_review_sheet, validate_batch  # noqa: E402


def load_steps(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("steps", [])
    for i, s in enumerate(data):
        s.setdefault("index", i)
    return data


def save_json(path: str, obj: object) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def render_report(
    items: list[dict],
    steps: list[dict],
    report,
) -> str:
    """把生成结果 + 校验报告渲染成 Markdown 报告。"""
    lines = ["# 实验报告草稿（LLM 生成 + 规则校验）", ""]
    lines.append(f"> 自动校验：{report.summary()}")
    lines.append("> 标记 `!!` 的步骤存在待确认问题，需人工核对原始终端日志。")
    lines.append("")

    for step in steps:
        idx = step.get("index", -1)
        item = items[idx] if 0 <= idx < len(items) else {}
        step_issues = [i for i in report.issues if i.step_index == idx]
        flag = "!!" if step_issues else "OK"
        lines.append(f"## [{flag}] 步骤 {idx + 1}：{step.get('title', '')}")
        lines.append("")
        lines.append("**命令**")
        lines.append("")
        lines.append("```bash")
        lines.append(step.get("command", "").strip())
        lines.append("```")
        lines.append("")
        lines.append(f"**含义**：{item.get('meaning', '')}")
        lines.append("")
        lines.append(f"**结果**：{item.get('result', '')}")
        lines.append("")
        lines.append("**真实输出**")
        lines.append("")
        lines.append("```")
        lines.append(step.get("output", "").strip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def selftest() -> int:
    """自检：验证校验器能识别编造内容，且不需要 API key。"""
    from validator import validate_item

    real_output = "libadd.so 7880 bytes, ELF 64-bit LSB shared object"

    cases = [
        {
            "name": "真实引用（应通过）",
            "item": {
                "meaning": "编译动态库并查看生成的文件属性，确认是可执行文件。",
                "result": "libadd.so 生成成功，大小 7880 字节。",
                "source_output": "libadd.so 7880 bytes",
            },
            "expect_error": False,
        },
        {
            "name": "编造数字（应告警）",
            "item": {
                "meaning": "编译动态库并查看生成的文件属性。",
                "result": "libadd.so 生成成功，大小 9999 字节。",
                "source_output": "libadd.so 7880 bytes",
            },
            "expect_error": False,
            "expect_warning": True,
        },
        {
            "name": "编造原文（应报错）",
            "item": {
                "meaning": "编译动态库并查看生成的文件属性。",
                "result": "编译成功。",
                "source_output": "这段文字根本不在真实输出里出现过",
            },
            "expect_error": True,
        },
        {
            "name": "字段缺失（应报错）",
            "item": {"meaning": "编译动态库。", "result": "", "source_output": "libadd.so"},
            "expect_error": True,
        },
    ]

    all_ok = True
    print("=" * 68)
    print("校验器自检")
    print("=" * 68)
    for case in cases:
        issues = validate_item(case["item"], real_output, step_index=0)
        has_err = any(i.level == "ERROR" for i in issues)
        has_warn = any(i.level == "WARNING" for i in issues)
        ok = has_err == case["expect_error"]
        if case.get("expect_warning"):
            ok = ok and has_warn
        all_ok = all_ok and ok
        print(f"\n[{'PASS' if ok else 'FAIL'}] {case['name']}")
        for i in issues:
            print(f"        {i}")
    print("\n" + "=" * 68)
    print("自检结果：", "全部通过" if all_ok else "存在失败用例")
    print("=" * 68)
    return 0 if all_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="llm-report-tool",
        description="用 LLM 生成实验报告草稿，并用确定性规则校验其真实性",
    )
    ap.add_argument("--input", help="步骤 JSON 文件")
    ap.add_argument("--out", default="out/report.md", help="输出 Markdown 路径")
    ap.add_argument("--items", help="已生成的结果 JSON（配合 --validate-only）")
    ap.add_argument("--validate-only", action="store_true", help="跳过 LLM 调用，只做校验")
    ap.add_argument("--review", default=None, help="人工终检清单输出路径")
    ap.add_argument("--batch-size", type=int, default=5, help="每批送入 LLM 的步骤数")
    ap.add_argument("--selftest", action="store_true", help="运行自检（不需要 API key）")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.input:
        ap.error("需要 --input（或使用 --selftest）")

    steps = load_steps(args.input)
    print(f"[1/4] 读取步骤：{len(steps)} 条")

    # --- 生成 ---
    if args.validate_only:
        if not args.items:
            ap.error("--validate-only 需要配合 --items")
        items = json.loads(Path(args.items).read_text(encoding="utf-8"))
        print(f"[2/4] 载入已有结果：{len(items)} 条（跳过 LLM 调用）")
        llm_meta = None
    else:
        cfg = LLMConfig()
        client = LLMClient(cfg)
        print(f"[2/4] 调用 LLM：{cfg.model} @ {cfg.base_url}")
        items = []
        llm_meta = {"model": cfg.model, "calls": []}
        for start in range(0, len(steps), args.batch_size):
            chunk = steps[start : start + args.batch_size]
            payload = client.complete_json(
                BATCH_SYSTEM_PROMPT, build_batch_prompt(chunk)
            )
            parsed = parse_items(payload, len(chunk))
            for j, p in enumerate(parsed):
                p["index"] = chunk[j]["index"]
            items.extend(parsed)
            print(f"      批次 {start // args.batch_size + 1}: {len(chunk)} 条已生成")
            time.sleep(0.2)

    # --- 校验 ---
    print("[3/4] 规则校验（source_output 逐字比对原始日志）")
    report = validate_batch(items, steps)
    print(f"      {report.summary()}")

    # --- 输出 ---
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(items, steps, report), encoding="utf-8")
    items_path = out_path.with_suffix(".items.json")
    save_json(str(items_path), items)
    if llm_meta is not None:
        save_json(str(out_path.with_suffix(".meta.json")), llm_meta)

    review_path = args.review or str(out_path.with_name(out_path.stem + "_review.md"))
    Path(review_path).write_text(
        render_review_sheet(items, steps, report), encoding="utf-8"
    )
    print(f"[4/4] 输出：\n      {out_path}\n      {items_path}\n      {review_path}")

    if report.errors:
        print(f"\n校验未通过：{len(report.errors)} 条 ERROR，必须修复后才能使用。")
        for e in report.errors[:10]:
            print(f"    {e}")
        return 2
    print("\n校验通过（WARNING 需人工确认）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LLMError as e:
        print(f"LLM 调用失败: {e}", file=sys.stderr)
        sys.exit(1)
