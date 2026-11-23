# 阿里云百炼 qwen3.8-flash 请求限制实测报告

- 端点：`https://{workspace-id}.cn-beijing.maas.aliyuncs.com`
- 模型：`qwen3.8-flash`（非思考模式；最大输入 991,808 tokens，上下文 1,000,000，最大输出 131,072）
- 时间：2026-11-23T13:15:38+08:00
- 请求数：162；累计输入 23,863,225 tokens（其中缓存命中 9,933,056）；按 0.8 / 0.1 / 2.7 元每百万 tokens（未命中 / 命中 / 输出）估算成本约 12.14 元
- 数据说明：表格中的「≥ X」是本次运行的上探止点；单图与请求体的字节级终值见 `docs/limits-summary.md`。

## 一、结论摘要

- **纯文本** OpenAI Chat、Anthropic 兼容都在 4.4 MB 英文文本处返回 `Range of input length should be [1, 991,808]`，与文档的 991,808 tokens 完全一致；OpenAI Responses **不报错，而是在约 3.4 MB 处静默截断输入**（详见「静默截断」一节）；64 MB 的传输上限对纯文本不可达——那相当于约 1,400 万 tokens。中文实测 4.45 MB（约 0.98M tokens）仍通过、4.6 MB 被拒。
- **单图体积** OpenAI Chat / OpenAI Responses：上限 **52,428,800 字节（50 MiB）Data URI**，约合原图 37.5 MB；Anthropic 兼容：上限 **33,554,432 字节（32 MiB）Data URI**，约合原图 24.0 MB。文档的 20 MB 原图限制在三条路径上均未单独生效。
- **请求体** OpenAI Chat / OpenAI Responses **110 MB 仍返回 200，未观察到请求体上限**；Anthropic 兼容 62.5 MB 通过、65 MB 被**直接断开连接**（无 HTTP 状态码）。文档的 64 MB 只以「断连」形式出现在部分路径上。
- **图片张数** 250 张通过、251 张被拒，错误信息为「Exceeded limit on max number of data-uri items : 250」，与文档的 250 张完全一致。
- **格式档位** 7680×4320 的 WEBP 仍返回 200，文档所述「4K–8K 仅支持 JPEG/PNG」未被执行；而宽高比 210:1 会被精确拒绝。

| 接口 | 文本 | 单图 | 请求体 | 图片张数 |
|---|---|---|---|---|
| OpenAI Chat | 4.22 / 4.4 MB | 36.38 / 39.25 MB | ≥ 110 MB | 250 / 251 张 |
| OpenAI Responses | 截断 @ 3.43 MB | 36.38 / 39.25 MB | ≥ 110 MB | 250 / 251 张 |
| Anthropic 兼容 | 4.22 / 4.4 MB | 23.95 / 24 MB | 62.5 / 65 MB | 250 / 251 张 |

一句话：**文档里的「张数」和「宽高比」被精确执行，而「单图体积」「4K–8K 格式档」在 OpenAI 两条路径上并未生效、「64 MB 请求体」只在部分路径以断连形式出现。**三条路径的差异不是数值差异，而是**校验项集合不同**。

## 二、方法学

1. **把体积与 token 成本解耦。** 图像 token 由像素决定，请求体由字节决定。体积类用例分两组：一组是 64×64 像素、用 `tEXt` 块撑大的 PNG（成本近零，用于探传输上限）；另一组是**不可压缩的随机像素**（文件体积≈真实像素数据，用于验证体积限制是否真的作用在图像内容上）。
2. **阶梯 + 二分。** 按文档值布点，命中首个失败点后在上一个通过点之间二分，直到区间小于容差。报告给出实测区间 `[最大通过, 首个拒绝)`。
3. **失败分类。** 4xx 业务拒绝直接计入边界；超时、429、5xx 视为抖动并重试两次。唯一的例外是请求体用例：网关用「直接断开连接」表达超限，该开关显式打开并在报告中标注。
4. **口径。** MB 一律为 MiB（1024×1024 字节），与 `Content-Length` 对齐；图片体积指编码前原始文件字节；Base64 体积指编码后字符数。
5. **未覆盖项。** 公网 URL 与本地路径传图（需公网图床）、视频输入、HEIC（本机无编码器）、RPM/TPM 限流、思考模式下的 983,616 tokens 上限。

## 三、纯文本请求

### OpenAI Chat

