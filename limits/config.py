"""Runtime configuration and the limit values quoted by the official document.

The documented numbers are kept in one place so that every experiment can
reference them symbolically instead of repeating magic numbers, and so the
final report can compare *measured* against *documented* values.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone, timedelta

DEFAULT_REGION = "cn-beijing"
DEFAULT_MODEL = "qwen3.8-flash"

# 只允许「字母数字开头 + 字母数字/点/下划线/连字符」，防止用 @ / 斜杠 / 冒号改写主机
WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REGION_RE = re.compile(r"^[a-z]{2,}(?:-[a-z0-9]+)+$")
HOST_SUFFIX = ".maas.aliyuncs.com"


@dataclass(frozen=True)
class Settings:
    """Connection settings resolved from the shell environment."""

    workspace_id: str
    api_key: str
    region: str = DEFAULT_REGION
    model: str = DEFAULT_MODEL
    timeout_s: float = 600.0
    request_interval_s: float = 1.0

    def __post_init__(self) -> None:
        if not WORKSPACE_ID_RE.fullmatch(self.workspace_id):
            raise SystemExit(
                f"DASHSCOPE_WORKSPACE_ID 含非法字符：{self.workspace_id!r}；"
                "只允许字母数字、点、下划线、连字符"
            )
        if not REGION_RE.fullmatch(self.region):
            raise SystemExit(f"DASHSCOPE_REGION 非法：{self.region!r}")

    @property
    def host(self) -> str:
        return f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com"

    @property
    def started_at(self) -> str:
        tz = timezone(timedelta(hours=8))
        return datetime.now(tz).isoformat(timespec="seconds")

    @classmethod
    def from_env(cls) -> "Settings":
        workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip()
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        missing = [
            name
            for name, value in (
                ("DASHSCOPE_WORKSPACE_ID", workspace_id),
                ("DASHSCOPE_API_KEY", api_key),
            )
            if not value
        ]
        if missing:
            raise SystemExit(
                "缺少环境变量: "
                + ", ".join(missing)
                + "\n请先执行 `source ~/.zshrc`，或在命令行中显式导出。"
            )
        return cls(
            workspace_id=workspace_id,
            api_key=api_key,
            region=os.getenv("DASHSCOPE_REGION", DEFAULT_REGION),
            model=os.getenv("DASHSCOPE_MODEL", DEFAULT_MODEL),
            timeout_s=float(os.getenv("BAILIAN_TIMEOUT_S", "600")),
            request_interval_s=float(os.getenv("BAILIAN_REQUEST_INTERVAL_S", "1.0")),
        )


@dataclass(frozen=True)
class DocumentedLimits:
    """Limits transcribed from the Model Studio vision documentation.

    Source:
    https://docs.bailian.console.aliyun.com/zh/model-studio/vision#使用限制

    默认值是 ``qwen3.8-flash``（属 Qwen3.8 系列，适用 20 MB 档）。换模型时
    用 ``BAILIAN_*`` 环境变量覆盖，或直接改这里的默认值——报告的「文档值」
    一列会跟着变，避免拿 A 模型的文档去评判 B 模型。
    """

    # 单张图像（公网 URL / Base64 原始文件）；qwen3.8-flash 属 Qwen3.8 系列，适用 20 MB 档
    image_mb_relaxed: float = 20.0
    # Base64 编码后的 Data URI 字符串
    data_uri_mb_openai: float = 20.0
    data_uri_mb_anthropic: float = 32.0
    # 整个请求体
    body_mb: float = 64.0
    body_mb_dashscope_domain: float = 16.0
    # 图片张数（Base64）
    images_base64_max: int = 250
    images_url_max_qwen38: int = 2048
    # 图像分辨率
    min_side_px_exclusive: int = 10
    max_aspect_ratio: int = 200
    # 上下文（qwen3.8-flash，非思考模式）
    max_input_tokens: int = 991_808
    max_output_tokens: int = 131_072
    context_tokens: int = 1_000_000

    def data_uri_mb(self, protocol_key: str) -> float:
        return (
            self.data_uri_mb_anthropic
            if protocol_key == "anthropic"
            else self.data_uri_mb_openai
        )

    def to_mapping(self) -> dict:
        return {item.name: getattr(self, item.name) for item in fields(self)}

    @classmethod
    def from_mapping(cls, data: dict | None) -> "DocumentedLimits":
        """优先用运行当时记录的文档值，避免重出报告时套错模型。"""
        if not data:
            return cls.from_env()
        kwargs = {}
        for name, value in data.items():
            default = getattr(cls, name, None)
            if default is None:
                continue
            kwargs[name] = float(value) if isinstance(default, float) else int(value)
        return cls(**kwargs)

    @classmethod
    def from_env(cls) -> "DocumentedLimits":
        """用 ``BAILIAN_*`` 覆盖文档值；未设置时保持 qwen3.8-flash 的默认值。"""
        return cls(
            image_mb_relaxed=_env_float("BAILIAN_IMAGE_MB", cls.image_mb_relaxed),
            data_uri_mb_openai=_env_float(
                "BAILIAN_DATA_URI_MB_OPENAI", cls.data_uri_mb_openai
            ),
            data_uri_mb_anthropic=_env_float(
                "BAILIAN_DATA_URI_MB_ANTHROPIC", cls.data_uri_mb_anthropic
            ),
            body_mb=_env_float("BAILIAN_BODY_MB", cls.body_mb),
            images_base64_max=_env_int(
                "BAILIAN_IMAGES_BASE64_MAX", cls.images_base64_max
            ),
            max_input_tokens=_env_int(
                "BAILIAN_MAX_INPUT_TOKENS", cls.max_input_tokens
            ),
            max_output_tokens=_env_int(
                "BAILIAN_MAX_OUTPUT_TOKENS", cls.max_output_tokens
            ),
            context_tokens=_env_int("BAILIAN_CONTEXT_TOKENS", cls.context_tokens),
        )


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"{name} 需要数字，收到: {raw!r}")


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


@dataclass(frozen=True)
class Pricing:
    """单价（元 / 百万 tokens），用于报告里的成本估算。

    默认值是 qwen3.8-flash；换模型时用 ``BAILIAN_PRICE_*`` 覆盖，
    否则报告会用错单价（max 系列是 flash 的十几倍）。
    """

    input: float = 0.8
    cache_hit: float = 0.1
    output: float = 2.7

    @classmethod
    def current(cls) -> "Pricing":
        return cls(
            input=_env_float("BAILIAN_PRICE_INPUT", cls.input),
            cache_hit=_env_float("BAILIAN_PRICE_CACHE_HIT", cls.cache_hit),
            output=_env_float("BAILIAN_PRICE_OUTPUT", cls.output),
        )

    def to_mapping(self) -> dict:
        return {"input": self.input, "cache_hit": self.cache_hit, "output": self.output}

    @classmethod
    def from_mapping(cls, data: dict | None) -> "Pricing":
        if not data:
            return cls.current()
        return cls(
            input=float(data.get("input", cls.input)),
            cache_hit=float(data.get("cache_hit", cls.cache_hit)),
            output=float(data.get("output", cls.output)),
        )


def env_floats(name: str) -> list[float] | None:
    """读取逗号分隔的数值列表；未设置返回 None。用于自定义探测点。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        values = [float(item) for item in raw.split(",") if item.strip()]
    except ValueError:
        raise SystemExit(f"{name} 需要逗号分隔的数字，收到: {raw!r}")
    if values != sorted(values):
        raise SystemExit(f"{name} 必须递增，收到: {values}")
    return values
