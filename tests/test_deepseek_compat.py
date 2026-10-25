"""DeepSeek 特有场景的回归测试。

覆盖三个真实踩过的坑：
1. reasoning token 耗尽 → 返回空 content（finish_reason=length）
2. JSON mode 要求 prompt 含 "json" 字样
3. .env 自动加载且不覆盖已有环境变量
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_report import BATCH_SYSTEM_PROMPT, SYSTEM_PROMPT, build_batch_prompt
from llm_report.client import LLMClient, LLMConfig, LLMError, load_dotenv


class EmptyContentClient(LLMClient):
    """模拟 DeepSeek 在 max_tokens 被 reasoning token 耗尽时的行为。"""

    def __init__(self) -> None:
        super().__init__(LLMConfig(api_key="mock"))

    def _post(self, payload):  # type: ignore[override]
        return {
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {"content": "", "reasoning_content": "思考中..."},
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 0},
        }


def test_empty_content_detected():
    """空 content 必须被识别为错误，而不是当成正常结果往下走。"""
    client = EmptyContentClient()
    client.config.max_retries = 2
    try:
        client.complete("sys", "user")
    except LLMError as e:
        assert "空内容" in str(e), f"错误信息应说明是空内容，实际：{e}"
        print("[PASS] 空 content 被正确识别并提示 max_tokens 问题")
        return
    raise AssertionError("应当抛出 LLMError")


def test_prompt_contains_json():
    """DeepSeek 的 JSON mode 要求 prompt 中出现 'json'，否则接口报错。"""
    assert "json" in SYSTEM_PROMPT.lower(), "SYSTEM_PROMPT 必须含 json"
    assert "json" in BATCH_SYSTEM_PROMPT.lower(), "BATCH_SYSTEM_PROMPT 必须含 json"
    user = build_batch_prompt(
        [{"index": 0, "title": "t", "command": "c", "output": "o"}]
    )
    assert "json" in user.lower(), "user prompt 必须含 json"
    print("[PASS] 三处 prompt 均含 json 字样（满足 DeepSeek JSON mode 要求）")


def test_dotenv_loading():
    """load_dotenv 能读到 .env，且不覆盖已有环境变量。"""
    with tempfile.TemporaryDirectory() as td:
        env = Path(td) / ".env"
        env.write_text(
            "# 注释行\nLLM_MODEL=deepseek-chat\nLLM_API_KEY=sk-test-123\n\nBROKEN_LINE\n",
            encoding="utf-8",
        )
        os.environ["LLM_MODEL"] = "preset-model"
        try:
            loaded = load_dotenv(env)
            assert loaded["LLM_MODEL"] == "deepseek-chat", "应从文件读到值"
            assert loaded["LLM_API_KEY"] == "sk-test-123", "应读到 key"
            assert os.environ["LLM_MODEL"] == "preset-model", "已有环境变量不应被覆盖"
            assert "BROKEN_LINE" not in loaded, "无 = 的行应被跳过"
            print("[PASS] .env 加载正确，且不覆盖已有环境变量")
        finally:
            os.environ.pop("LLM_MODEL", None)
            os.environ.pop("LLM_API_KEY", None)


def test_config_priority():
    """显式传参 > 环境变量。"""
    cfg = LLMConfig(model="explicit", api_key="sk-x")
    assert cfg.model == "explicit"
    assert cfg.api_key == "sk-x"
    print("[PASS] 显式传参优先级最高")


def main() -> int:
    print("=" * 66)
    print("DeepSeek 兼容性测试")
    print("=" * 66)
    tests = [
        test_empty_content_detected,
        test_prompt_contains_json,
        test_dotenv_loading,
        test_config_priority,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
    print("=" * 66)
    print("全部通过" if failed == 0 else f"{failed} 个用例失败")
    print("=" * 66)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
