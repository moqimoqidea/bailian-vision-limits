# 百炼三模型请求限制总结

对 `qwen3.8-flash`、`qwen3.8-max`、`qwen4-max` 在百炼**工作空间域名**三条兼容路径上的请求限制做实测与核对。
本文是结论汇总；逐条原始记录见 `results/`、`results-verify-*/`。

| 项目 | 说明 |
|---|---|
| 测试日期 | 2026-11-23 |
| 端点 | `https://{workspace-id}.cn-beijing.maas.aliyuncs.com` |
| 路径 | OpenAI Chat `/compatible-mode/v1/chat/completions`、OpenAI Responses `/compatible-mode/v1/responses`、Anthropic `/apps/anthropic/v1/messages` |
| 模式 | 非思考模式（`enable_thinking=false`） |
| 方法 | flash 跑全量阶梯定位边界；两个 max 模型按 flash 边界做 22 点逐条核对；单图与请求体再用字节级推进取终值 |

## 一、结论速览

| 维度 | 文档值 | qwen3.8-flash | qwen3.8-max | qwen4-max |
|---|---|---|---|---|
| 最大输入 | 991,808 tokens | 一致（英文 4.4 MB 触发 400） | 一致 | 一致 |
| 文本 · Chat / Anthropic | 991,808 | 4.225 MB 通过 / 4.4 MB 拒绝 | 同左 | 同左 |
| 文本 · Responses | 991,808 | **3.43 MB 起静默截断** | **同左（截断）** | **不截断，4.4 MB 直接 400** |
| 单图 Data URI · Chat/Responses | 20 MB | **50 MiB**（52,428,800 B） | 同左 | 同左 |
| 单图 Data URI · Anthropic | 32 MB | **32 MiB**（33,554,432 B） | 同左 | 同左 |
| 单图原始体积 | 20 MB | **39,321,582 B（37.50 MiB）** | 同左 | 同左 |
| 请求体 · Chat / Responses | 64 MB | **128 MiB（134,217,728 B）** | 同左 | 同左 |
| 请求体 · Anthropic | 64 MB | 62.5 MB 通过 / 65 MB 断连 | 同左 | 同左 |
| Base64 图片张数 | 250 | 250 / 251 精确 | 同左 | 同左 |
| 最小边长 | > 10 px | 实际 ≥10 px | 同左 | 同左 |
| 宽高比 | ≤ 200:1 | 210:1 拒绝 | 同左 | 同左 |
| 4K–8K 仅 JPEG/PNG | 是 | **未执行**（8K WEBP 通过） | 同左 | 同左 |

## 二、逐维度说明

### 1. 文本输入

- 上限就是 **991,808 tokens**，三条路径在超限时的错误信息都直接回显
  `Range of input length should be [1, 991808]`，与文档一致。
- 英文 4.225 MB（约 984 K tokens）通过，4.4 MB 拒绝；中文 4.45 MB 通过，4.6 MB 拒绝。
- 中英文的**字节上限几乎相同**（约 4.5 MB）：汉字 token 密度高，但每字占 3 字节，
  折算后 tokens/字节与英文持平（0.210 vs 0.222）。
- **Responses 是唯一例外**：`qwen3.8-flash` 与 `qwen3.8-max` 在服务端**静默截断**，
  4.4 / 4.5 MB 都只上报 800,017 tokens，超出部分不报错、不计费、直接丢弃；
  `qwen4-max` 已改为按 token 上限**拒绝**（4.4 MB → 400），3.5 MB 完整上报 815,640 tokens。

### 2. 单张图片体积

真正生效的是 **Base64 后的 Data URI 长度**，不是原图大小：

| 路径 | 实际上限 | 对应原图 | 触发方式 |
|---|---|---|---|
| Chat / Responses | 52,428,800 字节（50 MiB） | 39,321,582 字节（37.50 MiB） | 413 `Exceeded limit on max bytes per data-uri item` |
| Anthropic | 33,554,432 字节（32 MiB） | 约 25,165,806 字节（24.00 MiB，换算值） | 413 `BadRequest.TooLarge` |

文档写的 20 MB 原图限制在三条路径上都没有单独生效：真正起作用的是 Data URI 字符串长度。

字节级推进（Chat / Responses，三模型一致）：

- `39,321,582 B` 原图 → Data URI `52,428,798 B` → **200 通过**
- `39,321,583 B` 原图 → Data URI `52,428,802 B` → **413 拒绝**

即上限就是 **50 MiB（52,428,800 B）的 Data URI**，且 `data:image/png;base64,` 这 22 字节前缀**计入**长度。
换算成原图是 37.50 MiB（39,321,582 B）——比文档的 20 MB 宽松 87%。

### 3. 请求体整体

- Chat 与 Responses：上限是 **128 MiB（134,217,728 B）**，三模型一致。
  字节级验证：`134,217,728 B` 返回 200，`134,217,729 B` 直接断开连接（`Broken pipe`）。
  文档的 64 MB 不生效，但也不是「无上限」。
- Anthropic：62.5 MB 通过、65 MB 直接断开连接，上限在 62.5–65 MB 之间（≈64 MiB），
  与文档值最接近。

### 4. 图片张数

250 张通过，251 张返回 400：
`Exceeded limit on max number of data-uri items : 250`。三条路径一致。

### 5. 格式、分辨率与宽高比

