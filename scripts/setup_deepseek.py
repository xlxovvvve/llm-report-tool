"""DeepSeek 配置助手：交互式写入 .env 并做连通性验证。

用法：
    python scripts/setup_deepseek.py            # 交互式配置
    python scripts/setup_deepseek.py --check    # 只验证现有 .env
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

TEMPLATE = """# DeepSeek 配置（由 scripts/setup_deepseek.py 生成）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY={key}

# 可选调优
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2048
LLM_TIMEOUT=60
LLM_MAX_RETRIES=3
"""


def load_env() -> dict[str, str]:
    """读取 .env（若存在）。"""
    if not ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def save_env(key: str) -> None:
    ENV_FILE.write_text(TEMPLATE.format(key=key), encoding="utf-8")
    # 保证不会被 git 跟踪
    gi = ROOT / ".gitignore"
    if not gi.exists() or ".env" not in gi.read_text(encoding="utf-8"):
        with gi.open("a", encoding="utf-8") as f:
            f.write("\n.env\n")
    print(f"已写入 {ENV_FILE}")


def check() -> int:
    cfg = load_env()
    if not cfg.get("LLM_API_KEY"):
        print("✗ .env 中没有 LLM_API_KEY")
        return 1
    # 注入到环境变量，供 client 读取
    for k, v in cfg.items():
        os.environ[k] = v
    sys.path.insert(0, str(ROOT / "src"))
    from llm_report.cli import check_connection

    return check_connection()


def main() -> int:
    if "--check" in sys.argv:
        return check()

    print("=" * 60)
    print("DeepSeek 配置助手")
    print("=" * 60)
    print()
    print("需要先到 https://platform.deepseek.com/api_keys 创建 API Key")
    print("（新用户通常有免费额度，足够跑完整流程）")
    print()

    key = getpass.getpass("请粘贴 DeepSeek API Key（输入不回显）: ").strip()
    if not key:
        print("未输入 key，已取消")
        return 1
    if not key.startswith("sk-"):
        print("提示：DeepSeek 的 key 通常以 sk- 开头，请确认是否复制完整")

    save_env(key)
    print()
    ok = check()
    if ok != 0:
        return ok
    print()
    print("接下来可以正式跑：")
    print("  python src/llm_report/cli.py --input examples/steps.json --out out/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
