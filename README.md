# 百炼模型请求限制实测工具

对阿里云百炼**工作空间域名**（`{WorkspaceId}.{region}.maas.aliyuncs.com`）下的三条兼容路径
做请求边界实测，输出可复现的 Markdown 报告、原始数据与一键 curl 脚本。

- OpenAI Chat：`/compatible-mode/v1/chat/completions`
- OpenAI Responses：`/compatible-mode/v1/responses`
- Anthropic 兼容：`/apps/anthropic/v1/messages`

默认模型为 `qwen3.8-flash`，可通过环境变量切换（见「换模型」）。

第一次接手、只想照着做一遍，直接看 **[HANDOFF.md](HANDOFF.md)**——那是一份可以单独转发的操作手册。

## 跨平台

核心工具是纯 Python，macOS、Linux、Windows 都能跑：

- Windows 用 `python`（或 `py -3`），不要用 `python3`；环境变量用 `set`（cmd）或 `$env:`（PowerShell）。
- 输出已强制 UTF-8，Windows 旧终端若仍乱码，先执行 `chcp 65001`。
- 失败用例提供两种复现脚本：`results/curl/*.sh`（curl）与 `*.cmd`（Windows，内部走 `--replay`）。
- 不想用 curl 也行：`python run_tests.py --replay text_en_openai@4.4` 直接重放。

## 能测什么

| 维度 | 说明 |
|---|---|
| 文本上限 | 英文 / 中文各自在多少 MB 触发拒绝；错误信息会回显精确的 token 上限 |
| 单图体积 | 用不可压缩的随机像素图，测「原始文件」与「Base64 后 Data URI」两条限制谁先触发 |
| 请求体上限 | 用低像素大文件把请求体顶到目标体积，看是 413、断连还是照常接受 |
| 图片张数 | Base64 多图的上限（典型值 250） |
| 格式 / 分辨率 | BMP、JPEG、PNG、TIFF、WEBP；4K–8K 档位的格式限制；8K 图像的 token 截断 |
| 尺寸 / 宽高比 | 最小边长、200:1 宽高比 |
| 异常输入 | 空图、坏图、media_type 与真实格式不符 |
| 错误码 | 模型不存在、消息结构非法、超出上下文等场景的 HTTP 状态与 `code` |
| 静默截断 | Responses 超长时是否悄悄丢数据（用「预期 tokens vs 上报 tokens」判定） |

**不测**：公网 URL / 本地路径传图（需要可访问的图床）、视频输入、HEIC（无编码器）、
RPM/TPM 限流、思考模式下的独立上限。

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # 只需要 Pillow

export DASHSCOPE_API_KEY='sk-...'
export DASHSCOPE_WORKSPACE_ID='ws-...'

python3 run_tests.py --list              # 看有哪些实验与探测点
python3 run_tests.py --dry-run           # 只构建载荷，不发请求、不花钱
python3 verify_boundaries.py --model qwen3.8-max --out results-verify-qwen3.8-max
                                          # 换新模型默认走这个：22 点快速核对
