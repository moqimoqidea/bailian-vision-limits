# 单图原始体积：字节级边界（三模型）

结论：上限 39,321,582 B（37.50 MiB）通过，39,321,583 B 被 413 拒绝；
对应 Data URI 52,428,798 / 52,428,802 B，即 50 MiB 上限且计入 `data:image/png;base64,` 前缀。

## qwen3.8-flash

# qwen3.8-flash · image 推进结果

| 点位 | 请求体 | 结果 | 错误 |
|---|---|---|---|
| 39,321,582 B | 52,429,033 B | 通过 |  |
| 39,321,583 B | 52,429,037 B | HTTP 413 | Exceeded limit on max bytes per data-uri item : 52428800 |

## qwen3.8-max

# qwen3.8-max · image 推进结果

| 点位 | 请求体 | 结果 | 错误 |
|---|---|---|---|
| 39,321,582 B | 52,429,031 B | 通过 |  |
| 39,321,583 B | 52,429,035 B | HTTP 413 | Exceeded limit on max bytes per data-uri item : 52428800 |

## qwen4-max

# qwen4-max · image 推进结果

| 点位 | 请求体 | 结果 | 错误 |
|---|---|---|---|
| 39,321,582 B | 52,429,029 B | 通过 |  |
| 39,321,583 B | 52,429,033 B | HTTP 413 | Exceeded limit on max bytes per data-uri item : 52428800 |

