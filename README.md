# llm-report-tool

> 用大模型生成实验报告草稿，再用确定性规则校验其真实性。
> **LLM 负责写，规则负责验，人工负责终审。**

一个面向 Linux 上机实验报告的自动化流水线。输入是「命令 + 真实终端输出」，
输出是结构化的报告草稿 + 校验报告 + 人工终检清单。

---

## 为什么要做这个

用大模型写实验报告，最大的风险是**它会把没发生的事写成发生了**——
比如把 `libadd.so` 的大小从 7880 字节写成 9999 字节，
或者编一段看起来很合理但根本不存在的"终端输出"作为依据。

这类错误在人工复核时极难发现，因为**读起来是通顺的**。

本项目的做法是：**让模型必须交出它的证据。**

模型每写一条描述，都必须附一段 `source_output`——从真实终端输出里
**逐字复制**的原文。校验器再做一次机械比对：这段原文在日志里找不到，
就判定为编造，直接拦下。

整个校验层**不调用任何 LLM**，全部是确定性的字符串/数字比对，
所以同一份输入每次跑出的结果完全一致，可复现、可审计。

---

## 核心特性

| 特性 | 说明 |
|---|---|
| **防编造** | `source_output` 必须逐字出现在原始日志中，否则报 `FABRICATED_SOURCE` |
| **数字核验** | 描述中出现的数字必须在原始输出中出现过，否则报 `UNVERIFIED_NUMBER` |
| **数量断言** | 模型返回条数必须与输入步骤数一致，否则报 `COUNT_MISMATCH` |
| **三级问题** | ERROR 阻断 / WARNING 需确认 / INFO 提示 |
| **厂商无关** | 兼容 OpenAI Chat Completions 协议，可切换 OpenAI / DeepSeek / 通义 / 本地 Ollama |
| **零重依赖** | 仅用 Python 标准库（含 urllib），`pip install` 只装开发工具 |
| **可离线自检** | `--selftest` 和端到端测试都不需要 API key |
| **人工终检清单** | 把需要人确认的内容集中成一页带勾选项的 Markdown |

---

## 快速开始

### 1. 环境准备

```bash
git clone <your-repo-url>
cd llm-report-tool

# Python 3.10+
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements-dev.txt
```

### 2. 配置密钥

**最省事的方式**（交互式写入 + 自动验证连通性）：

```bash
python scripts/setup_deepseek.py
```

会提示你粘贴 API Key，写入 `.env`（已被 gitignore 排除，不会误传），然后立刻做一次连通性自检。

**手动配置**：复制 `.env.example` 为 `.env`，填入密钥即可。程序启动时会自动加载 `.env`
（已有环境变量优先，方便临时覆盖）。

```bash
# Linux/macOS
export LLM_API_KEY="sk-..."
export LLM_MODEL="deepseek-chat"
export LLM_BASE_URL="https://api.deepseek.com/v1"

# Windows PowerShell
$env:LLM_API_KEY = "sk-..."
```

**先做连通性自检**（消耗约 10 token，确认配置无误再正式跑）：

```bash
python src/llm_report/cli.py --check
```

```
============================================================
LLM 连通性自检
============================================================
  base_url : https://api.deepseek.com/v1
  model    : deepseek-chat
  api_key  : 已设置 (sk-abc***)

✓ 连接成功
  返回内容   : {"ok": true}
  实际模型   : deepseek-chat
  耗时       : 412 ms
  token 用量 : prompt 18 / completion 6
```

**换厂商只需改两个字段**：

| 厂商 | base_url | model |
|---|---|---|
| DeepSeek（推荐） | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 本地 Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |

> DeepSeek 的 JSON mode 要求 prompt 中必须出现 `json` 字样，否则接口报错。
> 本项目三处 prompt 均已包含，并有回归测试守住这一点（`tests/test_deepseek_compat.py`）。

### 3. 先跑自检（不需要 key）

```bash
python src/llm_report/cli.py --selftest
python tests/test_e2e.py
```

### 4. 正式使用

```bash
python src/llm_report/cli.py \
    --input examples/steps.json \
    --out out/report.md
```

产物：

```
out/report.md            # 报告草稿（含真实输出对照）
out/report.items.json     # 结构化生成结果
out/report_review.md     # 人工终检清单（带勾选项）
```

### 5. 只校验不生成