| 文本 | 内容体积 | 请求体 | usage 总输入 tokens | 结果 | 错误 |
|---|---|---|---|---|---|
| 英文文本 | 0.25 MB | 0.25 MB | 58,279 | 200 通过 | — |
| 英文文本 | 1 MB | 1.00 MB | 233,041 | 200 通过 | — |
| 英文文本 | 3 MB | 3.00 MB | 699,076 | 200 通过 | — |
| 英文文本 | 3.7 MB | 3.70 MB | 862,188 | 200 通过 | — |
| 英文文本 | 4.05 MB | 4.05 MB | 943,743 | 200 通过 | — |
| 英文文本 | 4.22 MB | 4.22 MB | 984,521 | 200 通过 | — |
| 英文文本 | 4.4 MB | 4.40 MB | — | 400 拒绝 | `invalid_parameter_error` Range of input length should be [1, 991808] |
| 中文文本 | 1 MB | 1.00 MB | 220,097 | 200 通过 | — |
| 中文文本 | 1.8 MB | 1.80 MB | 396,154 | 200 通过 | — |
| 中文文本 | 2.2 MB | 2.20 MB | 484,182 | 200 通过 | — |
| 中文文本 | 4 MB | 4.00 MB | 880,311 | 200 通过 | — |
| 中文文本 | 4.3 MB | 4.30 MB | 946,333 | 200 通过 | — |
| 中文文本 | 4.45 MB | 4.45 MB | 979,343 | 200 通过 | — |
| 中文文本 | 4.6 MB | 4.60 MB | — | 400 拒绝 | `invalid_parameter_error` Range of input length should be [1, 991808] |

token 密度约 **0.222 tokens/字符**；4.4 MB 处约 1,025,710 tokens，是上限 991,808 的 1.03 倍，与「恰好在此处被拒」一致。错误信息本身回显了精确的 token 上限，因此字节级精度意义有限。

### OpenAI Responses

| 文本 | 内容体积 | 请求体 | usage 总输入 tokens | 结果 | 错误 |
|---|---|---|---|---|---|
| 英文文本 | 0.25 MB | 0.25 MB | 58,311 | 200 通过 | — |
| 英文文本 | 1 MB | 1.00 MB | 233,073 | 200 通过 | — |
| 英文文本 | 3 MB | 3.00 MB | 699,108 | 200 通过 | — |
| 英文文本 | 4.4 MB | 4.40 MB | 800,017 | 200 通过 | — |
| 英文文本 | 4.5 MB | 4.50 MB | 800,017 | 200 通过 | — |
| 中文文本 | 1 MB | 1.00 MB | 220,129 | 200 通过 | — |
| 中文文本 | 1.8 MB | 1.80 MB | 396,186 | 200 通过 | — |
| 中文文本 | 2.2 MB | 2.20 MB | 484,214 | 200 通过 | — |
| 中文文本 | 4 MB | 4.00 MB | 755,576 | 200 通过 | — |
| 中文文本 | 4.6 MB | 4.60 MB | 755,576 | 200 通过 | — |


**注意：** 其中 4 条虽然返回 200，但上报的 token 数明显低于按字符数推算的预期，属于**静默截断**——详见下一节。

### Anthropic 兼容

| 文本 | 内容体积 | 请求体 | usage 总输入 tokens | 结果 | 错误 |
|---|---|---|---|---|---|
| 英文文本 | 0.25 MB | 0.25 MB | 58,279 | 200 通过 | — |
| 英文文本 | 1 MB | 1.00 MB | 233,041 | 200 通过 | — |
| 英文文本 | 3 MB | 3.00 MB | 699,076 | 200 通过 | — |
| 英文文本 | 3.7 MB | 3.70 MB | 862,188 | 200 通过 | — |
| 英文文本 | 4.05 MB | 4.05 MB | 943,743 | 200 通过 | — |
| 英文文本 | 4.22 MB | 4.22 MB | 984,521 | 200 通过 | — |
| 英文文本 | 4.4 MB | 4.40 MB | — | 400 拒绝 | `InvalidParameter` Range of input length should be [1, 991808] |
| 中文文本 | 1 MB | 1.00 MB | 220,097 | 200 通过 | — |
| 中文文本 | 1.8 MB | 1.80 MB | 396,154 | 200 通过 | — |
| 中文文本 | 2.2 MB | 2.20 MB | 484,182 | 200 通过 | — |
| 中文文本 | 4 MB | 4.00 MB | 880,311 | 200 通过 | — |
| 中文文本 | 4.3 MB | 4.30 MB | 946,333 | 200 通过 | — |
| 中文文本 | 4.45 MB | 4.45 MB | 979,343 | 200 通过 | — |
| 中文文本 | 4.6 MB | 4.60 MB | — | 400 拒绝 | `InvalidParameter` Range of input length should be [1, 991808] |