python3 run_tests.py --suite text        # 只跑文本边界
python3 run_tests.py --suite all         # 全量（仅客户明确要求时）
```

全量成本参考：`qwen3.8-flash` 约 12 元（含 128 MiB 请求体与百万 token 级文本探测）。
只想看结论可以先跑 `text` + `image-format`，约 1 元。

## 环境变量

### 必需

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 工作空间 API Key（`sk-ws-` 开头） |
| `DASHSCOPE_WORKSPACE_ID` | 工作空间 ID，用于拼出专属域名 |

### 连接与模型

| 变量 | 默认 | 说明 |
|---|---|---|
| `DASHSCOPE_REGION` | `cn-beijing` | 地域 |
| `DASHSCOPE_MODEL` | `qwen3.8-flash` | 被测模型 ID |
| `BAILIAN_TIMEOUT_S` | `600` | 单请求超时；大体积用例需要留足 |
| `BAILIAN_REQUEST_INTERVAL_S` | `1.0` | 请求间隔，避免触发限流 |

### 文档限值（换模型时按模型详情页填）

这些值只用于**对比与展示**，不改变探测逻辑；默认值对应 `qwen3.8-flash`。

| 变量 | 默认 |
|---|---|
| `BAILIAN_MAX_INPUT_TOKENS` | `991808` |
| `BAILIAN_MAX_OUTPUT_TOKENS` | `131072` |
| `BAILIAN_CONTEXT_TOKENS` | `1000000` |
| `BAILIAN_IMAGE_MB` | `20` |
| `BAILIAN_DATA_URI_MB_OPENAI` | `20` |
| `BAILIAN_DATA_URI_MB_ANTHROPIC` | `32` |
| `BAILIAN_BODY_MB` | `64` |
| `BAILIAN_IMAGES_BASE64_MAX` | `250` |
| `BAILIAN_PRICE_INPUT` | `0.8` |
| `BAILIAN_PRICE_CACHE_HIT` | `0.1` |
| `BAILIAN_PRICE_OUTPUT` | `2.7` |

后三项只影响报告里的成本估算。max 系列的报价是 flash 的十几倍（如 `qwen3.8-max` 12 / 1.5 / 36，
`qwen4-max` 10 / 0.5 / 30），换模型时不改会严重低估费用。

### 探测点（一般不用改）

| 变量 | 说明 |
|---|---|
| `BAILIAN_TEXT_POINTS_MB` | 英文本探测点，逗号分隔且递增，如 `1,4,8,12,16` |
| `BAILIAN_IMAGE_POINTS_MB` | 单图探测点（对所有协议生效），如 `5,9,11` |

中文探测点会按 `BAILIAN_MAX_INPUT_TOKENS / 991808` 自动等比缩放，无需单独设置。

## 换模型

以 `qwen3.8-max`、`qwen4-max` 为例：

```bash
export DASHSCOPE_MODEL=qwen3.8-max
export BAILIAN_MAX_INPUT_TOKENS=<模型详情页的「最大输入」>
export BAILIAN_MAX_OUTPUT_TOKENS=<模型详情页的「最大输出」>
python3 run_tests.py --suite all --out results-qwen38-max
```

要点：

1. **上下文与最大输出必须手动传入。** 本工具不内置各模型的数值，避免拿 A 模型的文档去评判 B 模型；
   这两个值会出现在报告的「文档值」列与 `max_tokens` 越界用例里。
2. **文本探测点会自动缩放。** 默认布点按 991,808 tokens 设计；若模型是 256K 上下文，
   探测点会自动降到约 1/4，无需改代码。上下文显著更大（如 2M）时，建议用
   `BAILIAN_TEXT_POINTS_MB=1,4,8,12,16` 显式上探。
3. **图片档位按文档传入。** 视觉文档把 `Qwen4-Max`、`Qwen3.8 系列` 归入单图 20 MB 档，
   Base64 张数上限 250、URL 传入 2048；其他系列可能是 10 MB 档。
   若模型是 10 MB 档，单图探测点默认已包含 9.9 MB 的低位点，可以直接测出边界。
4. **不同模型的结果不能混用。** 每次运行用 `--out results-<model>` 分目录存放，
   报告里的端点、模型、时间戳都是当次运行的事实。
5. **默认先做基线核对，不要直接全量。** 新模型先跑 `verify_boundaries.py`（22 点、6–7 分钟），
   全过即可复用基线结论；只有客户明确要求全量时才跑 `--suite all`。规则详见 `AGENTS.md`。

同一份文档，同一个模型，三条路径的校验项集合并不同；跨模型更不应套用结论。

## 产物

| 路径 | 内容 |
|---|---|
| `results/report.md` | 分析报告：结论、逐项明细、错误码字典、文档对照、工程建议 |
| `results/results.json` | 全部记录 + 各维度边界结论 + 成本估算 |
| `results/records.jsonl` | 逐请求流水，支持断点续跑 |
| `results/curl/*.sh` | 失败用例复现脚本（curl），同名 `.cmd` 供 Windows 使用 |

`report.md` 的章节按数据动态生成：只跑部分套件时，空章节会自动省略，编号连续。

## 运行控制

```bash
python3 run_tests.py --suite text --protocol responses   # 只跑某条路径
python3 run_tests.py --only body_size_openai             # 只补测一个实验（替换其历史记录）
python3 run_tests.py --protocol anthropic --force        # 整条路径重跑并替换
python3 run_tests.py --resume                            # 跳过已完成实验
python3 run_tests.py --report-only                       # 由 results.json 重出报告
python3 run_tests.py --dump-body text_en_openai@4.4 --out /tmp/body.json
python3 run_tests.py --replay text_en_openai@4.4      # 直接重放，不依赖 curl
```

两个模型的边界完全一致时，可以合并成一份对照报告：

```bash
python3 merge_models.py --a results-qwen38-max --b results-qwen4-max --out results-merged
```

边界不一致时脚本会拒绝合并并列出差异，保留两份独立报告。

## 代码结构

```
run_tests.py                 CLI 入口
limits/
  config.py                  环境变量、文档限值（可覆盖）、单价
  protocols.py               三条路径的载荷/usage/错误解析策略
  transport.py               HTTP、重试、错误归一化、抖动识别
  fixtures.py                确定性测试数据（精确尺寸 PNG、随机像素图、中英文文本）
  base.py                    实验框架：单请求、边界搜索、上下文
  wire.py                    JSON 编码与载荷指标
  experiments/               每个 suite 一个模块，声明式定义探测点
  runner.py                  编排、进度、增量落盘
  report.py                  Markdown 报告
  curlgen.py                 失败用例复现脚本
  persist.py                 结果反序列化
tests/                       39 个离线单测，不触网
```

## 设计要点

1. **体积与 token 成本解耦。** 图像 token 由像素决定，请求体由字节决定。测试图分两类：
   64×64 像素 + 大 `tEXt` 块（成本近零，探传输上限）、不可压缩随机像素（体积≈真实像素数据，
   验证限制是否作用在图像内容上）。
2. **阶梯 + 二分。** 命中首个失败点后在上一个通过点之间二分，报告给出区间 `[最大通过, 首个拒绝)`。
3. **失败分类。** 4xx 业务拒绝计入边界；超时、429、5xx、以及带 `timed out` 的 400 视为抖动，
   重试两次后仍失败则中止该维度并标注，不把网络问题误判成平台限制。

## 已知限制

- 边界是区间而非精确值，受 tokenizer 分段与网关实现影响，可能抖动几 KB。
- Anthropic 的 `input_tokens` 只含非缓存部分，总输入需加 `cache_creation_input_tokens` 与
  `cache_read_input_tokens`；工具内部已归一化，直接看 `usage.input_tokens` 即可。
- Responses 路径超长时可能**静默截断**而非报错，报告会用「预期 vs 上报 tokens」标出来。

## 样例结果（`qwen3.8-flash`，2026-11-23，162 次请求）

| 维度 | 文档 | OpenAI Chat | OpenAI Responses | Anthropic 兼容 |
|---|---|---|---|---|
| 最大输入 | 991,808 | 4.4 MB 英文被拒 | **3.43 MB 起静默截断** | 4.4 MB 英文被拒 |
| 单图原图 | 20 MB | 39,321,582 B | 同左 | ≈24 MB |
| 单图 Data URI | 20 / 32 MB | 50 MiB | 50 MiB | 32 MiB |
| 请求体 | 64 MB | 128 MiB | 128 MiB | 62.5–65 MB 间断连 |
| Base64 张数 | 250 | 250 / 251 精确 | 同左 | 同左 |

完整分析见 `results/report.md`。这组数据仅代表 `qwen3.8-flash` 在该工作空间的表现，
换模型请重新实测。
