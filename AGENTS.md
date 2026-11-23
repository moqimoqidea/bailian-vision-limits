# AGENTS.md

给在本仓库工作的 AI 代理与工程师的操作说明。人类读者先看 `README.md`。

## 这个仓库是什么

一个**实测工具**，不是 SDK。它对阿里云百炼工作空间域名下的三条兼容路径发真实请求，
测量请求边界（文本 token 上限、单图体积、请求体、张数、格式、尺寸、宽高比、错误码），
产出可复现的 `results/report.md`、`results/results.json` 与 `results/curl/*.sh`。

三条路径：OpenAI Chat（`/compatible-mode/v1/chat/completions`）、
OpenAI Responses（`/compatible-mode/v1/responses`）、Anthropic（`/apps/anthropic/v1/messages`）。

## 必须先读的硬性规则

1. **绝不把 API Key 写进任何文件。** 一切通过 `DASHSCOPE_API_KEY` / `DASHSCOPE_WORKSPACE_ID`
   环境变量。提交前用 `grep -r "sk-ws-\\|sk-" .` 自检（`results/` 与 `.git/` 也要看）。
2. **不要跨模型套用结论。** 文档限值随模型系列变化；`DocumentedLimits` 的默认值只对应
   `qwen3.8-flash`。换模型时用 `BAILIAN_*` 环境变量覆盖，并把结果放到独立的 `--out` 目录。
3. **结果目录不是缓存。** `results/records.jsonl` 是断点续跑的账本，`--force` 会替换所选实验的
   历史记录；不要手工编辑这三个文件，改代码后重跑。
4. **测试必须离线可跑。** `tests/` 不允许发起网络请求；新增解析/搜索逻辑必须有单测。
5. **报告的文字结论必须由数据推导。** 新增结论文案时从 `records`/`boundaries` 取值，
   不要在字符串里写死数字（历史教训：把「Anthropic 少报」写死，实际是自己没求和）。

## 测试策略：默认快速模式（重要）

**新模型一律先跑快速核对，只有客户明确要求「全量 / 完整阶梯」时才跑全量。**

| 场景 | 动作 | 耗时 | 成本 |
|---|---|---|---|
| 默认（换新模型、例行确认） | `verify_boundaries.py`：按 flash 基线逐点复验 22 项 | 6–7 分钟 | 十几到二十几元 |
| 核对全过 | 直接复用基线结论，**不跑全量** | — | — |
| 核对有异常 | **只对异常维度**做定点阶梯（`--only` + 自定义点位），不要整体重跑 | 视维度 | 视维度 |
| 客户明确要求全量 | `run_tests.py --suite all` | 30–40 分钟 | 高价模型 80–100 元 |

判断与执行细则：

1. 先 `verify_boundaries.py --model <id> --out results-verify-<id>`，它读
   `results/results.json` 的基线边界，拒绝类请求不计费。
2. 核对全过就结束，报告里写「在本轮 22 个点位上与基线一致」，不要暗示做过全量。
3. 出现异常时先定位到具体维度（文本 / 单图 / 请求体 / 张数），再用
   `run_tests.py --only <experiment>` 或自定义 `points` 做小范围阶梯。
4. 全量是**例外**，必须在交付说明里写明「客户要求全量」。
5. 价格先算再跑：max 系列输入 10–12 元/百万，一次 4 MB 文本请求就是约 100 万 tokens。
   历史教训：qwen3.8-max 直接跑全量，50 个实验花了约 88 元。

## 常用命令

```bash
python3 -m unittest discover -s tests -v      # 39 个离线单测
python3 run_tests.py --list                   # 列出实验与探测点
python3 run_tests.py --dry-run                # 只构建载荷，不发请求
python3 run_tests.py --suite text --protocol openai
python3 run_tests.py --protocol responses --force --out results
python3 run_tests.py --report-only            # 由 results.json 重出报告
python3 run_tests.py --dump-body text_en_openai@4.4 --out /tmp/body.json
python3 push_limits.py --model qwen3.8-flash --dim image --bytes 39321582,39321583
python3 push_limits.py --model qwen3.8-flash --dim body  --mb 127.9,128
```

`--force` = 重跑所选实验并替换其历史记录；`--only` = 只跑指定 id 并替换。

## 代码结构与依赖方向

```
run_tests.py            CLI
limits/
  config.py             Settings（环境变量）、DocumentedLimits（可覆盖）、单价
  protocols.py          Protocol 策略：body / usage / reply / headers
  transport.py          HTTP + 重试 + HttpResult.kind（accepted/rejected/transient）
  fixtures.py           确定性测试数据（png_of_size / noise_png_of_size / 文本）
  base.py               Built、Context、SingleRequest、BoundarySearch
  wire.py               JSON 编码 + 载荷指标
  experiments/          text、text_truncation、transport_body、image_size、
                        image_size_real、image_count、image_format、misc
  runner.py             编排、进度、增量落盘
  report.py             Markdown 报告（章节按数据动态编号）
  curlgen.py            失败用例复现脚本
  persist.py            反序列化
tests/                  test_fixtures / test_protocols / test_boundary
```

依赖是单向的：`config`/`protocols`/`fixtures` 不依赖 `base`；`experiments` 只依赖 `base` 与
`wire`；`report` 只读 `records`。不要把 I/O 或格式化逻辑塞进 `protocols.py`。

## 新增一条协议路径

1. 在 `limits/protocols.py` 继承 `Protocol`，实现 `headers`、`_body`、`usage`、`reply`。
   构造函数里通过 `Protocol.body()` 模板方法统一钳制 `max_tokens`（下限见 `min_max_tokens`）。