已有生成结果时，可以跳过 LLM 调用只跑校验：

```bash
python src/llm_report/cli.py \
    --input examples/steps.json \
    --items out/report.items.json \
    --validate-only
```

退出码：`0` = 校验通过；`2` = 存在 ERROR，必须修复。

---

## 输入格式

`examples/steps.json`：

```json
{
  "steps": [
    {
      "index": 0,
      "title": "编译生成动态库 libadd.so",
      "command": "gcc -fPIC -shared -o libadd.so add.c && ls -l libadd.so",
      "output": "-rwxr-xr-x. 1 wht wht 7880 Oct 24 02:11 libadd.so"
    }
  ]
}
```

`output` 必须是**真实终端输出**，这是整个校验体系的地基。

---

## 校验规则

| 代码 | 级别 | 触发条件 |
|---|---|---|
| `FABRICATED_SOURCE` | ERROR | `source_output` 在原始输出中找不到 → 模型编造 |
| `COUNT_MISMATCH` | ERROR | 返回条数 ≠ 输入步骤数 |
| `MISSING_INDEX` | ERROR | 缺少某个 index 的条目 |
| `MISSING_ITEM` | ERROR | 该 index 未被模型返回 |
| `MISSING_FIELD` | ERROR | `meaning` / `result` / `source_output` 有空值 |
| `UNVERIFIED_NUMBER` | WARNING | 描述中的数字在原始输出里不存在 |
| `FILLER_TEXT` | WARNING | 结果是"运行成功"这类无信息量表述 |
| `MEANING_TOO_SHORT` | INFO | 含义描述过短 |
| `RESULT_TOO_SHORT` | INFO | 结果描述过短 |

比对前会做归一化：去空白、统一全半角标点、忽略大小写，
所以跨行、跨格式的引用也能正确匹配。

---

## 项目结构

```
llm-report-tool/
├── src/
│   ├── llm_report/
│   │   ├── client.py       # LLM 客户端：重试、退避、JSON 稳健提取、.env 加载
│   │   ├── prompts.py      # Prompt 模板 + 结构化响应解析
│   │   └── cli.py          # 命令行入口（--selftest / --check / 正式流程）
│   └── validator/
│       └── checker.py      # 确定性校验规则（不依赖 LLM）
├── scripts/
│   └── setup_deepseek.py   # 交互式配置 + 连通性自检
├── examples/
│   └── steps.json          # 示例输入（真实终端输出）
├── tests/
│   ├── test_e2e.py         # 端到端离线测试（mock LLM）
│   └── test_deepseek_compat.py  # DeepSeek 特有场景回归测试
├── docs/
│   └── design.md           # 设计说明
├── .github/workflows/ci.yml
├── requirements-dev.txt
└── README.md
```

---

## 设计取舍

**为什么校验层不调 LLM？**
如果用 LLM 判断"这段描述是否幻觉"，就变成了用不确定的判断去校验不确定的输出。
本项目让校验层是纯规则，同一输入必然同样输出，可复现、可审计。

**为什么强制模型输出 `source_output`？**
把"是否有据"从开放判断变成机械比对。模型可以写得不好，但**不能伪造证据**。

**为什么保留人工终检？**
自动校验只能发现"与日志矛盾"的问题，发现不了"虽然一致但解释得不准确"。
语义正确性仍需人确认。所以流程是三级：**自动校验 → 人工终检 → 定稿**。

**为什么用标准库而不是 requests？**
减少依赖，`git clone` 后即可运行。HTTP 层的重试、退避、错误分类自己实现更可控。

---

## 已知限制

- 校验器只能发现"与日志矛盾"的问题，无法判断解释是否**准确**
- 数字核验会漏掉小于 2 位的数字（如把 "1 个文件" 说成 "2 个文件" 中的 1）
- 依赖模型支持 `response_format: json_object`；不支持时靠 prompt 约束 + 重试兜底
  （DeepSeek 支持，但要求 prompt 中含 `json` 字样——本项目已满足并有测试守住）
- DeepSeek 等推理模型在 `max_tokens` 被 reasoning token 耗尽时会返回**空 content**，
  本项目会明确报错并提示调大 `LLM_MAX_TOKENS`，而不是把它当成正常结果
- 校验的是**引用是否存在**，不校验引用的**片段是否最能支撑结论**

---

## License

MIT