token 密度约 **0.222 tokens/字符**；4.4 MB 处约 1,025,710 tokens，是上限 991,808 的 1.03 倍，与「恰好在此处被拒」一致。错误信息本身回显了精确的 token 上限，因此字节级精度意义有限。

### 中文为什么没有更早触顶

中文实测 0.630 tokens/字符。一个汉字占 3 字节、约 1.6 tokens，折合 **0.210 tokens/字节**；英文是 0.222 tokens/字符、约 4.5 字符/token，折合 0.222 tokens/字节。两者几乎相同，所以「中文 2 MB 就到顶」的直觉是错的——**按字节算，中英文的上限都在 4.5 MB 附近**。

### usage 口径：三条路径的「总输入」字段含义不同

- **OpenAI Chat**：`prompt_tokens` 已是总输入，`prompt_tokens_details.cached_tokens` 是其中的缓存命中部分（子集，不叠加）。
- **OpenAI Responses**：同上，字段名为 `input_tokens`，缓存命中在 `input_tokens_details.cached_tokens`。
- **Anthropic**：`input_tokens` 只统计**最后一个缓存断点之后**的 token；官方口径为 `total = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`（[Prompt caching 文档](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)）。

| 内容体积 | 接口 | usage 总输入 tokens | 与 Chat 的差异 |
|---|---|---|---|
| 0.25 MB | OpenAI Chat | 58,279 | 基准 |
| 0.25 MB | OpenAI Responses | 58,311 | +32 |
| 0.25 MB | Anthropic 兼容 | 58,279 | 0 |
| 1 MB | OpenAI Chat | 233,041 | 基准 |
| 1 MB | OpenAI Responses | 233,073 | +32 |
| 1 MB | Anthropic 兼容 | 233,041 | 0 |
| 3 MB | OpenAI Chat | 699,076 | 基准 |
| 3 MB | OpenAI Responses | 699,108 | +32 |
| 3 MB | Anthropic 兼容 | 699,076 | 0 |

以 1 MB 为例：Anthropic 上报 `input_tokens`=175,697、`cache_read_input_tokens`=57,344，合计 233,041，与 Chat 的 `prompt_tokens` 完全相同。

Chat 与 Anthropic 的总输入**逐位相等**；Responses 只差一个固定开销（+32 tokens），来自 `input` 字符串与 `messages` 数组的包装差异。三条路径的计数本身都准确，差异只在字段口径：该兼容层会把大部分输入（含图像 token）计入 `cache_read_input_tokens`，只读 `input_tokens` 会明显低估。做容量规划或成本核算时，Anthropic 必须先求和，并注意缓存命中与未命中单价不同。

## 四、Responses 路径的静默截断

Responses 路径在输入超长时**不返回 4xx**，而是把 `input` 截断后照常推理。只看 HTTP 状态会把这种行为误读成「限制更宽松」。

| 内容体积 | 字符数 | 预期 tokens | 实际上报 | 比例 | 结论 |
|---|---|---|---|---|---|
| 3.3 MB | 3,460,331 | 769,147 | 769,034 | 100.0% | 完整 |
| 3.5 MB | 3,670,047 | 815,762 | 800,017 | 98.1% | **截断** |
| 3.65 MB | 3,827,333 | 850,723 | 800,017 | 94.0% | **截断** |
| 3.8 MB | 3,984,619 | 885,684 | 800,017 | 90.3% | **截断** |

3 次被截断的请求上报值完全相同，反算截断点约 **3.43 MB（3,599,210 字节）**：超出该长度的内容既不报错、也不计费，但**会被静默丢弃**。长文档若走 Responses 路径，必须由客户端按字节切分，不能依赖服务端拒绝。

中文侧同样封顶在 755,576 tokens，按 0.630 tokens/字符、每字 3 字节折算约 **3.43 MB**，与英文的 3.43 MB 吻合——说明截断判据是**字节数**而不是 token 数。

## 五、单张图片体积

### 真实像素图像（决定性实验）

文件由不可压缩的随机像素构成，体积约等于真实像素数据，排除「元数据被剥离」的干扰。

