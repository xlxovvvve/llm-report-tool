"""LLM 客户端：兼容 OpenAI Chat Completions 协议。

设计要点：
1. 不绑定厂商 —— 通过 base_url 切换 OpenAI / DeepSeek / 通义 / 本地 Ollama
2. 强制 JSON 输出 —— 用 response_format 或在 prompt 里约束，降低解析失败率
3. 失败可重试 —— 网络抖动、限流、JSON 解析失败都重试，且退避
4. 密钥优先从环境变量读；也支持从项目根目录的 .env 读取（该文件已被 gitignore 排除）
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_dotenv(path: str | Path | None = None) -> dict[str, str]:
    """从 .env 文件加载环境变量（已存在的环境变量优先，不覆盖）。

    不依赖 python-dotenv，保持零第三方依赖。
    返回实际加载的键值对。
    """
    if path is None:
        # 从 src/llm_report/client.py 往上找三层就是项目根
        path = Path(__file__).resolve().parents[2] / ".env"
    p = Path(path)
    if not p.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        loaded[k] = v
        # 已有环境变量优先（方便临时覆盖）
        os.environ.setdefault(k, v)
    return loaded


class LLMError(RuntimeError):
    """LLM 调用失败（已重试耗尽）。"""


@dataclass(init=False)
class LLMConfig:
    """模型配置。

    优先级：已存在的环境变量 > 项目根目录 .env > 内置默认值。
    也支持直接传参覆盖（用于测试）。
    """

    model: str
    base_url: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout: int
    max_retries: int

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        # 先加载 .env（不覆盖已有环境变量），再决定各字段取值
        load_dotenv()
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        self.temperature = (
            temperature
            if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", "0.2"))
        )
        self.max_tokens = (
            max_tokens if max_tokens is not None else int(os.getenv("LLM_MAX_TOKENS", "2048"))
        )
        self.timeout = timeout if timeout is not None else int(os.getenv("LLM_TIMEOUT", "60"))
        self.max_retries = (
            max_retries if max_retries is not None else int(os.getenv("LLM_MAX_RETRIES", "3"))
        )

    def validate(self) -> None:
        if not self.api_key:
            raise LLMError(
                "未配置 LLM_API_KEY。请设置环境变量 LLM_API_KEY，"
                "或在项目根目录的 .env 中写入（可运行 scripts/setup_deepseek.py 生成）。"
            )


@dataclass
class LLMResponse:
    """一次调用的完整结果，用于审计与追溯。"""

    content: str
    model: str
    raw: dict[str, Any]
    attempts: int
    latency_ms: int
    prompt_chars: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "attempts": self.attempts,
            "latency_ms": self.latency_ms,
            "prompt_chars": self.prompt_chars,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


class LLMClient:
    """极简 Chat Completions 客户端，只依赖标准库。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()

    # ---------- 底层 ----------
    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "User-Agent": "llm-report-tool/0.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ---------- 对外 ----------
    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = True,
        temperature: float | None = None,
    ) -> LLMResponse:
        """发起一次对话补全，返回原始文本。

        json_mode=True 时请求模型输出 JSON（部分厂商需额外支持）。
        """
        self.config.validate()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            started = time.time()
            try:
                raw = self._post(payload)
                content = raw["choices"][0]["message"]["content"]
                # DeepSeek 等厂商在 reasoning token 耗尽时会返回空 content，
                # 此时不能当成正常结果，否则后面 JSON 解析会莫名失败。
                if not content or not content.strip():
                    finish = raw["choices"][0].get("finish_reason")
                    raise LLMError(
                        f"模型返回空内容（finish_reason={finish}），"
                        f"可能是 max_tokens 被 reasoning token 耗尽，"
                        f"请调大 LLM_MAX_TOKENS"
                    )
                usage = raw.get("usage") or {}
                return LLMResponse(
                    content=content,
                    model=raw.get("model", self.config.model),
                    raw=raw,
                    attempts=attempt,
                    latency_ms=int((time.time() - started) * 1000),
                    prompt_chars=len(system) + len(user),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:300]
                last_err = LLMError(f"HTTP {e.code}: {body}")
                # 4xx（除 429）是请求本身的问题，重试无意义
                if e.code != 429 and 400 <= e.code < 500:
                    raise last_err from e
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError) as e:
                last_err = LLMError(f"{type(e).__name__}: {e}")
            except json.JSONDecodeError as e:
                last_err = LLMError(f"响应不是合法 JSON: {e}")

            if attempt < self.config.max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))

        raise LLMError(f"调用失败（已重试 {self.config.max_retries} 次）: {last_err}")

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """要求模型返回 JSON 并解析。

        模型有时会在 JSON 前后加解释文字或代码围栏，这里做容错提取。
        """
        err: Exception | None = None
        for i in range(max_attempts):
            resp = self.complete(
                system,
                user,
                json_mode=True,
                temperature=0.0 if i > 0 else temperature,
            )
            try:
                return extract_json(resp.content)
            except ValueError as e:
                err = e
                # 追加一条纠正指令重试
                user = user + "\n\n[纠正] 上次输出不是合法 JSON，请只输出 JSON 对象本身，不要任何解释或代码围栏。"
        raise LLMError(f"模型输出无法解析为 JSON（重试 {max_attempts} 次）: {err}")


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里稳健地提取 JSON 对象。

    依次尝试：直接解析 -> 去代码围栏 -> 提取首个平衡的 {...}。
    """
    text = text.strip()
    if not text:
        raise ValueError("空响应")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 去 ```json ... ``` 围栏
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") and part.endswith("}"):
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue

    # 扫描第一个平衡的 {...}
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"未找到合法 JSON: {text[:120]!r}")
