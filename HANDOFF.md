# 百炼模型请求限制实测 · 交接说明

这份文档是给**执行测试的人**的独立操作手册，不需要看别的文件。按顺序做完即可拿到报告。

你要做的事：用你自己的百炼工作空间凭证，对指定模型跑一遍请求边界实测，得到一份可复现的
分析报告。工具已经写好在压缩包里，你只负责配置和运行。

---

## 0. 你需要准备

| 项目 | 要求 |
|---|---|
| Python | 3.10 或更高（`python --version` 确认） |
| 依赖 | Pillow（一条 `pip install` 解决） |
| 凭证 | 百炼**工作空间**的 `API Key` 与 `Workspace ID` |
| 网络 | 能访问 `*.maas.aliyuncs.com` |
| 磁盘 | 约 50 MB（测试图在内存生成，不落盘；结果很小） |

> 必须是**工作空间专属域名**的凭证（`sk-ws-` 开头的 Key、`ws-` 开头的 Workspace ID）。
> 公共 DashScope 域名的 Key 走不通这套端点。

## 1. 解压与安装（Windows）

```bat
:: 解压后进入目录
cd bailian-vision-limits

:: 建虚拟环境（可选但推荐）
python -m venv .venv
.venv\Scripts\activate

:: 安装依赖
pip install -r requirements.txt
```

## 1'. 解压与安装（macOS / Linux）