| 接口 | 原图体积 | Data URI 体积 | 请求体 | 结果 | 错误 |
|---|---|---|---|---|---|
| OpenAI Chat | 20.5 MB | 27.33 MB | 27.33 MB | 200 通过 | — |
| OpenAI Chat | 33.5 MB | 44.67 MB | 44.67 MB | 200 通过 | — |
| OpenAI Chat | 36.38 MB | 48.50 MB | 48.50 MB | 200 通过 | — |
| OpenAI Chat | 39.25 MB | 52.33 MB | 52.33 MB | 413 拒绝 | `invalid_request_error` Exceeded limit on max bytes per data-uri item : 52428800 |
| OpenAI Chat | 45 MB | 60.00 MB | 60.00 MB | 413 拒绝 | `invalid_request_error` Exceeded limit on max bytes per data-uri item : 52428800 |
| OpenAI Responses | 20.5 MB | 27.33 MB | 27.33 MB | 200 通过 | — |
| OpenAI Responses | 33.5 MB | 44.67 MB | 44.67 MB | 200 通过 | — |
| OpenAI Responses | 36.38 MB | 48.50 MB | 48.50 MB | 200 通过 | — |
| OpenAI Responses | 39.25 MB | 52.33 MB | 52.33 MB | 413 拒绝 | `BadRequest.TooLarge` Exceeded limit on max bytes per data-uri item : 52428800 |
| OpenAI Responses | 45 MB | 60.00 MB | 60.00 MB | 413 拒绝 | `BadRequest.TooLarge` Exceeded limit on max bytes per data-uri item : 52428800 |
| Anthropic 兼容 | 20.5 MB | 27.33 MB | 27.33 MB | 200 通过 | — |
| Anthropic 兼容 | 21 MB | 28.00 MB | 28.00 MB | 200 通过 | — |
| Anthropic 兼容 | 23.9 MB | 31.87 MB | 31.87 MB | 200 通过 | — |
| Anthropic 兼容 | 23.95 MB | 31.93 MB | 31.93 MB | 200 通过 | — |
| Anthropic 兼容 | 24 MB | 32.00 MB | 32.00 MB | 413 拒绝 | `BadRequest.TooLarge` Exceeded limit on max bytes per data-uri item : 33554432 |
| Anthropic 兼容 | 24.1 MB | 32.13 MB | 32.13 MB | 413 拒绝 | `BadRequest.TooLarge` Exceeded limit on max bytes per data-uri item : 33554432 |

- OpenAI Chat：`阈值落在 [36.375, 39.25) MB`，错误信息给出字节上限 52,428,800（= 50 MiB），对应原图约 37.5 MB。
- OpenAI Responses：`阈值落在 [36.375, 39.25) MB`，错误信息给出字节上限 52,428,800（= 50 MiB），对应原图约 37.5 MB。
- Anthropic 兼容：`阈值落在 [23.95, 24) MB`，错误信息给出字节上限 33,554,432（= 32 MiB），对应原图约 24.0 MB。

体积最大的通过请求（OpenAI Chat，36.375 MB）输入 tokens 为 2,555（纯文本请求约 30），证明图像确实被解码处理，不是被静默丢弃。文档的 20 MB 单图限制在三条路径上均未生效——真正起作用的是编码后的 Data URI 字符串上限。

### 填充型 PNG（交叉验证）

64×64 像素、用 `tEXt` 块撑到目标体积。两轮结果一致，说明体积判定不区分「像素数据」与「附属块」——真正没生效的是限制本身，而不是测法有问题。

| 接口 | 原图体积 | Data URI 体积 | 结果 |
|---|---|---|---|
| OpenAI Chat | 9.9 MB | 13.20 MB | 200 通过 |
| OpenAI Chat | 14.9 MB | 19.87 MB | 200 通过 |
| OpenAI Chat | 15.1 MB | 20.13 MB | 200 通过 |
| OpenAI Chat | 19.9 MB | 26.53 MB | 200 通过 |
| OpenAI Chat | 20.1 MB | 26.80 MB | 200 通过 |
| OpenAI Responses | 9.9 MB | 13.20 MB | 200 通过 |
| OpenAI Responses | 14.9 MB | 19.87 MB | 200 通过 |
| OpenAI Responses | 15.1 MB | 20.13 MB | 200 通过 |
| OpenAI Responses | 19.9 MB | 26.53 MB | 200 通过 |
| OpenAI Responses | 20.1 MB | 26.80 MB | 200 通过 |
| Anthropic 兼容 | 9.9 MB | 13.20 MB | 200 通过 |
| Anthropic 兼容 | 14.9 MB | 19.87 MB | 200 通过 |
| Anthropic 兼容 | 15.1 MB | 20.13 MB | 200 通过 |
| Anthropic 兼容 | 19.9 MB | 26.53 MB | 200 通过 |
| Anthropic 兼容 | 20.1 MB | 26.80 MB | 200 通过 |

