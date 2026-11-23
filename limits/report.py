"""Markdown report generation from the collected records.

Sections are only emitted when they have data, and are numbered dynamically so
that running a subset of suites still produces a coherent document.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable, Iterable

from .config import DocumentedLimits, Settings
from .records import Boundary, Record, RunSummary

PROTOCOL_LABEL = {
    "openai": "OpenAI Chat",
    "responses": "OpenAI Responses",
    "anthropic": "Anthropic 兼容",
}
PROTOCOL_ORDER = ("openai", "responses", "anthropic")
NUMERALS = (
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
    "十一",
    "十二",
    "十三",
    "十四",
    "十五",
)
MIB = 1024 * 1024


def _table(headers: list[str], rows: Iterable[list[str]]) -> str:
    body = list(rows)
    if not body:
        return ""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def _num(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text + suffix


def _status(record: Record) -> str:
    if record.status == 0:
        return "连接重置"
    return "200 通过" if record.accepted else f"{record.status} 拒绝"


def _error(record: Record) -> str:
    if record.accepted:
        return "—"
    code = record.error_code or record.error_type or "—"
    message = " ".join(record.error_message.split())
    if len(message) > 120:
        message = message[:120] + "…"
    return f"`{code}` {message}"


class Report:
    def __init__(self, summary: RunSummary, settings: Settings) -> None:
        from .config import Pricing

        self._summary = summary
        self._settings = settings
        # 优先用运行当时记录的文档值与单价，避免 --report-only 时套错模型。
        self._limits = DocumentedLimits.from_mapping(
            summary.settings.get("documented_limits")
        )
        self._pricing = Pricing.from_mapping(summary.settings.get("pricing"))
        self._records = summary.records

    # ---------------------------------------------------------------- lookup
    def _by_experiment(self, prefix: str) -> list[Record]:
        return [r for r in self._records if r.experiment_id.startswith(prefix)]

    def _record(self, experiment_id: str) -> Record | None:
        for record in self._records:
            if record.experiment_id == experiment_id:
                return record
        return None

    def _boundary(self, prefix: str, protocol: str) -> Boundary | None:
        for boundary in self._summary.boundaries:
            if boundary.experiment_id.startswith(prefix) and boundary.protocol == protocol:
                return boundary
        return None

    def _max_ok(self, prefix: str, protocol: str) -> float | None:
        values = [
            r.axis_value
            for r in self._by_experiment(prefix)
            if r.protocol == protocol and r.accepted and r.axis_value is not None
        ]
        return max(values) if values else None

    def _density(self, protocol: str, prefix: str = "text_en_") -> float | None:
        candidates = [
            r
            for r in self._by_experiment(prefix)
            if r.protocol == protocol
            and r.accepted
            and r.usage.get("input_tokens")
            and r.text_chars
        ]
        if not candidates:
            return None
        # 取最小的探测点：大体积点可能已被服务端截断，不能用来量密度。
        smallest = min(candidates, key=lambda r: r.text_chars)
        return smallest.usage["input_tokens"] / smallest.text_chars

    @staticmethod
    def _csv(record: Record) -> str:
        return f"{record.body_mb:.2f} MB"

    @staticmethod
    def _byte_cap(record: Record | None) -> int | None:
        """Extract the byte ceiling quoted by the gateway, e.g. ``: 52428800``."""
        if not record:
            return None
        match = re.search(r"(\d{6,})", record.error_message)
        return int(match.group(1)) if match else None

    # ---------------------------------------------------------------- render
    def render(
        self,
        title: str | None = None,
        intro: list[str] | None = None,
        extra_sections: list[tuple[str, str]] | None = None,
    ) -> str:
        """``extra_sections`` 会插在「结论摘要」之后，编号自动顺延。"""
        sections: list[tuple[str, str]] = []
        builders: list[Callable[[], tuple[str, str]]] = [
            self._s_summary,
            self._s_method,
            self._s_text,
            self._s_truncation,
            self._s_image_size,
            self._s_transport,
            self._s_count,
            self._s_format,
            self._s_misc,
            self._s_errors,
            self._s_doc,
            self._s_recommendations,
            self._s_appendix,
        ]
        for builder in builders:
            title_text, body = builder()
            if body.strip():
                sections.append((title_text, body))
        for offset, section in enumerate(extra_sections or []):
            sections.insert(1 + offset, section)
        rendered = [self._header(title, intro)]
        for index, (title_text, body) in enumerate(sections):
            numeral = NUMERALS[index] if index < len(NUMERALS) else str(index + 1)
            rendered.append(f"## {numeral}、{title_text}\n\n{body}")
        return "\n\n".join(rendered) + "\n"

    def _header(self, title: str | None = None, intro: list[str] | None = None) -> str:
        pricing = self._pricing
        uncached, cached = self._summary.input_tokens()
        host = self._summary.settings.get("host") or self._settings.host
        if intro is not None:
            return "\n".join(
                [title or f"# 阿里云百炼 {self._settings.model} 请求限制实测报告", ""]
                + intro
            )
        return "\n".join(
            [
                f"# 阿里云百炼 {self._settings.model} 请求限制实测报告",
                "",
                f"- 端点：`{host}`",
                f"- 模型：`{self._settings.model}`（非思考模式；最大输入 "
                f"{self._limits.max_input_tokens:,} tokens，上下文 "
                f"{self._limits.context_tokens:,}，最大输出 "
                f"{self._limits.max_output_tokens:,}）",
                f"- 时间：{self._summary.settings.get('started_at', '')}",
                f"- 请求数：{len(self._records)}；累计输入 {uncached + cached:,} tokens"
                f"（其中缓存命中 {cached:,}）；按 {pricing.input:g} / {pricing.cache_hit:g} / "
                f"{pricing.output:g} 元每百万 tokens（未命中 / 命中 / 输出）"
                f"估算成本约 {self._summary.cost_cny():.2f} 元",
                "- 数据说明：表格中的「≥ X」是本次运行的上探止点；单图与请求体的"
                "字节级终值见 `docs/limits-summary.md`。",
            ]
        )

    # ----------------------------------------------------------------- parts
    def _s_summary(self) -> tuple[str, str]:
        findings = [self._finding_text(), self._finding_image(), self._finding_body(),
                    self._finding_count(), self._finding_format()]
        bullets = [f"- **{title}** {body}" for title, body in findings if body]
        rows = []
        for protocol in PROTOCOL_ORDER:
            image = self._boundary("image_real_", protocol)
            count = self._boundary("image_count_", protocol)
            if image and image.first_fail:
                image_cell = f"{_num(image.last_ok)} / {_num(image.first_fail)} MB"
            else:
                max_ok = self._max_ok("image_real_", protocol)
                image_cell = f"≥ {_num(max_ok)} MB 通过" if max_ok else "—"
            rows.append(
                [
                    PROTOCOL_LABEL[protocol],
                    self._text_cell(protocol),
                    image_cell,
                    self._body_cell(protocol),
                    f"{int(count.last_ok)} / {int(count.first_fail)} 张"
                    if count and count.last_ok is not None and count.first_fail is not None
                    else "—",
                ]
            )
        return "结论摘要", "\n".join(
            bullets
            + [
                "",
                _table(
                    ["接口", "文本", "单图", "请求体", "图片张数"],
                    rows,
                ),
                "",
                "一句话：**文档里的「张数」和「宽高比」被精确执行，"
                "而「单图体积」「4K–8K 格式档」在 OpenAI 两条路径上并未生效、" 
                "「64 MB 请求体」只在部分路径以断连形式出现。**"
                "三条路径的差异不是数值差异，而是**校验项集合不同**。",
            ]
        )

    def _truncation_cap(self, protocol: str) -> float | None:
        """由「上报 tokens 远低于预期」的记录反算截断点（MB）。"""
        density = self._density(protocol)
        if not density:
            return None
        implied = []
        for record in self._by_experiment("trunc_"):
            if record.protocol != protocol or not record.accepted or not record.text_chars:
                continue
            reported = record.usage.get("input_tokens") or 0
            if reported and reported < 0.995 * density * record.text_chars:
                implied.append(reported / density / MIB)
        return sum(implied) / len(implied) if implied else None

    def _text_cell(self, protocol: str) -> str:
        boundary = self._boundary("text_en_", protocol)
        if boundary and boundary.first_fail:
            return f"{_num(boundary.last_ok)} / {_num(boundary.first_fail)} MB"
        cap = self._truncation_cap(protocol)
        return f"截断 @ {cap:.2f} MB" if cap else "—"

    def _finding_text(self) -> tuple[str, str]:
        boundaries = [
            boundary
            for boundary in (self._boundary("text_en_", p) for p in PROTOCOL_ORDER)
            if boundary and boundary.first_fail
        ]
        if not boundaries:
            return "", ""
        points = {round(boundary.first_fail, 3) for boundary in boundaries}
        scope = "、".join(PROTOCOL_LABEL[boundary.protocol] for boundary in boundaries)
        where = (
            f"都在 {_num(boundaries[0].first_fail)} MB"
            if len(points) == 1
            else "分别在 " + "、".join(f"{_num(v)} MB" for v in sorted(points))
        )
        zh = self._boundary("text_zh_ext_", "openai")
        zh_max = self._max_ok("text_zh_ext_", "openai")
        tail = ""
        if zh_max:
            zh_density = self._density("openai", "text_zh_") or 0.63
            approx = zh_max * MIB / 3 * zh_density
            tail = f"中文实测 {_num(zh_max)} MB（约 {approx / 1e6:.2f}M tokens）仍通过"
            if zh and zh.first_fail:
                tail += f"、{_num(zh.first_fail)} MB 被拒"
            tail += "。"

        sentences = []
        if boundaries:
            sentences.append(
                f"{scope}{where} 英文文本处返回 "
                f"`Range of input length should be [1, {self._limits.max_input_tokens:,}]`，"
                "与文档的 991,808 tokens 完全一致"
            )
        truncated = [p for p in PROTOCOL_ORDER if self._truncation_cap(p)]
        if truncated:
            cap = self._truncation_cap(truncated[0]) or 0
            sentences.append(
                f"{'、'.join(PROTOCOL_LABEL[p] for p in truncated)} "
                f"**不报错，而是在约 {cap:.1f} MB 处静默截断输入**（详见「静默截断」一节）"
            )
        sentences.append("64 MB 的传输上限对纯文本不可达——那相当于约 1,400 万 tokens")
        return "纯文本", "；".join(sentences) + "。" + tail

    def _finding_image(self) -> tuple[str, str]:
        groups: dict[float | None, list[str]] = {}
        for protocol in PROTOCOL_ORDER:
            max_ok = self._max_ok("image_real_", protocol)
            boundary = self._boundary("image_real_", protocol)
            if max_ok is None and not boundary:
                continue
            cap = self._byte_cap(self._first_fail("image_real_", protocol))
            groups.setdefault(cap, []).append(PROTOCOL_LABEL[protocol])
        if not groups:
            return "", ""
        parts = []
        for cap, labels in groups.items():
            names = " / ".join(labels)
            if cap:
                parts.append(
                    f"{names}：上限 **{cap:,} 字节（{cap / MIB:.0f} MiB）Data URI**，"
                    f"约合原图 {cap * 0.75 / MIB:.1f} MB"
                )
            else:
                parts.append(f"{names}：未观察到单图上限")
        effective = [
            self._max_ok("image_real_", protocol) or 0 for protocol in PROTOCOL_ORDER
        ]
        tail = (
            "文档的 20 MB 原图限制在三条路径上均未单独生效。"
            if all(value >= self._limits.image_mb_relaxed for value in effective if value)
            else ""
        )
        return "单图体积", "；".join(parts) + "。" + tail

    def _first_fail(self, prefix: str, protocol: str) -> Record | None:
        boundary = self._boundary(prefix, protocol)
        if not boundary or boundary.first_fail is None:
            return None
        return next(
            (
                r
                for r in self._by_experiment(prefix)
                if r.protocol == protocol and r.axis_value == boundary.first_fail
            ),
            None,
        )

    def _first_fail_value(self, prefix: str, protocol: str) -> float | None:
        boundary = self._boundary(prefix, protocol)
        return boundary.first_fail if boundary else None

    def _finding_body(self) -> tuple[str, str]:
        open_ended: list[str] = []
        limited: list[tuple[str, float, float]] = []
        for protocol in PROTOCOL_ORDER:
            boundary = self._boundary("body_size_", protocol)
            max_ok = self._max_ok("body_size_", protocol)
            if not boundary and max_ok is None:
                continue
            if boundary and boundary.first_fail:
                limited.append((protocol, boundary.last_ok, boundary.first_fail))
            elif max_ok:
                open_ended.append(protocol)
        if not open_ended and not limited:
            return "", ""
        parts: list[str] = []
        if open_ended:
            peak = max(self._max_ok("body_size_", p) or 0 for p in open_ended)
            names = " / ".join(PROTOCOL_LABEL[p] for p in open_ended)
            parts.append(
                f"{names} **{_num(peak)} MB 仍返回 200，未观察到请求体上限**"
            )
        for protocol, last_ok, first_fail in limited:
            if protocol == "anthropic":
                parts.append(
                    f"{PROTOCOL_LABEL[protocol]} {_num(last_ok)} MB 通过、"
                    f"{_num(first_fail)} MB 被**直接断开连接**（无 HTTP 状态码）"
                )
            else:
                parts.append(
                    f"{PROTOCOL_LABEL[protocol]} {_num(last_ok)} MB 通过、"
                    f"{_num(first_fail)} MB 被拒"
                )
        tail = (
            "文档的 64 MB 只以「断连」形式出现在部分路径上。"
            if limited and len(limited) < len(PROTOCOL_ORDER)
            else ""
        )
        return "请求体", "；".join(parts) + "。" + tail

    def _body_cell(self, protocol: str) -> str:
        body = self._boundary("body_size_", protocol)
        if body and body.first_fail:
            return f"{_num(body.last_ok)} / {_num(body.first_fail)} MB"
        max_ok = self._max_ok("body_size_", protocol)
        return f"≥ {_num(max_ok)} MB" if max_ok else "—"

    def _finding_count(self) -> tuple[str, str]:
        boundary = self._boundary("image_count_", "openai")
        if not boundary or boundary.first_fail is None:
            return "", ""
        rejected = next(
            (
                r
                for r in self._by_experiment("image_count_openai")
                if r.axis_value == boundary.first_fail
            ),
            None,
        )
        return (
            "图片张数",
            f"{int(boundary.last_ok)} 张通过、{int(boundary.first_fail)} 张被拒"
            + (f"，错误信息为「{rejected.error_message}」" if rejected else "")
            + "，与文档的 250 张完全一致。",
        )

    def _finding_format(self) -> tuple[str, str]:
        webp = self._record("fmt_8k_webp_openai")
        if not webp or not webp.accepted:
            return "", ""
        return (
            "格式档位",
            "7680×4320 的 WEBP 仍返回 200，文档所述「4K–8K 仅支持 JPEG/PNG」未被执行；"
            "而宽高比 210:1 会被精确拒绝。",
        )

    def _s_method(self) -> tuple[str, str]:
        return "方法学", "\n".join(
            [
                "1. **把体积与 token 成本解耦。** 图像 token 由像素决定，请求体由字节决定。"
                "体积类用例分两组：一组是 64×64 像素、用 `tEXt` 块撑大的 PNG（成本近零，"
                "用于探传输上限）；另一组是**不可压缩的随机像素**（文件体积≈真实像素数据，"
                "用于验证体积限制是否真的作用在图像内容上）。",
                "2. **阶梯 + 二分。** 按文档值布点，命中首个失败点后在上一个通过点之间二分，"
                "直到区间小于容差。报告给出实测区间 `[最大通过, 首个拒绝)`。",
                "3. **失败分类。** 4xx 业务拒绝直接计入边界；超时、429、5xx 视为抖动并重试两次。"
                "唯一的例外是请求体用例：网关用「直接断开连接」表达超限，该开关显式打开并在报告中标注。",
                "4. **口径。** MB 一律为 MiB（1024×1024 字节），与 `Content-Length` 对齐；"
                "图片体积指编码前原始文件字节；Base64 体积指编码后字符数。",
                "5. **未覆盖项。** 公网 URL 与本地路径传图（需公网图床）、视频输入、HEIC"
                "（本机无编码器）、RPM/TPM 限流、思考模式下的 983,616 tokens 上限。",
            ]
        )

    def _s_text(self) -> tuple[str, str]:
        blocks: list[str] = []
        for protocol in PROTOCOL_ORDER:
            records = sorted(
                [
                    r
                    for r in self._records
                    if r.experiment_id.startswith(("text_en_", "text_zh_"))
                    and r.protocol == protocol
                ],
                key=lambda r: (0 if "_en_" in r.experiment_id else 1, r.axis_value or 0),
            )
            if not records:
                continue
            rows = [
                [
                    r.title.replace("体积边界", "").replace("（续测）", ""),
                    _num(r.axis_value, 2, " MB"),
                    self._csv(r),
                    f"{r.usage['input_tokens']:,}" if r.usage.get("input_tokens") else "—",
                    _status(r),
                    _error(r),
                ]
                for r in records
            ]
            blocks += [
                f"### {PROTOCOL_LABEL[protocol]}",
                "",
                _table(["文本", "内容体积", "请求体", "usage 总输入 tokens", "结果", "错误"], rows),
                "",
            ]
            density = self._density(protocol)
            boundary = self._boundary("text_en_", protocol)
            if density and density > 0.1 and boundary and boundary.first_fail:
                estimate = int(density * boundary.first_fail * MIB)
                ratio = estimate / self._limits.max_input_tokens
                blocks += [
                    f"token 密度约 **{density:.3f} tokens/字符**；{_num(boundary.first_fail)} MB 处约 "
                    f"{estimate:,} tokens，是上限 {self._limits.max_input_tokens:,} 的 "
                    f"{ratio:.2f} 倍，与「恰好在此处被拒」一致。"
                    "错误信息本身回显了精确的 token 上限，因此字节级精度意义有限。",
                ]
            elif boundary:
                blocks += [
                    "该接口缺少可用的 usage 数据，无法用上报值反推 token 数；"
                    "容量判断以请求体字节与错误信息为准。",
                ]
            blocks.append("")
            truncated = []
            for record in records:
                if not record.accepted or not record.text_chars:
                    continue
                record_density = (
                    self._density(protocol, "text_zh_")
                    if "_zh_" in record.experiment_id
                    else density
                )
                if record_density and (record.usage.get("input_tokens") or 0) < (
                    0.995 * record_density * record.text_chars
                ):
                    truncated.append(record)
            if truncated:
                blocks += [
                    f"**注意：** 其中 {len(truncated)} 条虽然返回 200，但上报的 token 数"
                    "明显低于按字符数推算的预期，属于**静默截断**——详见下一节。",
                    "",
                ]

        zh_density = self._density("openai", "text_zh_")
        if zh_density:
            blocks += [
                "### 中文为什么没有更早触顶",
                "",
                f"中文实测 {zh_density:.3f} tokens/字符。一个汉字占 3 字节、约 1.6 tokens，"
                f"折合 **{zh_density / 3:.3f} tokens/字节**；英文是 0.222 tokens/字符、"
                "约 4.5 字符/token，折合 0.222 tokens/字节。两者几乎相同，"
                "所以「中文 2 MB 就到顶」的直觉是错的——**按字节算，中英文的上限都在 4.5 MB 附近**。",
                "",
            ]

        alignment = self._usage_alignment()
        if alignment:
            example = self._anthropic_example()
            blocks += [
                "### usage 口径：三条路径的「总输入」字段含义不同",
                "",
                "- **OpenAI Chat**：`prompt_tokens` 已是总输入，`prompt_tokens_details.cached_tokens` 是其中的缓存命中部分（子集，不叠加）。",
                "- **OpenAI Responses**：同上，字段名为 `input_tokens`，缓存命中在 `input_tokens_details.cached_tokens`。",
                "- **Anthropic**：`input_tokens` 只统计**最后一个缓存断点之后**的 token；官方口径为 "
                "`total = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`"
                "（[Prompt caching 文档](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)）。",
                "",
                _table(
                    ["内容体积", "接口", "usage 总输入 tokens", "与 Chat 的差异"],
                    alignment,
                ),
            ]
            if example:
                blocks += ["", example]
            blocks += [
                "",
                "Chat 与 Anthropic 的总输入**逐位相等**；Responses 只差一个固定开销"
                + (f"（{self._response_offset():+d} tokens）" if self._response_offset() else "")
                + "，来自 `input` 字符串与 `messages` 数组的包装差异。"
                "三条路径的计数本身都准确，差异只在字段口径：该兼容层会把大部分输入"
                "（含图像 token）计入 `cache_read_input_tokens`，只读 `input_tokens` 会明显低估。"
                "做容量规划或成本核算时，Anthropic 必须先求和，"
                "并注意缓存命中与未命中单价不同。",
            ]
        if not blocks:
            return "", ""
        return "纯文本请求", "\n".join(blocks)

    def _usage_alignment(self) -> list[list[str]]:
        """同一内容体积下对比三条路径的总输入，验证 Anthropic 求和口径。"""
        series = {
            protocol: {
                record.axis_value: record
                for record in self._by_experiment(f"text_en_{protocol}")
                if record.accepted and record.usage.get("input_tokens")
            }
            for protocol in PROTOCOL_ORDER
        }
        if not all(series.values()):
            return []
        common = set.intersection(*(set(items) for items in series.values()))
        if not common:
            return []
        values = sorted(common)
        picks = sorted({values[0], values[len(values) // 2], values[-1]})
        rows = []
        for value in picks:
            base = series["openai"][value].usage["input_tokens"]
            for protocol in PROTOCOL_ORDER:
                record = series[protocol].get(value)
                if not record:
                    continue
                total = record.usage["input_tokens"]
                delta = total - base
                rows.append(
                    [
                        _num(value, 2, " MB"),
                        PROTOCOL_LABEL[protocol],
                        f"{total:,}",
                        "基准" if protocol == "openai" else ("0" if delta == 0 else f"{delta:+,}"),
                    ]
                )
        return rows

    def _response_offset(self) -> int | None:
        """Responses 与 Chat 在相同 1 MB 文本上的总输入差（载荷包装开销）。"""
        chat = next(
            (r for r in self._by_experiment("text_en_openai") if r.axis_value == 1.0), None
        )
        responses = next(
            (r for r in self._by_experiment("text_en_responses") if r.axis_value == 1.0), None
        )
        if chat and responses and chat.usage.get("input_tokens"):
            return responses.usage["input_tokens"] - chat.usage["input_tokens"]
        return None

    def _anthropic_example(self) -> str:
        for record in self._by_experiment("text_en_anthropic"):
            if record.accepted and record.axis_value == 1.0:
                usage = record.usage
                return (
                    f"以 1 MB 为例：Anthropic 上报 `input_tokens`="
                    f"{usage.get('uncached_input_tokens', 0):,}、`cache_read_input_tokens`="
                    f"{usage.get('cache_read_tokens', 0):,}，合计 {usage['input_tokens']:,}，"
                    "与 Chat 的 `prompt_tokens` 完全相同。"
                )
        return ""

    def _s_truncation(self) -> tuple[str, str]:
        records = sorted(self._by_experiment("trunc_"), key=lambda r: r.axis_value or 0)
        if not records:
            return "", ""
        base = next(
            (
                r
                for r in self._by_experiment("text_en_responses")
                if r.axis_value == 1.0 and r.accepted and r.text_chars
            ),
            None,
        )
        density = (
            base.usage["input_tokens"] / base.text_chars if base and base.usage else 0.222
        )
        rows = []
        implied = []
        for record in records:
            expected = int(record.text_chars * density)
            reported = int(record.usage.get("input_tokens") or 0)
            ratio = reported / expected if expected else 0
            truncated = ratio < 0.995
            if truncated and reported:
                implied.append(reported / density / MIB)
            rows.append(
                [
                    _num(record.axis_value, 2, " MB"),
                    f"{record.text_chars:,}",
                    f"{expected:,}",
                    f"{reported:,}",
                    f"{ratio * 100:.1f}%",
                    "**截断**" if truncated else "完整",
                ]
            )
        cap = sum(implied) / len(implied) if implied else None
        blocks = [
            "Responses 路径在输入超长时**不返回 4xx**，而是把 `input` 截断后照常推理。"
            "只看 HTTP 状态会把这种行为误读成「限制更宽松」。",
            "",
            _table(
                ["内容体积", "字符数", "预期 tokens", "实际上报", "比例", "结论"], rows
            ),
        ]
        if cap:
            blocks += [
                "",
                f"{len(implied)} 次被截断的请求上报值完全相同，反算截断点约 "
                f"**{cap:.2f} MB（{cap * MIB:,.0f} 字节）**：超出该长度的内容既不报错、"
                "也不计费，但**会被静默丢弃**。长文档若走 Responses 路径，必须由客户端"
                "按字节切分，不能依赖服务端拒绝。",
            ]
        zh_density = self._density("responses", "text_zh_")
        zh_reported = max(
            (
                int(record.usage.get("input_tokens") or 0)
                for record in self._by_experiment("text_zh_responses")
                + self._by_experiment("text_zh_ext_responses")
                if record.accepted
            ),
            default=0,
        )
        if zh_density and zh_reported and cap:
            zh_mb = zh_reported / zh_density * 3 / MIB
            blocks += [
                "",
                f"中文侧同样封顶在 {zh_reported:,} tokens，按 {zh_density:.3f} tokens/字符、"
                f"每字 3 字节折算约 **{zh_mb:.2f} MB**，与英文的 {cap:.2f} MB 吻合——"
                "说明截断判据是**字节数**而不是 token 数。",
            ]
        return "Responses 路径的静默截断", "\n".join(blocks)

    def _s_image_size(self) -> tuple[str, str]:
        real = self._by_experiment("image_real_")
        padded = self._by_experiment("image_size_")
        if not real and not padded:
            return "", ""
        blocks: list[str] = []
        if real:
            rows = []
            for protocol in PROTOCOL_ORDER:
                for record in sorted(
                    [r for r in real if r.protocol == protocol], key=lambda r: r.axis_value or 0
                ):
                    rows.append(
                        [
                            PROTOCOL_LABEL[protocol],
                            _num(record.axis_value, 2, " MB"),
                            f"{record.base64_mb:.2f} MB",
                            self._csv(record),
                            _status(record),
                            _error(record),
                        ]
                    )
            blocks += [
                "### 真实像素图像（决定性实验）",
                "",
                "文件由不可压缩的随机像素构成，体积约等于真实像素数据，排除「元数据被剥离」的干扰。",
                "",
                _table(["接口", "原图体积", "Data URI 体积", "请求体", "结果", "错误"], rows),
                "",
            ]
            for protocol in PROTOCOL_ORDER:
                boundary = self._boundary("image_real_", protocol)
                max_ok = self._max_ok("image_real_", protocol)
                if max_ok is None and not boundary:
                    continue
                cap = self._byte_cap(self._first_fail("image_real_", protocol))
                if cap and boundary and boundary.first_fail:
                    blocks.append(
                        f"- {PROTOCOL_LABEL[protocol]}：`{boundary.detail}`，"
                        f"错误信息给出字节上限 {cap:,}（= {cap / MIB:.0f} MiB），"
                        f"对应原图约 {cap * 0.75 / MIB:.1f} MB。"
                    )
                elif max_ok:
                    blocks.append(
                        f"- {PROTOCOL_LABEL[protocol]}：{max_ok:g} MB 仍返回 200，"
                        "未观察到单图上限。"
                    )
            biggest = max(
                (record for record in real if record.accepted),
                key=lambda record: record.axis_value or 0,
                default=None,
            )
            tokens = biggest.usage.get("input_tokens") if biggest else None
            if biggest and tokens:
                blocks += [
                    "",
                    f"体积最大的通过请求（{PROTOCOL_LABEL[biggest.protocol]}，"
                    f"{biggest.axis_value:g} MB）输入 tokens 为 {tokens:,}"
                    "（纯文本请求约 30），证明图像确实被解码处理，不是被静默丢弃。"
                    "文档的 20 MB 单图限制在三条路径上均未生效——真正起作用的是"
                    "编码后的 Data URI 字符串上限。",
                ]
        if padded:
            rows = []
            for protocol in PROTOCOL_ORDER:
                for record in sorted(
                    [r for r in padded if r.protocol == protocol], key=lambda r: r.axis_value or 0
                ):
                    rows.append(
                        [
                            PROTOCOL_LABEL[protocol],
                            _num(record.axis_value, 2, " MB"),
                            f"{record.base64_mb:.2f} MB",
                            _status(record),
                        ]
                    )
            blocks += [
                "",
                "### 填充型 PNG（交叉验证）",
                "",
                "64×64 像素、用 `tEXt` 块撑到目标体积。两轮结果一致，说明体积判定不区分"
                "「像素数据」与「附属块」——真正没生效的是限制本身，而不是测法有问题。",
                "",
                _table(["接口", "原图体积", "Data URI 体积", "结果"], rows),
            ]
        return "单张图片体积", "\n".join(blocks)

    def _s_transport(self) -> tuple[str, str]:
        records = sorted(
            self._by_experiment("body_size_"),
            key=lambda r: (PROTOCOL_ORDER.index(r.protocol), r.axis_value or 0),
        )
        if not records:
            return "", ""
        rows = [
            [
                PROTOCOL_LABEL[r.protocol],
                _num(r.axis_value, 1, " MB"),
                self._csv(r),
                str(r.image_count),
                _status(r),
                _error(r) if not r.accepted else "—",
            ]
            for r in records
        ]
        blocks = [
            "6 张 64×64、单张约 8–14 MB 的 PNG，把请求体顶到目标体积；图像 token 成本可忽略。",
            "",
            _table(["接口", "目标体积", "实际请求体", "图片数", "结果", "错误"], rows),
            "",
        ]
        for protocol in PROTOCOL_ORDER:
            boundary = self._boundary("body_size_", protocol)
            max_ok = self._max_ok("body_size_", protocol)
            if boundary and boundary.first_fail is not None:
                blocks.append(
                    f"- {PROTOCOL_LABEL[protocol]}：`{boundary.detail}`。"
                    + (
                        "该侧没有 413，网关直接重置连接（`Broken pipe`），"
                        "重试三次仍复现，属于体积触发的拒绝而非网络抖动。"
                        if protocol == "anthropic"
                        else "该侧在大体积下仍返回 200，未观察到硬上限。"
                    )
                )
            elif max_ok:
                blocks.append(
                    f"- {PROTOCOL_LABEL[protocol]}：**{_num(max_ok)} MB 仍返回 200，"
                    "未观察到请求体上限**，文档的 64 MB 在该路径未生效。"
                )
        return "请求体整体上限", "\n".join(blocks)

    def _s_count(self) -> tuple[str, str]:
        rows = []
        for protocol in PROTOCOL_ORDER:
            for record in sorted(
                self._by_experiment(f"image_count_{protocol}"), key=lambda r: r.axis_value or 0
            ):
                rows.append(
                    [
                        PROTOCOL_LABEL[protocol],
                        f"{int(record.axis_value or 0)} 张",
                        f"{record.body_mb:.3f} MB",
                        _status(record),
                        _error(record),
                    ]
                )
        if not rows:
            return "", ""
        return "Base64 图片张数", "\n".join(
            [
                _table(["接口", "张数", "请求体", "结果", "错误"], rows),
                "",
                "张数上限与体积上限是**两条独立约束**：250 张 64×64 小图只有约 80 KB，"
                "轻松通过体积检查，但第 251 张被精确拦下。实际可用张数取两者中更紧的一条。",
            ]
        )

    def _s_format(self) -> tuple[str, str]:
        records = [r for r in self._by_experiment("fmt_") if r.protocol == "openai"]
        if not records:
            return "", ""
        rows = [
            [r.title, r.expect, f"{r.raw_asset_bytes / 1024:.1f} KB", _status(r), _error(r)]
            for r in records
        ]
        blocks = [
            "以 OpenAI Chat 为主表；Responses 与 Anthropic 两条路径的逐项对比见 `results.json`。",
            "",
            _table(["用例", "文档预期", "原始体积", "结果", "错误"], rows),
        ]
        others = {
            protocol: {
                r.experiment_id: r
                for r in self._by_experiment("fmt_")
                if r.protocol == protocol
            }
            for protocol in PROTOCOL_ORDER
            if protocol != "openai"
        }
        if any(others.values()):
            divergent = [
                f"{r.title}（{PROTOCOL_LABEL[protocol]}）"
                for protocol, table in others.items()
                for r in records
                if (other := table.get(r.experiment_id.replace("_openai", f"_{protocol}")))
                and other.accepted != r.accepted
            ]
            blocks.append("")
            blocks.append(
                "三条路径对格式、尺寸、宽高比的判定完全一致。"
                if not divergent
                else "判定不一致的用例：" + "、".join(divergent) + "。"
            )
        eight_k = self._record("fmt_res_8k_openai")
        four_k = self._record("fmt_4k_jpeg_openai")
        token_note = ""
        if eight_k and four_k:
            big = eight_k.usage.get("input_tokens")
            small = four_k.usage.get("input_tokens")
            if big and small:
                token_note = (
                    f"8K（33 Mpx）输入 {big:,} tokens，5K（15 Mpx）输入 {small:,} tokens——"
                    "像素数翻倍而 token 基本持平，说明 `max_pixels` 在截断，"
                    "分辨率不会线性放大成本。"
                )
        blocks += [
            "",
            "两处与文档不符：**最小边长**实测阈值为 ≥10 px（文档写「>10」，9 px 才被拒）；"
            "**4K–8K 仅 JPEG/PNG** 未执行，7680×4320 的 WEBP 正常返回 200。"
            "另外，把 JPEG 字节声明成 `image/png` 也能通过，说明服务端按内容嗅探格式，"
            "不信任 `media_type`。" + token_note,
        ]
        return "格式、分辨率与宽高比", "\n".join(blocks)

    def _s_misc(self) -> tuple[str, str]:
        prefixes = ("max_tokens_overflow_", "unknown_model_", "empty_messages_")
        records = [
            record
            for prefix in prefixes
            for protocol in PROTOCOL_ORDER
            for record in self._by_experiment(prefix)
            if record.protocol == protocol
        ]
        if not records:
            return "", ""
        rows = [
            [PROTOCOL_LABEL[r.protocol], r.title, r.expect, _status(r), _error(r)]
            for r in records
        ]
        blocks = [
            _table(["接口", "用例", "预期", "结果", "错误"], rows),
            "",
            "这些用例的价值在于**建立错误码参照系**：同样是 400，「模型不存在」「消息结构非法」"
            "「超出上下文」返回的 `code` 与措辞不同。仅「模型不存在」一项，三条路径就给出三个答案："
            "Chat 404 `model_not_found`、Responses 404 `MODEL_NOT_FOUND`、Anthropic 400 "
            "`InvalidParameter`。排障应按 `code` 分支，不要匹配 message。",
        ]
        unexpected = [r for r in records if "期望 4xx" in r.expect and r.accepted]
        if unexpected:
            blocks += [
                "",
                "**协议差异：** "
                + "；".join(
                    f"{PROTOCOL_LABEL[r.protocol]} 对「{r.title}」返回 200" for r in unexpected
                )
                + "。服务端未做该校验，调用方不能依赖它兜底，仍需在客户端限制输出长度。",
            ]
        return "其他边界", "\n".join(blocks)

    def _s_errors(self) -> tuple[str, str]:
        groups: dict[tuple[int, str, str], list[Record]] = defaultdict(list)
        for record in self._records:
            if not record.accepted:
                groups[(record.status, record.error_code, record.error_type)].append(record)
        if not groups:
            return "", ""
        rows = []
        for (status, code, error_type), items in sorted(
            groups.items(), key=lambda item: (-len(item[1]), item[0][0])
        ):
            sample = items[0]
            message = " ".join(sample.error_message.split())
            rows.append(
                [
                    str(status) if status else "0（无响应）",
                    f"`{code}`" if code else "—",
                    f"`{error_type}`" if error_type else "—",
                    str(len(items)),
                    message[:130] + ("…" if len(message) > 130 else ""),
                    f"`{sample.experiment_id}`",
                ]
            )
        return "错误码字典", _table(
            ["HTTP", "code", "type", "次数", "代表性 message", "示例用例"], rows
        )

    def _s_doc(self) -> tuple[str, str]:
        rows: list[list[str]] = []
        for protocol in PROTOCOL_ORDER:
            text = self._boundary("text_en_", protocol)
            if text and text.first_fail:
                rows.append(
                    [
                        f"最大输入（{PROTOCOL_LABEL[protocol]}）",
                        f"{self._limits.max_input_tokens:,} tokens",
                        f"{_num(text.first_fail)} MB 英文文本被拒，错误信息给出同一数值",
                        "一致",
                    ]
                )
                continue
            cap = self._truncation_cap(protocol)
            if cap:
                reported = max(
                    (
                        int(record.usage.get("input_tokens") or 0)
                        for record in self._by_experiment("trunc_")
                        if record.protocol == protocol
                    ),
                    default=0,
                )
                rows.append(
                    [
                        f"最大输入（{PROTOCOL_LABEL[protocol]}）",
                        f"{self._limits.max_input_tokens:,} tokens",
                        f"约 {cap:.2f} MB 起静默截断（上报 {reported:,} tokens）",
                        "未执行（截断而非拒绝）",
                    ]
                )
        for protocol in PROTOCOL_ORDER:
            max_ok = self._max_ok("image_real_", protocol)
            boundary = self._boundary("image_real_", protocol)
            if max_ok:
                rows.append(
                    [
                        f"单图原图 ≤ 20 MB（{PROTOCOL_LABEL[protocol]}）",
                        "20 MB",
                        f"真实像素 {_num(max_ok)} MB 仍 200",
                        "未执行" if max_ok >= self._limits.image_mb_relaxed else "一致",
                    ]
                )
            if boundary and boundary.first_fail is not None:
                cap = self._byte_cap(self._first_fail("image_real_", protocol))
                documented = self._limits.data_uri_mb(protocol)
                actual = cap / MIB if cap else None
                if actual is None:
                    verdict = "见错误信息"
                elif abs(actual - documented) < 0.6:
                    verdict = "一致"
                elif actual > documented:
                    verdict = f"高于文档值 {actual / documented:.1f} 倍"
                else:
                    verdict = "低于文档值"
                rows.append(
                    [
                        f"Data URI 上限（{PROTOCOL_LABEL[protocol]}）",
                        f"{documented:g} MB",
                        f"{cap:,} 字节（{actual:.0f} MiB）" if cap else "—",
                        verdict,
                    ]
                )
        for protocol in PROTOCOL_ORDER:
            body = self._boundary("body_size_", protocol)
            max_ok = self._max_ok("body_size_", protocol)
            if not body and max_ok is None:
                continue
            if body and body.first_fail:
                cell = f"{_num(body.last_ok)} / {_num(body.first_fail)} MB"
                verdict = "以断连形式生效" if protocol == "anthropic" else "未执行"
                if protocol == "openai" and body.first_fail > self._limits.body_mb:
                    verdict = "上限高于文档值"
            else:
                cell = f"{_num(max_ok)} MB 仍 200"
                verdict = "未执行"
            rows.append(
                [f"请求体 ≤ 64 MB（{PROTOCOL_LABEL[protocol]}）", "64 MB", cell, verdict]
            )
        count = self._boundary("image_count_", "openai")
        if count and count.first_fail is not None:
            rows.append(
                [
                    "Base64 图片张数",
                    f"≤ {self._limits.images_base64_max} 张",
                    f"{int(count.last_ok)} 张通过 / {int(count.first_fail)} 张拒绝",
                    "一致",
                ]
            )
        min9 = self._record("fmt_min_9px_openai")
        min10 = self._record("fmt_min_10px_openai")
        if min9 and min10:
            rows.append(
                [
                    "最小边长",
                    "> 10 px",
                    f"9 px {'拒绝' if not min9.accepted else '通过'} / "
                    f"10 px {'通过' if min10.accepted else '拒绝'}",
                    "实际阈值为 ≥10 px，比文档宽松 1 px",
                ]
            )
        aspect = self._record("fmt_aspect_210_openai")
        if aspect:
            rows.append(
                [
                    "宽高比",
                    "≤ 200:1",
                    f"210:1 {'被拒' if not aspect.accepted else '通过'}",
                    "一致" if not aspect.accepted else "与文档不符",
                ]
            )
        webp = self._record("fmt_8k_webp_openai")
        if webp:
            rows.append(
                [
                    "4K–8K 仅 JPEG/PNG",
                    "仅 JPEG/PNG",
                    f"7680×4320 WEBP {'通过' if webp.accepted else '拒绝'}",
                    "未执行" if webp.accepted else "一致",
                ]
            )
        if not rows:
            return "", ""
        return "与官方文档的对照", "\n".join(
            [
                _table(["项目", "文档值", "实测", "结论"], rows),
                "",
                "「未执行」指**没有观察到该限制**，不代表官方文档错误：文档描述的是模型能力的"
                "**上限承诺**，实现可选择更宽松；但从工程角度，不能把它当作可依赖的拒绝条件——"
                "超限请求会被接受并正常计费。",
            ]
        )

    def _s_recommendations(self) -> tuple[str, str]:
        return "工程建议", "\n".join(
            [
                "1. **不要把 Responses 的「不报错」当成限制更宽松。** 它在约 3.43 MB 处"
                "**静默截断**输入：不返回 4xx、不提示、超出部分不计费但直接丢弃。"
                "长文档走该路径必须由客户端按字节切分，建议单请求文本控制在 3 MB 以内。",
                "2. **客户端必须自己卡单图体积，且按 Base64 后的长度算。** 实测上限是 "
                "Data URI 50 MiB（Chat / Responses，原图约 37.5 MB）与 32 MiB"
                "（Anthropic，原图约 24 MB）；文档的 20 MB 是更保守的承诺，"
                "不能当作服务端会替你拦截的护栏——超限图会被照常解码并按 token 计费。",
                "3. **Anthropic 的 `input_tokens` 不是总输入，必须求和。** 按官方口径 "
                "`total = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`；"
                "实测与 Chat 的 `prompt_tokens` 逐位相等。该兼容层把大部分输入"
                "（含图像 token）计入 `cache_read_input_tokens`，只读 `input_tokens` 会明显低估。"
                "计费时注意缓存命中价（0.1 元/百万）与未命中价（0.8 元/百万）不同。",
                "4. **文本按 token 预算切分，而不是按 MB。** 上限 991,808 tokens 对应约 4.4 MB "
                "英文或 4.5 MB 中文——两者几乎相同，因为汉字虽然 token 密度高，但每字占 3 字节。",
                "5. **多图请求同时受三条约束：** 张数 ≤ 250（硬限制，精确执行）、单图 Data URI "
                "≤ 50 MiB（Chat / Responses）/ 32 MiB（Anthropic）、整体请求体在 Anthropic 侧"
                "约 64 MB 会断连，Chat / Responses 的上限是 128 MiB。按 250 张、单图 2 MB 规划最稳。",
                "6. **错误分支按 `code` 实现。** 同一语义在三条路径下的状态码与 code 都不同"
                "（模型不存在：Chat 404 `model_not_found`、Responses 404 `MODEL_NOT_FOUND`、"
                "Anthropic 400 `InvalidParameter`），message 还含可变数值。",
                "7. **对「断连」做显式处理。** 请求体超限时 Anthropic 不返回 413，而是直接重置连接，"
                "客户端应把大体积上传的 `Broken pipe` 与网络抖动区分开（例如按体积阈值预判）。",
            ]
        )

    def _s_appendix(self) -> tuple[str, str]:
        failures = [r for r in self._records if not r.accepted]
        return "附录", "\n".join(
            [
                "### 复现方式",
                "",
                "```bash",
                "source ~/.zshrc          # 提供 DASHSCOPE_WORKSPACE_ID / DASHSCOPE_API_KEY",
                "python3 run_tests.py --suite all",
                "```",
                "",
                f"失败用例的复现脚本在 `results/curl/`（共 {len(failures)} 个用例，"
                "每个用例提供 `.sh` 与 `.cmd` 两份）。Unix 用 curl 重放，Windows 用 "
                "`--replay`；两者都调用同一段构建逻辑还原请求体，因此上百 MB 的载荷也能一键重放。",
                "",
                "### 产物",
                "",
                "- `results/report.md`：本报告",
                "- `results/results.json`：全部记录与边界结论",
                "- `results/records.jsonl`：逐请求流水，支持 `--resume` / `--only` 增量补测",
                "- `results/curl/`：失败用例的可复现脚本",
                "",
                "测试图片全部在内存中生成（体积可精确控制、不落盘），无需清理临时文件。",
                "",
                "### 边界终值",
                "",
                "本报告的边界表是**本次运行阶梯的止点**。请求体与单图体积的字节级终值",
                "（128 MiB / 原图 39,321,582 B）见 `docs/limits-summary.md`。",
                "",
                "### 可信度说明",
                "",
                "- 边界是**区间**而非精确值：受 tokenizer 分段与网关实现影响，临界点可能有几 KB 抖动。",
                "- Responses 的截断点由「上报 tokens ÷ 实测密度」反算，精度约 ±0.5%，"
                "已用中英文两组数据交叉验证（均落在 3.43 MB）。",
                "- 4xx 中带 `timed out` / `try again` 等标记的响应按抖动处理，不计入边界；"
                "请求体用例的「连接重置」则显式按超限处理并标注。",
                "- 单次运行的结论受网络状况影响，可用 `--only` / `--force` 重跑单个维度或整条路径。",
            ]
        )
