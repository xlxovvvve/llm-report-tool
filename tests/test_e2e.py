"""端到端离线测试：用 mock LLM 跑完整流水线。

目的：让 CI 和任何人都能在没有 API key 的情况下验证整条链路是通的。
Mock 故意包含"编造内容"和"数量缺失"两种异常，用来验证校验器确实能拦住。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_report import LLMClient, LLMConfig, build_batch_prompt, parse_items
from validator import render_review_sheet, validate_batch

STEPS = json.loads(
    (Path(__file__).resolve().parents[1] / "examples" / "steps.json").read_text(
        encoding="utf-8"
    )
)["steps"]


class MockLLM(LLMClient):
    """假 LLM：按步骤数返回内容，其中第 1 条编造原文、第 2 条数字造假。"""

    def __init__(self) -> None:
        super().__init__(LLMConfig(api_key="mock"))

    def complete_json(self, system, user, **kwargs):  # type: ignore[override]
        n = user.count("--- index ")
        items = []
        for i in range(n):
            if i == 1:
                # 编造：source_output 在真实输出里不存在
                items.append(
                    {
                        "index": i,
                        "meaning": "查看头文件内容，确认函数声明写对。",
                        "result": "头文件声明正确。",
                        "source_output": "这是一段并不存在于真实输出中的编造内容",
                    }
                )
            elif i == 2:
                # 数字造假：真实是 7880，这里写 9999
                items.append(
                    {
                        "index": i,
                        "meaning": "编译生成动态库，并查看生成文件的大小与类型。",
                        "result": "libadd.so 编译生成成功，文件大小 9999 字节。",
                        "source_output": "libadd.so 7880 Oct 24 02:11",
                    }
                )
            else:
                items.append(
                    {
                        "index": i,
                        "meaning": "执行本步骤的命令，完成对应的实验操作并观察结果。",
                        "result": "命令执行完成，终端输出如上所示。",
                        "source_output": (STEPS[i]["output"].strip().split("\n")[0])[:40],
                    }
                )
        return {"items": items}


def main() -> int:
    print("=" * 70)
    print("端到端离线测试（mock LLM）")
    print("=" * 70)

    client = MockLLM()
    payload = client.complete_json("system", build_batch_prompt(STEPS))
    items = parse_items(payload, len(STEPS))
    for j, p in enumerate(items):
        p["index"] = STEPS[j]["index"]
    print(f"[1] mock 生成 {len(items)} 条")

    report = validate_batch(items, STEPS)
    print(f"[2] 校验：{report.summary()}")
    for i in report.issues:
        if i.level in ("ERROR", "WARNING"):
            print(f"      {i}")

    sheet = render_review_sheet(items, STEPS, report)
    print(f"[3] 人工终检清单 {len(sheet)} 字符，含勾选项 {sheet.count('- [ ]')} 个")

    # 断言：mock 故意埋的 2 个问题必须被抓到
    codes = {i.code for i in report.issues}
    assert "FABRICATED_SOURCE" in codes, "未抓到编造原文"
    assert "UNVERIFIED_NUMBER" in codes, "未抓到编造数字"
    assert not report.ok, "存在 ERROR 时不应判定为通过"
    print("[4] 断言通过：编造原文与编造数字均被拦截")

    print("\n" + "=" * 70)
    print("端到端测试通过")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