## 六、请求体整体上限

6 张 64×64、单张约 8–14 MB 的 PNG，把请求体顶到目标体积；图像 token 成本可忽略。

| 接口 | 目标体积 | 实际请求体 | 图片数 | 结果 | 错误 |
|---|---|---|---|---|---|
| OpenAI Chat | 12 MB | 12.00 MB | 6 | 200 通过 | — |
| OpenAI Chat | 60 MB | 60.00 MB | 6 | 200 通过 | — |
| OpenAI Chat | 65 MB | 65.00 MB | 6 | 200 通过 | — |
| OpenAI Chat | 80 MB | 80.00 MB | 6 | 200 通过 | — |
| OpenAI Chat | 110 MB | 110.00 MB | 6 | 200 通过 | — |
| OpenAI Responses | 12 MB | 12.00 MB | 6 | 200 通过 | — |
| OpenAI Responses | 60 MB | 60.00 MB | 6 | 200 通过 | — |
| OpenAI Responses | 65 MB | 65.00 MB | 6 | 200 通过 | — |
| OpenAI Responses | 80 MB | 80.00 MB | 6 | 200 通过 | — |
| OpenAI Responses | 110 MB | 110.00 MB | 6 | 200 通过 | — |
| Anthropic 兼容 | 12 MB | 12.00 MB | 6 | 200 通过 | — |
| Anthropic 兼容 | 60 MB | 60.00 MB | 6 | 200 通过 | — |
| Anthropic 兼容 | 62.5 MB | 62.50 MB | 6 | 200 通过 | — |
| Anthropic 兼容 | 65 MB | 65.00 MB | 6 | 连接重置 | `—` URLError: [Errno 32] Broken pipe |

- OpenAI Chat：**110 MB 仍返回 200，未观察到请求体上限**，文档的 64 MB 在该路径未生效。
- OpenAI Responses：**110 MB 仍返回 200，未观察到请求体上限**，文档的 64 MB 在该路径未生效。
- Anthropic 兼容：`阈值落在 [62.5, 65) MB`。该侧没有 413，网关直接重置连接（`Broken pipe`），重试三次仍复现，属于体积触发的拒绝而非网络抖动。

## 七、Base64 图片张数

| 接口 | 张数 | 请求体 | 结果 | 错误 |
|---|---|---|---|---|
| OpenAI Chat | 1 张 | 0.001 MB | 200 通过 | — |
| OpenAI Chat | 250 张 | 0.080 MB | 200 通过 | — |
| OpenAI Chat | 251 张 | 0.080 MB | 400 拒绝 | `invalid_request_error` Exceeded limit on max number of data-uri items : 250 |
| OpenAI Responses | 1 张 | 0.001 MB | 200 通过 | — |
| OpenAI Responses | 250 张 | 0.078 MB | 200 通过 | — |
| OpenAI Responses | 251 张 | 0.079 MB | 400 拒绝 | `BadRequest.TooLarge` Exceeded limit on max number of data-uri items : 250 |
| Anthropic 兼容 | 1 张 | 0.001 MB | 200 通过 | — |
| Anthropic 兼容 | 250 张 | 0.083 MB | 200 通过 | — |
| Anthropic 兼容 | 251 张 | 0.083 MB | 400 拒绝 | `BadRequest.TooLarge` Exceeded limit on max number of data-uri items : 250 |

张数上限与体积上限是**两条独立约束**：250 张 64×64 小图只有约 80 KB，轻松通过体积检查，但第 251 张被精确拦下。实际可用张数取两者中更紧的一条。

## 八、格式、分辨率与宽高比

以 OpenAI Chat 为主表；Responses 与 Anthropic 两条路径的逐项对比见 `results.json`。