- 支持 PNG / JPEG / BMP / TIFF / WEBP；按内容嗅探格式，**不信任声明的 `media_type`**。
- 最小边长实际是 **≥10 px**（9 px 拒绝），比文档的「>10」宽松 1 px。
- 宽高比 4000×20（恰好 200:1）通过，4200×20（210:1）拒绝，与文档一致。
- 文档称「4K–8K 仅支持 JPEG/PNG」，实测 7680×4320 的 WEBP 正常返回 200，该限制**未执行**。
- 8K 图像输入约 2,514 tokens，与 5000×3000 的 2,570 接近，说明 `max_pixels` 在截断，
  分辨率不会线性放大成本。

### 6. 输出长度校验与错误码

| 场景 | Chat | Responses | Anthropic |
|---|---|---|---|
| flash：输出长度 = 131,073 | 400 | **200** | **200** |
| qwen3.8-max：输出长度 = 131,073 | 400 | **200** | **200** |
| qwen4-max：输出长度 = 131,073 | **200** | **200** | **200** |
| 未知模型 | 404 `model_not_found` | 404 `MODEL_NOT_FOUND` | 400 `InvalidParameter` |
| 空对话 | 400 `invalid_parameter_error` | 400 `InvalidParameter` | 400 `InvalidParameter` |

只有 Chat 路径（且非 qwen4-max）会校验输出长度；Responses 与 Anthropic 都不校验，
调用方必须自己限制 `max_tokens`，否则依赖服务端兜底会失效。
错误码在三条路径上连大小写都不同，排障应按 `code` 分支，不要匹配 message。

## 三、模型间只有两处差异

1. **qwen4-max 的 Responses 不再静默截断**（改进）
   - `qwen3.8-flash` / `qwen3.8-max`：3.5 MB → 200 且固定上报 800,017 tokens（截断）
   - `qwen4-max`：3.5 MB → 200 且完整上报 815,640 tokens；4.4 MB → 400
2. **qwen4-max 的 Chat 不校验 `max_tokens`**
   - 131,073（以及上探到 2,097,152）都返回 200；另两个模型在 131,073 就 400

除上述两点外，其余核对点在三个模型上完全一致（qwen3.8-max 22/22 全通过，qwen4-max 21/22，唯一不同即第 1 条）。

## 四、价格与成本

| 模型 | 输入 | 缓存命中 | 输出 | 备注 |
|---|---|---|---|---|
| qwen3.8-flash | 0.8 | 0.1 | 2.7 | 全量 162 次请求约 12 元 |
| qwen3.8-max | 12 | 1.5 | 36 | 单价约为 flash 的 15 倍 |
| qwen4-max | 10 | 0.5 | 30 | 缓存命中价极低（0.5） |

文本探测是主要成本：一次 4 MB 级请求就是约 100 万输入 tokens。对 max 系列，先用
`verify_boundaries.py` 做 22 点核对（单模型 6–7 分钟、十几到二十几元），确认无异常后
再决定是否跑全量，比直接全量省一个数量级。

> 教训：本项目在 qwen3.8-max 上曾直接跑全量，50 个实验就花了约 88 元。

## 五、方法与证据

- **qwen3.8-flash**：全量阶梯 + 二分，162 次请求，11 个边界，报告见 `results/report.md`。
- **qwen3.8-max / qwen4-max**：以 flash 的边界为基线，逐点复验 22 个点位
  （拒绝类请求不计费），结果见 `results-verify-qwen38-max/verify.md`、
  `results-verify-qwen4-max/verify.md`，合并对照见 `results-verify-merged/report.md`。
- **单图与请求体**：用 `push_limits.py` 做字节级推进（150 MB 断连后向下二分，
  再用合法 JSON 空白补齐到精确字节），三模型复验同一点位，结果见 `docs/evidence/`。
- 因此对两个 max 模型的结论是「**在已测点位上与基线一致**」，而不是重新做了全量阶梯；
  唯一的实质差异已单列（第三节）。
- 复现：
  ```bash
  export DASHSCOPE_API_KEY=... DASHSCOPE_WORKSPACE_ID=...
  python verify_boundaries.py --model qwen4-max --out results-verify-qwen4-max
  python run_tests.py --suite all --out results-qwen38-flash   # 全量
  ```

## 六、工程建议

1. **Anthropic 的 `input_tokens` 不是总输入**，需加 `cache_creation_input_tokens` 与
   `cache_read_input_tokens`；只读前者会明显低估。
2. **不要在 Responses 上依赖「超长会报错」**：flash 与 3.8-max 会静默截断并丢内容；
   qwen4-max 才会拒绝。跨模型时客户端必须自己按字节切分（建议 ≤3 MB 留余量）。
3. **单图按 Base64 后长度预检**：50 MiB / 32 MiB 才是真实护栏，不是文档的 20 MB。
4. **`max_tokens` 必须客户端兜底**：只有 Chat（且非 qwen4-max）会校验。
5. **排障按 `code` 分支**：同一个「模型不存在」，三条路径给出三个不同 code。

## 附：文件索引

| 路径 | 内容 |
|---|---|
| `results/report.md` | qwen3.8-flash 全量报告 |
| `results-verify-qwen38-max/verify.md` | qwen3.8-max 22 点核对 |
| `results-verify-qwen4-max/verify.md` | qwen4-max 22 点核对 |
| `results-verify-merged/report.md` | 两模型对照与差异说明 |
| `docs/evidence/image-boundary.md` | 单图 39,321,582 B 的三模型字节级证据 |
| `docs/evidence/body-boundary.md` | 请求体 128 MiB 的阶梯与字节级证据 |
| `docs/limits-summary.md` | 本文 |

> 注：`results/report.md` 是 flash 的全量报告，其中请求体一栏写的是「≥110 MB」——
> 那是当时阶梯的上探止点；后续字节级推进会补到 128 MiB，以本文与 `docs/evidence/` 为准。