```bash
cd bailian-vision-limits
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> 没有 Pillow 时工具会直接提示安装命令，不会抛一堆 traceback。

## 2. 配置环境变量

### Windows PowerShell

```powershell
$env:DASHSCOPE_API_KEY="sk-ws-..."
$env:DASHSCOPE_WORKSPACE_ID="ws-..."
$env:DASHSCOPE_MODEL="qwen3.8-max"
$env:BAILIAN_MAX_INPUT_TOKENS="<模型详情页的最大输入>"
$env:BAILIAN_MAX_OUTPUT_TOKENS="<模型详情页的最大输出>"
```

### Windows cmd

```bat
set DASHSCOPE_API_KEY=sk-ws-...
set DASHSCOPE_WORKSPACE_ID=ws-...
set DASHSCOPE_MODEL=qwen3.8-max
set BAILIAN_MAX_INPUT_TOKENS=<最大输入>
set BAILIAN_MAX_OUTPUT_TOKENS=<最大输出>
```

### macOS / Linux

```bash
export DASHSCOPE_API_KEY='sk-ws-...'
export DASHSCOPE_WORKSPACE_ID='ws-...'
export DASHSCOPE_MODEL='qwen3.8-max'
export BAILIAN_MAX_INPUT_TOKENS='<最大输入>'
export BAILIAN_MAX_OUTPUT_TOKENS='<最大输出>'
```

**为什么一定要设后两个？** 工具不内置各模型的上下文与最大输出，避免拿 A 模型的文档去评判
B 模型。这两个值决定文本探测点的位置，也决定报告「文档值」那一列。数值从百炼控制台的
模型详情页抄即可。

## 3. 先自检，别急着花钱

```bash
python run_tests.py --list          # 列出所有实验与探测点（不联网）
python run_tests.py --dry-run       # 构建全部载荷并打印体积（不联网、不花钱）
```

`--dry-run` 最后会打印「共 N 个实验，最多 M 次请求」。如果这一步报 Pillow 缺失，回到第 1 步。

## 4. 开跑

**默认走快速核对**：拿已知的 flash 边界逐点复验，拒绝类请求不计费。

```bash
python verify_boundaries.py --model qwen3.8-max --out results-verify-qwen3.8-max
```

跑完看 `verify.md`：22 个点位全过，就说明该模型在本轮核对范围内与 flash 一致，
可以直接引用 `docs/limits-summary.md` 的结论，**不需要再跑全量**。

只有**客户明确要求「全量 / 完整阶梯」**时才执行下面这条：

```bash
python run_tests.py --suite all --out results-qwen38-max
```

全量会重跑 91 个实验、30–40 分钟；高价模型（max 系列）成本可达 80–100 元，
跑之前先和客户确认。

Windows 下把 `python` 换成 `py -3` 也可以；**不要**用 `python3`（Windows 通常没有这个别名）。

`--out` 一定要带模型名。不同模型的结果分目录存放，互不覆盖。

中断了可以续跑（两种模式都支持）：

```bash
python verify_boundaries.py --model qwen3.8-max --out results-verify-qwen3.8-max
python run_tests.py --suite all --out results-qwen38-max --resume
```

## 5. 看结果

跑完会打印报告路径。核心看三个文件：

| 文件 | 用途 |
|---|---|
| `results-qwen38-max/report.md` | **主报告**，先看「结论摘要」和「与官方文档的对照」 |
| `results-qwen38-max/results.json` | 全部原始记录与边界结论，做二次分析用 |
| `results-qwen38-max/curl/` | 每个失败用例的复现脚本 |

报告章节含义：

- **结论摘要**：四条核心边界一张表看完
- **纯文本请求**：英文 / 中文各自的边界，含每条请求的 token 数
- **静默截断**（若有）：服务端不报错但丢数据的情况，**这是最需要警惕的**
- **单张图片体积**：原始体积与 Base64 后体积谁是瓶颈
- **请求体整体上限 / 图片张数**：传输层与张数限制
- **格式、分辨率与宽高比**：哪些文档规则实际没生效
- **错误码字典**：按 `code` 挂分支用
- **与官方文档的对照**：逐条给「一致 / 未执行 / 不一致」

## 6. 复现单个失败用例

每个失败用例都有两份脚本：

- **Windows**：`results-qwen38-max\curl\xxx.cmd`，双击或在 cmd 里执行
- **macOS / Linux**：`bash results-qwen38-max/curl/xxx.sh`（用 curl）

两者重放的是完全相同的请求体。也可以手动：

```bash
python run_tests.py --replay text_en_openai@4.4
```

## 7. 换模型时要改什么

以 `qwen3.8-max`、`qwen4-max` 为例，最少改三样：

| 变量 | 填什么 |
|---|---|
| `DASHSCOPE_MODEL` | 模型 ID，如 `qwen3.8-max` |
| `BAILIAN_MAX_INPUT_TOKENS` | 模型详情页的「最大输入」 |
| `BAILIAN_MAX_OUTPUT_TOKENS` | 模型详情页的「最大输出」 |

可选项（不确定就别设，用默认）：

| 变量 | 何时需要 |
|---|---|
| `BAILIAN_TEXT_POINTS_MB=1,4,8,12,16` | 上下文远大于 1M，默认布点探不到顶 |
| `BAILIAN_IMAGE_POINTS_MB=5,9,11` | 模型是 10 MB 档或更小，需要自定义单图点位 |
| `BAILIAN_IMAGE_MB` / `BAILIAN_DATA_URI_MB_OPENAI` / `BAILIAN_DATA_URI_MB_ANTHROPIC` | 文档值与本工具默认值不同 |
| `BAILIAN_TIMEOUT_S` | 网络慢，大体积用例频繁超时（默认 600 秒） |
| `BAILIAN_REQUEST_INTERVAL_S` | 触发限流时调大（默认 1 秒） |
| `BAILIAN_PRICE_INPUT` / `BAILIAN_PRICE_CACHE_HIT` / `BAILIAN_PRICE_OUTPUT` | 报告里的成本估算；max 系列约为 10–12 / 0.5–1.5 / 30–36 元每百万，不改会严重低估 |

文本探测点会按 `BAILIAN_MAX_INPUT_TOKENS / 991808` 自动缩放，256K 上下文的模型无需改点。

## 8. 能测什么、测不了什么

**能测**：三条兼容路径（Chat / Responses / Anthropic）下的文本体积边界、单图体积
（原始 vs Base64）、请求体整体上限、Base64 张数、格式（BMP/JPEG/PNG/TIFF/WEBP）、
4K–8K 格式档、最小边长、宽高比、异常输入（空图/坏图/声明格式不符）、错误码、
以及 Responses 的超长静默截断。

**测不了**：公网 URL 或本地路径传图（需要一个可公网访问的图床）、视频输入、
HEIC（环境缺编码器）、RPM/TPM 限流、思考模式下的独立上限。

## 9. 成本与时间

| 范围 | 请求数 | 大致成本 | 时间 |
|---|---|---|---|
| 快速核对（默认） | 22 | 十几到二十几元 | 6~7 分钟 |
| `--suite text` | 10~15 | 1~3 元（flash）/ 15~25 元（max） | 2~3 分钟 |
| `--suite all`（仅客户要求时） | 约 160 | 12 元（flash）/ 80~100 元（max） | 30~40 分钟 |

成本主要来自文本探测（百万 token 级）与大图上传；图像 token 被服务端截断在 2,500 左右，
所以大文件不等于高成本。报告开头会给出本次的 token 与费用估算。

## 10. 常见问题

**`ModuleNotFoundError: No module named 'PIL'`**
没装依赖：`pip install -r requirements.txt`。

**`401` / `403`**
Key 无效或与 Workspace 不匹配。确认 `DASHSCOPE_WORKSPACE_ID` 与 Key 属于同一个工作空间，
且 Key 是 `sk-ws-` 开头的工作空间 Key。

**`404 model_not_found`**
模型 ID 拼错，或该工作空间未开通这个模型。

**大体积用例超时 / 连接被重置**
把 `BAILIAN_TIMEOUT_S` 调大（如 900）。注意 Anthropic 路径在请求体超限时**不返回 413**，
而是直接断连，这属于被测行为，报告会标注。

**Windows 终端中文乱码**
工具已把输出切到 UTF-8；若仍有问题，先执行 `chcp 65001`。

**`.cmd` 双击一闪而过**
说明环境变量没设或 Python 不在 PATH。在该目录打开 cmd，手动执行 `.cmd` 看报错。

**结果能不能和别人的对比？**
不能。不同模型、不同工作空间、不同时间的限值都可能不同；报告里的模型与时间戳是当次事实。

## 11. 交付前请确认

- 报告里的「结论摘要」与「文档对照」两节读完
- 若出现「静默截断」，说明该路径超长不报错但会丢内容，业务侧必须自己切分
- 把 `results-<model>/` 整个目录回传，包含 `report.md`、`results.json` 与 `curl/`
- 不要把 API Key 写进任何文件或提交到 git