| 用例 | 文档预期 | 原始体积 | 结果 | 错误 |
|---|---|---|---|---|
| PNG 64×64 | 文档列为支持格式，期望 200 | 0.2 KB | 200 通过 | — |
| JPEG 64×64 | 文档列为支持格式，期望 200 | 0.7 KB | 200 通过 | — |
| BMP 64×64 | 文档列为支持格式（<4K），期望 200 | 12.1 KB | 200 通过 | — |
| TIFF 64×64 | 文档列为支持格式（<4K），期望 200 | 12.1 KB | 200 通过 | — |
| WEBP 64×64 | 文档列为支持格式（<4K），期望 200 | 0.1 KB | 200 通过 | — |
| 5000×3000 JPEG | 4K–8K 区间允许 JPEG，期望 200 | 230.5 KB | 200 通过 | — |
| 5000×3000 WEBP | 4K–8K 区间仅允许 JPEG/PNG，期望 4xx | 26.2 KB | 200 通过 | — |
| 10×10 PNG | 文档：宽高均须 > 10 px；10 px 恰好是文档边界 | 0.1 KB | 200 通过 | — |
| 9×9 PNG | 低于 10 px，用于确认阈值为「≥10」还是「>10」 | 0.1 KB | 400 拒绝 | `invalid_parameter_error` The image length and width do not meet the model restrictions. [height:9 or width:9 must be larger than 10] |
| 1×1 PNG | 极小边长的反证用例：若仍返回 200，说明最小边限制未被实际执行 | 0.1 KB | 400 拒绝 | `invalid_parameter_error` The image length and width do not meet the model restrictions. [height:1 or width:1 must be larger than 10] |
| 11×11 PNG | 刚好越过最小边限制，期望 200 | 0.1 KB | 200 通过 | — |
| 4000×20 PNG | 宽高比恰好 200:1，文档为「不得超过」，期望 200 | 0.4 KB | 200 通过 | — |
| 4200×20 PNG | 宽高比 210:1 超过 200:1，期望 4xx | 0.4 KB | 400 拒绝 | `invalid_parameter_error` The image length and width do not meet the model restrictions. [absolute aspect ratio must be smaller than 200, got 20 /… |
| 7680×4320 PNG | 文档推荐上限 8K 以内，期望 200 且图像 token 被 max_pixels 截断 | 104.7 KB | 200 通过 | — |
| 7680×4320 WEBP | 文档称 4K–8K 仅支持 JPEG/PNG；若 200 则说明该格式限制未被执行 | 57.7 KB | 200 通过 | — |
| JPEG 字节声明为 image/png | 观察服务端是否嗅探真实格式：200 表示按内容识别，4xx 表示信任 media_type | 0.7 KB | 200 通过 | — |
| 非图像字节声明为 image/png | 基数为合法 base64 但内容不是图像，期望 4xx | 0.2 KB | 400 拒绝 | `invalid_parameter_error` The image format is illegal and cannot be opened |
| 0 字节图像 | 空数据，期望 4xx | 0.0 KB | 400 拒绝 | `invalid_parameter_error` The provided URL does not appear to be valid. Ensure it is correctly formatted. |

三条路径对格式、尺寸、宽高比的判定完全一致。

两处与文档不符：**最小边长**实测阈值为 ≥10 px（文档写「>10」，9 px 才被拒）；**4K–8K 仅 JPEG/PNG** 未执行，7680×4320 的 WEBP 正常返回 200。另外，把 JPEG 字节声明成 `image/png` 也能通过，说明服务端按内容嗅探格式，不信任 `media_type`。8K（33 Mpx）输入 2,514 tokens，5K（15 Mpx）输入 2,570 tokens——像素数翻倍而 token 基本持平，说明 `max_pixels` 在截断，分辨率不会线性放大成本。

## 九、其他边界

| 接口 | 用例 | 预期 | 结果 | 错误 |
|---|---|---|---|---|
| OpenAI Chat | max_tokens = 131,073 | 超过最大输出 131,072，期望 4xx | 400 拒绝 | `invalid_parameter_error` Range of max_tokens should be [1, 131072] |
| OpenAI Responses | max_output_tokens = 131,073 | 超过最大输出 131,072，期望 4xx | 200 通过 | — |
| Anthropic 兼容 | max_tokens = 131,073 | 超过最大输出 131,072，期望 4xx | 200 通过 | — |
| OpenAI Chat | 不存在的模型名 | 期望 4xx，用于区分「模型不存在」与「请求超限」两类错误码 | 404 拒绝 | `model_not_found` Model not exist. |
| OpenAI Responses | 不存在的模型名 | 期望 4xx，用于区分「模型不存在」与「请求超限」两类错误码 | 404 拒绝 | `MODEL_NOT_FOUND` Model not found: qwen3.8-flash-does-not-exist |
| Anthropic 兼容 | 不存在的模型名 | 期望 4xx，用于区分「模型不存在」与「请求超限」两类错误码 | 400 拒绝 | `InvalidParameter` Model not exist. |
| OpenAI Chat | messages 为空数组 | 期望 4xx，记录结构校验的错误码 | 400 拒绝 | `invalid_parameter_error` Role must be in ["user", "assistant", "system", "function", "plugin", "tool"] and the role in last message must be in ["… |
| OpenAI Responses | input 为空数组 | 期望 4xx，记录结构校验的错误码 | 400 拒绝 | `InvalidParameter` <400> InternalError.Algo.InvalidParameter: Role must be in ["user", "assistant", "system", "function", "plugin", "tool"]… |
| Anthropic 兼容 | messages 为空数组 | 期望 4xx，记录结构校验的错误码 | 400 拒绝 | `InvalidParameter` Role must be in ["user", "assistant", "system", "function", "plugin", "tool"] and the role in last message must be in ["… |

这些用例的价值在于**建立错误码参照系**：同样是 400，「模型不存在」「消息结构非法」「超出上下文」返回的 `code` 与措辞不同。仅「模型不存在」一项，三条路径就给出三个答案：Chat 404 `model_not_found`、Responses 404 `MODEL_NOT_FOUND`、Anthropic 400 `InvalidParameter`。排障应按 `code` 分支，不要匹配 message。

**协议差异：** OpenAI Responses 对「max_output_tokens = 131,073」返回 200；Anthropic 兼容 对「max_tokens = 131,073」返回 200。服务端未做该校验，调用方不能依赖它兜底，仍需在客户端限制输出长度。

## 十、错误码字典

| HTTP | code | type | 次数 | 代表性 message | 示例用例 |
|---|---|---|---|---|---|
| 400 | `invalid_parameter_error` | `invalid_request_error` | 9 | Range of input length should be [1, 991808] | `text_en_openai` |
| 400 | `InvalidParameter` | — | 9 | Range of input length should be [1, 991808] | `text_en_anthropic` |
| 400 | `InvalidParameter` | `invalid_request_error` | 6 | <400> InternalError.Algo.InvalidParameter: The image length and width do not meet the model restrictions. [height:9 or width:9 mus… | `fmt_min_9px_responses` |
| 413 | `BadRequest.TooLarge` | — | 4 | Exceeded limit on max bytes per data-uri item : 33554432 | `image_real_anthropic` |
| 400 | `BadRequest.TooLarge` | — | 2 | Exceeded limit on max number of data-uri items : 250 | `image_count_anthropic` |
| 413 | — | `invalid_request_error` | 2 | Exceeded limit on max bytes per data-uri item : 52428800 | `image_real_openai` |
| 0（无响应） | — | — | 1 | URLError: [Errno 32] Broken pipe | `body_size_anthropic` |
| 400 | — | `invalid_request_error` | 1 | Exceeded limit on max number of data-uri items : 250 | `image_count_openai` |
| 404 | `model_not_found` | `invalid_request_error` | 1 | Model not exist. | `unknown_model_openai` |
| 404 | `MODEL_NOT_FOUND` | `invalid_request_error` | 1 | Model not found: qwen3.8-flash-does-not-exist | `unknown_model_responses` |

## 十一、与官方文档的对照

| 项目 | 文档值 | 实测 | 结论 |
|---|---|---|---|
| 最大输入（OpenAI Chat） | 991,808 tokens | 4.4 MB 英文文本被拒，错误信息给出同一数值 | 一致 |
| 最大输入（OpenAI Responses） | 991,808 tokens | 约 3.43 MB 起静默截断（上报 800,017 tokens） | 未执行（截断而非拒绝） |
| 最大输入（Anthropic 兼容） | 991,808 tokens | 4.4 MB 英文文本被拒，错误信息给出同一数值 | 一致 |
| 单图原图 ≤ 20 MB（OpenAI Chat） | 20 MB | 真实像素 36.38 MB 仍 200 | 未执行 |
| Data URI 上限（OpenAI Chat） | 20 MB | 52,428,800 字节（50 MiB） | 高于文档值 2.5 倍 |
| 单图原图 ≤ 20 MB（OpenAI Responses） | 20 MB | 真实像素 36.38 MB 仍 200 | 未执行 |
| Data URI 上限（OpenAI Responses） | 20 MB | 52,428,800 字节（50 MiB） | 高于文档值 2.5 倍 |
| 单图原图 ≤ 20 MB（Anthropic 兼容） | 20 MB | 真实像素 23.95 MB 仍 200 | 未执行 |
| Data URI 上限（Anthropic 兼容） | 32 MB | 33,554,432 字节（32 MiB） | 一致 |
| 请求体 ≤ 64 MB（OpenAI Chat） | 64 MB | 110 MB 仍 200 | 未执行 |
| 请求体 ≤ 64 MB（OpenAI Responses） | 64 MB | 110 MB 仍 200 | 未执行 |
| 请求体 ≤ 64 MB（Anthropic 兼容） | 64 MB | 62.5 / 65 MB | 以断连形式生效 |
| Base64 图片张数 | ≤ 250 张 | 250 张通过 / 251 张拒绝 | 一致 |
| 最小边长 | > 10 px | 9 px 拒绝 / 10 px 通过 | 实际阈值为 ≥10 px，比文档宽松 1 px |
| 宽高比 | ≤ 200:1 | 210:1 被拒 | 一致 |
| 4K–8K 仅 JPEG/PNG | 仅 JPEG/PNG | 7680×4320 WEBP 通过 | 未执行 |

「未执行」指**没有观察到该限制**，不代表官方文档错误：文档描述的是模型能力的**上限承诺**，实现可选择更宽松；但从工程角度，不能把它当作可依赖的拒绝条件——超限请求会被接受并正常计费。

## 十二、工程建议

1. **不要把 Responses 的「不报错」当成限制更宽松。** 它在约 3.43 MB 处**静默截断**输入：不返回 4xx、不提示、超出部分不计费但直接丢弃。长文档走该路径必须由客户端按字节切分，建议单请求文本控制在 3 MB 以内。
2. **客户端必须自己卡单图体积，且按 Base64 后的长度算。** 实测上限是 Data URI 50 MiB（Chat / Responses，原图约 37.5 MB）与 32 MiB（Anthropic，原图约 24 MB）；文档的 20 MB 是更保守的承诺，不能当作服务端会替你拦截的护栏——超限图会被照常解码并按 token 计费。
3. **Anthropic 的 `input_tokens` 不是总输入，必须求和。** 按官方口径 `total = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`；实测与 Chat 的 `prompt_tokens` 逐位相等。该兼容层把大部分输入（含图像 token）计入 `cache_read_input_tokens`，只读 `input_tokens` 会明显低估。计费时注意缓存命中价（0.1 元/百万）与未命中价（0.8 元/百万）不同。
4. **文本按 token 预算切分，而不是按 MB。** 上限 991,808 tokens 对应约 4.4 MB 英文或 4.5 MB 中文——两者几乎相同，因为汉字虽然 token 密度高，但每字占 3 字节。
5. **多图请求同时受三条约束：** 张数 ≤ 250（硬限制，精确执行）、单图 Data URI ≤ 50 MiB（Chat / Responses）/ 32 MiB（Anthropic）、整体请求体在 Anthropic 侧约 64 MB 会断连，Chat / Responses 的上限是 128 MiB。按 250 张、单图 2 MB 规划最稳。
6. **错误分支按 `code` 实现。** 同一语义在三条路径下的状态码与 code 都不同（模型不存在：Chat 404 `model_not_found`、Responses 404 `MODEL_NOT_FOUND`、Anthropic 400 `InvalidParameter`），message 还含可变数值。
7. **对「断连」做显式处理。** 请求体超限时 Anthropic 不返回 413，而是直接重置连接，客户端应把大体积上传的 `Broken pipe` 与网络抖动区分开（例如按体积阈值预判）。

## 十三、附录

### 复现方式

```bash
source ~/.zshrc          # 提供 DASHSCOPE_WORKSPACE_ID / DASHSCOPE_API_KEY
python3 run_tests.py --suite all
```

失败用例的复现脚本在 `results/curl/`（共 36 个用例，每个用例提供 `.sh` 与 `.cmd` 两份）。Unix 用 curl 重放，Windows 用 `--replay`；两者都调用同一段构建逻辑还原请求体，因此上百 MB 的载荷也能一键重放。

### 产物

- `results/report.md`：本报告
- `results/results.json`：全部记录与边界结论
- `results/records.jsonl`：逐请求流水，支持 `--resume` / `--only` 增量补测
- `results/curl/`：失败用例的可复现脚本

测试图片全部在内存中生成（体积可精确控制、不落盘），无需清理临时文件。

### 边界终值

本报告的边界表是**本次运行阶梯的止点**。请求体与单图体积的字节级终值
（128 MiB / 原图 39,321,582 B）见 `docs/limits-summary.md`。

### 可信度说明

- 边界是**区间**而非精确值：受 tokenizer 分段与网关实现影响，临界点可能有几 KB 抖动。
- Responses 的截断点由「上报 tokens ÷ 实测密度」反算，精度约 ±0.5%，已用中英文两组数据交叉验证（均落在 3.43 MB）。
- 4xx 中带 `timed out` / `try again` 等标记的响应按抖动处理，不计入边界；请求体用例的「连接重置」则显式按超限处理并标注。
- 单次运行的结论受网络状况影响，可用 `--only` / `--force` 重跑单个维度或整条路径。
