"""Recording configuration — load/save ~/.ccwhat/config.toml and preset expansion."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

try:
    import tomli_w  # optional write backend
except ImportError:
    tomli_w = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Public paths
# ---------------------------------------------------------------------------

CCWHAT_DIR: Path = Path.home() / ".ccwhat"
DEFAULT_CONFIG_PATH: Path = CCWHAT_DIR / "config.toml"
DEFAULT_RAW_LOG_DIR: Path = CCWHAT_DIR / "raw-req-resp"

# Legacy path for migration reads
LEGACY_DIR: Path = Path.home() / ".deep-ai-analysis"
LEGACY_RAW_LOG_DIR: Path = LEGACY_DIR / "raw-req-resp"

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict[str, Any]] = {
    "claude": {
        "domains": ["api.anthropic.com"],
        "paths": ["/v1/messages", "/v1/messages/count_tokens"],
    },
    "codex": {
        "domains": ["api.openai.com", "chatgpt.com"],
        "paths": ["/v1/responses", "/backend-api/codex/responses"],
    },
}

# ---------------------------------------------------------------------------
# Redaction defaults
# ---------------------------------------------------------------------------

DEFAULT_REDACT_HEADERS: list[str] = [
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "proxy-authorization",
]
DEFAULT_REDACT_PATTERNS: list[str] = ["token", "secret", "key"]

DEFAULT_MAX_BODY_BYTES: int = 512 * 1024  # 512 KB


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class RecordingConfig:
    preset: str | None = None
    domains: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    redact_headers: list[str] = field(default_factory=lambda: list(DEFAULT_REDACT_HEADERS))
    redact_header_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_REDACT_PATTERNS))
    onboarding_complete: bool = False

    def effective_domains(self) -> list[str]:
        """Return union of preset domains + explicit domains."""
        result = list(self.domains)
        if self.preset and self.preset in PRESETS:
            for d in PRESETS[self.preset]["domains"]:
                if d not in result:
                    result.append(d)
        return result

    def effective_paths(self) -> list[str]:
        """Return union of preset paths + explicit paths."""
        result = list(self.paths)
        if self.preset and self.preset in PRESETS:
            for p in PRESETS[self.preset]["paths"]:
                if p not in result:
                    result.append(p)
        return result

    def is_valid_for_recording(self) -> bool:
        return bool(self.effective_domains())

    def to_dict(self) -> dict[str, Any]:
        return {
            "recording": {
                **({"preset": self.preset} if self.preset else {}),
                "domains": self.domains,
                "paths": self.paths,
                "max_body_bytes": self.max_body_bytes,
                "redact_headers": self.redact_headers,
                "redact_header_patterns": self.redact_header_patterns,
                "onboarding_complete": self.onboarding_complete,
            }
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")


def validate_domain(domain: str) -> str:
    """Return normalized domain or raise ValueError."""
    domain = domain.strip()
    if not domain:
        raise ValueError("Domain must not be empty.")
    if "://" in domain:
        raise ValueError(f"Domain must not include a URL scheme: {domain!r}")
    if "/" in domain or "\\" in domain:
        raise ValueError(f"Domain must not include a path: {domain!r}")
    if " " in domain or "\t" in domain:
        raise ValueError(f"Domain must not contain whitespace: {domain!r}")
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"Invalid domain format: {domain!r}")
    return domain


def normalize_path(path: str) -> str:
    """Ensure path starts with /."""
    path = path.strip()
    if path and not path.startswith("/"):
        path = "/" + path
    return path


def validate_config(cfg: RecordingConfig) -> list[str]:
    """Return list of validation error messages (empty = valid)."""
    errors: list[str] = []
    for d in cfg.domains:
        try:
            validate_domain(d)
        except ValueError as exc:
            errors.append(str(exc))
    if cfg.max_body_bytes is not None and cfg.max_body_bytes < 0:
        errors.append("max_body_bytes must be >= 0")
    return errors


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_config(config_path: Path | None = None) -> RecordingConfig | None:
    """Load config from TOML file. Returns None if file does not exist."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return None
    if tomllib is None:
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    rec = data.get("recording", {})
    cfg = RecordingConfig(
        preset=rec.get("preset"),
        domains=rec.get("domains", []),
        paths=[normalize_path(p) for p in rec.get("paths", [])],
        max_body_bytes=rec.get("max_body_bytes", DEFAULT_MAX_BODY_BYTES),
        redact_headers=rec.get("redact_headers", list(DEFAULT_REDACT_HEADERS)),
        redact_header_patterns=rec.get("redact_header_patterns", list(DEFAULT_REDACT_PATTERNS)),
        onboarding_complete=rec.get("onboarding_complete", False),
    )
    return cfg


def save_config(cfg: RecordingConfig, config_path: Path | None = None) -> None:
    """Persist config to TOML file, creating directories as needed."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.to_dict()
    if tomli_w is not None:
        path.write_bytes(tomli_w.dumps(data).encode())
    else:
        lines = ["[recording]\n"]
        rec = data["recording"]
        if "preset" in rec:
            lines.append(f'preset = "{rec["preset"]}"\n')
        lines.append(_toml_str_list("domains", rec["domains"]))
        lines.append(_toml_str_list("paths", rec["paths"]))
        lines.append(f'max_body_bytes = {rec["max_body_bytes"]}\n')
        lines.append(_toml_str_list("redact_headers", rec["redact_headers"]))
        lines.append(_toml_str_list("redact_header_patterns", rec["redact_header_patterns"]))
        lines.append(f'onboarding_complete = {"true" if rec["onboarding_complete"] else "false"}\n')
        path.write_text("".join(lines), encoding="utf-8")


def _toml_str_list(key: str, values: list[str]) -> str:
    items = ", ".join(f'"{v}"' for v in values)
    return f"{key} = [{items}]\n"


# ---------------------------------------------------------------------------
# Helpers for proxy / run
# ---------------------------------------------------------------------------


def generate_local_session_id() -> str:
    """Generate a local session ID for requests without X-Claude-Code-Session-Id."""
    return f"local-{uuid.uuid4()}"
