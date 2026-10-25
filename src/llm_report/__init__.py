"""llm-report-tool —— 用 LLM 生成实验报告草稿，并用确定性规则校验其真实性。

定位：**LLM 负责写，规则负责验，人工负责终审。**
"""
from .client import LLMClient, LLMConfig, LLMError, LLMResponse, extract_json
from .prompts import (
    BATCH_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_batch_prompt,
    build_user_prompt,
    parse_items,
)

__version__ = "0.1.0"
__all__ = [
    "BATCH_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "LLMResponse",
    "build_batch_prompt",
    "build_user_prompt",
    "extract_json",
    "parse_items",
]
