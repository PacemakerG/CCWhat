"""Tests for ccwhat.agent_config — auto-detection of recording domains."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from ccwhat.agent_config import (
    _opencode_hosts_from_models_output,
    _strip_jsonc_comments,
    detect_default_paths,
    detect_domains,
)


# ---------------------------------------------------------------------------
# JSONC comment stripping (task 3.3)
# ---------------------------------------------------------------------------

class TestStripJsoncComments:
    def test_line_comment_removed(self):
        src = '{"a": 1} // this is a comment\n'
        result = _strip_jsonc_comments(src)
        assert "//" not in result
        assert json.loads(result) == {"a": 1}

    def test_block_comment_removed(self):
        src = '{"a": /* ignore this */ 1}'
        result = _strip_jsonc_comments(src)
        assert "/*" not in result
        assert json.loads(result) == {"a": 1}

    def test_mixed_comments(self):
        src = '// header\n{"a": /* block */ 1} // tail\n'
        result = _strip_jsonc_comments(src)
        assert json.loads(result.strip()) == {"a": 1}

    def test_no_comments_unchanged(self):
        src = '{"x": "y"}'
        assert _strip_jsonc_comments(src) == src


# ---------------------------------------------------------------------------
# opencode domain detection (task 3.1)
# ---------------------------------------------------------------------------

class TestDetectOpencodeDomains:
    def _write_opencode_config(self, home: Path, providers: dict) -> Path:
        config_dir = home / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "opencode.jsonc"
        config_file.write_text(json.dumps({"provider": providers}), encoding="utf-8")
        return config_file

    def test_single_provider(self, tmp_path):
        self._write_opencode_config(tmp_path, {
            "friday": {"options": {"baseURL": "https://aigc.sankuai.com/v1/openai/native"}}
        })
        result = detect_domains("opencode", _home=tmp_path)
        assert result == ["aigc.sankuai.com"]

    def test_models_output_extracts_builtin_provider_url(self):
        output = '''
opencode/deepseek-v4-flash-free
{
  "id": "deepseek-v4-flash-free",
  "providerID": "opencode",
  "api": {
    "url": "https://opencode.ai/zen/v1",
    "npm": "@ai-sdk/openai-compatible"
  }
}
friday/deepseek-v4-flash
{
  "id": "deepseek-v4-flash",
  "providerID": "friday",
  "api": {
    "url": "openai",
    "npm": "@ai-sdk/openai-compatible"
  }
}
'''
        assert _opencode_hosts_from_models_output(output) == ["opencode.ai"]

    def test_real_home_merges_config_and_builtin_catalog(self, tmp_path):
        self._write_opencode_config(tmp_path, {
            "friday": {"options": {"baseURL": "https://aigc.sankuai.com/v1/openai/native"}}
        })
        fake_completed = mock.MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = '''
opencode/deepseek-v4-flash-free
{"api":{"url":"https://opencode.ai/zen/v1"}}
'''
        with mock.patch("pathlib.Path.home", return_value=tmp_path), \
             mock.patch("ccwhat.agent_config.subprocess.run", return_value=fake_completed):
            result = detect_domains("opencode")

        assert result == ["aigc.sankuai.com", "opencode.ai"]

    def test_multiple_providers(self, tmp_path):
        self._write_opencode_config(tmp_path, {
            "p1": {"options": {"baseURL": "https://a.example.com/v1"}},
            "p2": {"options": {"baseURL": "https://b.example.com/api"}},
        })
        result = detect_domains("opencode", _home=tmp_path)
        assert "a.example.com" in result
        assert "b.example.com" in result
        assert len(result) == 2

    def test_duplicate_providers_deduped(self, tmp_path):
        self._write_opencode_config(tmp_path, {
            "p1": {"options": {"baseURL": "https://same.example.com/v1"}},
            "p2": {"options": {"baseURL": "https://same.example.com/v2"}},
        })
        result = detect_domains("opencode", _home=tmp_path)
        assert result == ["same.example.com"]

    def test_missing_config_returns_default(self, tmp_path):
        result = detect_domains("opencode", _home=tmp_path)
        assert result == ["opencode.ai"]

    def test_invalid_config_returns_default(self, tmp_path):
        config_dir = tmp_path / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        (config_dir / "opencode.jsonc").write_text("not valid json {{{{", encoding="utf-8")
        result = detect_domains("opencode", _home=tmp_path)
        assert result == ["opencode.ai"]

    def test_jsonc_with_comments_parsed(self, tmp_path):
        config_dir = tmp_path / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        content = (
            '// top comment\n'
            '{"provider": {"p": {"options": {"baseURL": "https://gw.example.com"}}}}'
        )
        (config_dir / "opencode.jsonc").write_text(content, encoding="utf-8")
        result = detect_domains("opencode", _home=tmp_path)
        assert result == ["gw.example.com"]


# ---------------------------------------------------------------------------
# claude domain detection (task 3.2)
# ---------------------------------------------------------------------------

class TestDetectClaudeDomains:
    def _write_claude_settings(self, home: Path, env: dict) -> None:
        config_dir = home / ".claude"
        config_dir.mkdir(parents=True)
        (config_dir / "settings.json").write_text(
            json.dumps({"env": env}), encoding="utf-8"
        )

    def test_custom_base_url(self, tmp_path):
        self._write_claude_settings(tmp_path, {"ANTHROPIC_BASE_URL": "https://mcli.sankuai.com"})
        assert detect_domains("claude", _home=tmp_path) == ["mcli.sankuai.com"]

    def test_no_base_url_returns_default(self, tmp_path):
        self._write_claude_settings(tmp_path, {"ANTHROPIC_MODEL": "opus"})
        assert detect_domains("claude", _home=tmp_path) == ["api.anthropic.com"]

    def test_missing_config_returns_default(self, tmp_path):
        assert detect_domains("claude", _home=tmp_path) == ["api.anthropic.com"]

    def test_environment_base_url_is_included(self, tmp_path):
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://env.example.com"}, clear=False):
            assert detect_domains("claude", _home=tmp_path) == ["env.example.com"]


# ---------------------------------------------------------------------------
# codex domain detection (task 3.2)
# ---------------------------------------------------------------------------

class TestDetectCodexDomains:
    def _write_codex_config(self, home: Path, content: str) -> None:
        config_dir = home / ".codex"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(content, encoding="utf-8")

    def test_custom_base_url(self, tmp_path):
        toml = '[shell_environment_policy.set]\nOPENAI_BASE_URL = "https://gw.example.com"\n'
        self._write_codex_config(tmp_path, toml)
        assert detect_domains("codex", _home=tmp_path) == ["gw.example.com"]

    def test_model_provider_base_url(self, tmp_path):
        toml = '''
model_provider = "portkey"

[model_providers.portkey]
base_url = "https://portkey.example.com/v1"
'''
        self._write_codex_config(tmp_path, toml)
        assert detect_domains("codex", _home=tmp_path) == ["portkey.example.com"]

    def test_openai_base_url_override(self, tmp_path):
        self._write_codex_config(tmp_path, 'openai_base_url = "https://us.api.openai.com/v1"\n')
        assert detect_domains("codex", _home=tmp_path) == ["us.api.openai.com"]

    def test_no_base_url_returns_default(self, tmp_path):
        toml = '[shell_environment_policy.set]\nANTHROPIC_MODEL = "opus"\n'
        self._write_codex_config(tmp_path, toml)
        assert detect_domains("codex", _home=tmp_path) == ["api.openai.com", "chatgpt.com"]

    def test_missing_config_returns_default(self, tmp_path):
        assert detect_domains("codex", _home=tmp_path) == ["api.openai.com", "chatgpt.com"]


# ---------------------------------------------------------------------------
# Unknown agent (task 3.4)
# ---------------------------------------------------------------------------

class TestUnknownAgent:
    def test_returns_empty_list(self):
        assert detect_domains("unknown-agent") == []

    def test_empty_string_returns_empty(self):
        assert detect_domains("") == []


# ---------------------------------------------------------------------------
# detect_default_paths
# ---------------------------------------------------------------------------

class TestDetectDefaultPaths:
    def test_opencode_paths(self):
        assert detect_default_paths("opencode") == []

    def test_claude_paths(self):
        assert detect_default_paths("claude") == []

    def test_codex_paths(self):
        assert detect_default_paths("codex") == []

    def test_unknown_agent_empty(self):
        assert detect_default_paths("unknown") == []