2. 若路径有自己的字段名，设置 `max_tokens_field` / `messages_field`，`misc` 套件会自动跟随。
3. 注册到文件末尾的 `PROTOCOLS` 元组。所有 suite 会自动为它生成实验。
4. 在 `tests/test_protocols.py` 增加载荷、usage、reply 三类断言。
5. `python3 run_tests.py --list --protocol <key>` 确认实验生成，再 `--dry-run` 检查体积。

## 新增一个实验维度

优先用现成框架，不要写新的 runner：

- 单点验证：`SingleRequest(id=..., suite=..., builder=..., expect=...)`
- 找阈值：`BoundarySearch(id=..., points=[...], tolerance=..., builder=...)`
  - 网关用「连接重置」表达超限时传 `transient_is_failure=True`
  - 所有 probe 记录都会带 `axis` / `axis_value`，报告直接可用
- 在 `limits/experiments/__init__.py` 的 `SUITES` 注册模块。

`builder(value) -> Built` 必须返回确定性的字节（同样的 value 得到同样的 payload），
否则 `--dump-body` 无法复现。

## 测试与验收

提交前跑：

```bash
python3 -m unittest discover -s tests
python3 run_tests.py --dry-run          # 确认所有 suite 能构建载荷
```

改动解析或边界逻辑时，补一个**回归单测**（例：Anthropic usage 三项求和、400 超时按抖动处理、
Responses 的 `max_output_tokens` 下限 16）。

报告类改动用 `--report-only` 验证，不必重新发请求。

## 已踩过的坑（改代码前看一遍）

1. **填充型 PNG 不能代替真实大图。** 64×64 像素 + 大 `tEXt` 块只能探传输上限；
   要证明「限制是否作用在图像内容上」必须用不可压缩随机像素（`noise_png_of_size`）。
2. **400 不一定是限制。** `Download multimodal file timed out` 是 400，但属于抖动；
   `HttpResult.kind` 会按 message 识别 `timed out` / `try again` 等标记。
3. **Anthropic 的 `input_tokens` 不是总输入。** 必须加 `cache_creation_input_tokens` 与
   `cache_read_input_tokens`；工具已在 `Protocol.usage()` 归一化，别再退回旧写法。
4. **Responses 会静默截断。** 超长约 3.43 MB 时不报错，只把 input 截断后照常推理；
   判定要用「预期 tokens（字符数×密度）vs 上报 tokens」，不能只看 HTTP 200。
5. **Responses 要求 `max_output_tokens >= 16`。** 常量写在 builder 里时，改实验对象的属性没用；
   钳制必须发生在 `Protocol.body()` 入口。
6. **`usage` 的字段名在三条路径上不同。** Chat 用 `prompt_tokens`，Responses 用 `input_tokens`，
   Anthropic 用三项之和；不要写跨路径的字段假设。
7. **报告章节按数据动态生成。** 新增章节时把它加进 `Report.render()` 的 builders 列表，
   标题不要自己编号；`NUMERALS` 不够长会退化成阿拉伯数字。

## 安全约束（改代码前必读）

1. **端点只能由 `Settings` 拼装。** 必须 HTTPS 且主机名以 `.maas.aliyuncs.com` 结尾；
   工作空间 ID 与区域都受正则约束（禁止 `@`、`/`、`:`、空格），防止把请求改写到别的主机。
2. **不跟随重定向。** `Transport` 用自定义 `HTTPRedirectHandler`，3xx 直接按失败处理，
   避免认证头被转发到第三方。
3. **所有对外文本都脱敏。** 错误 message、模型回复、`--replay` 输出在落盘/打印前统一走
   `limits/redact.py`；新增输出路径必须调用 `redact()`。
4. **复现脚本不把密钥放进 argv。** `.sh` 用 `curl --config` 读取临时配置文件（`umask 077`），
   并加 `-q` 忽略 `.curlrc`；`.cmd` 走 `python run_tests.py --replay`。
5. **脚本内容不可被数据改写。** 注释与参数先经 `_safe_text()` 单行化，
   实验 id 必须匹配 `_EXPERIMENT_ID`，否则跳过生成。

## 跨平台约束（Windows 必须可用）

1. 路径一律用 `pathlib`，不要手拼 `/`，不要假设有 `/tmp`（脚本里用 `%TEMP%` 或 `--out` 指定）。
2. 所有文件读写显式 `encoding="utf-8"`；`results/curl/*.cmd` 内容保持 **纯 ASCII + CRLF**，
   避免 cmd.exe 在非中文代码页下解析乱码。
3. `chmod` 只在 `os.name == "posix"` 时调用（Windows 上无意义）。
4. `run_tests.py` 启动时会把 stdout/stderr 切到 UTF-8；新增独立入口也要做同样处理。
5. 新增生成脚本时，必须同时产出 `.sh` 与 `.cmd`：`.sh` 用 curl，`.cmd` 调
   `python run_tests.py --replay`，两者重放同一请求体。
6. 不要依赖 `bash`、`grep`、`sed`、`python3` 这些在 Windows 上不保证存在的命令；
   文档里给 Windows 命令时用 `python` / `py -3`、`set` / `$env:`。

## 交付检查清单

- [ ] 没有密钥；没有写死的本机绝对路径（`/Users/...`）
- [ ] `python3 -m unittest discover -s tests` 全绿
- [ ] `--dry-run` 全量可构建
- [ ] 报告中的数字与 `results.json` 一致（用 `--report-only` 重生成一次）
- [ ] 若换过模型：`README.md` 的「样例结果」注明模型与日期，不要留旧模型的数字
- [ ] `HANDOFF.md` 的模型示例与当前交付目标一致（默认写的是 qwen3.8-max / qwen4-max）
- [ ] 新模型默认走 `verify_boundaries.py`；若跑了全量，交付说明里写明「客户要求全量」
