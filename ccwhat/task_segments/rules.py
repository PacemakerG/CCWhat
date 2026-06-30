"""Rule-based intent classification and todo extraction for task segmentation."""

from __future__ import annotations

import json
import re
from importlib import resources

from ccwhat.task_segments.models import IntentResult


# ---------------------------------------------------------------------------
# 3.1  Rule loader and lexical matchers
# ---------------------------------------------------------------------------

def load_rules() -> dict:
    return json.loads(
        resources.files("ccwhat").joinpath("assets/task_segment_rules.json").read_text(encoding="utf-8")
    )


def match_phrases(text: str, phrases: list[str]) -> list[str]:
    """Return every phrase from *phrases* that appears in *text* (substring match)."""
    return [p for p in phrases if p in text]


def match_words(text: str, words: list[str]) -> list[str]:
    """Return every word from *words* that appears in *text* as a whole word (case-insensitive)."""
    hits: list[str] = []
    for word in words:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(word)
    return hits


# ---------------------------------------------------------------------------
# 3.2  User-message intent classification
# ---------------------------------------------------------------------------

def classify_intent(text: str, rules: dict | None = None) -> IntentResult:
    """Classify the intent of a user message.

    Returns an :class:`IntentResult` with scores, task_type, veto flag, and reasons.
    """
    if rules is None:
        rules = load_rules()

    result = IntentResult()

    # --- new_task_score ---
    nm = rules["new_task_markers"]
    nm_score: float = nm["score"]

    for phrase in match_phrases(text, nm.get("zh_phrases", [])):
        result.new_task_score += nm_score
        result.reasons.append(f"new_task:zh:{phrase}:+{nm_score}")

    for word in match_words(text, nm.get("en_words", [])):
        result.new_task_score += nm_score
        result.reasons.append(f"new_task:en:{word}:+{nm_score}")

    # --- continuation_score ---
    cm = rules["continuation_markers"]
    cm_score: float = cm["score"]

    for phrase in match_phrases(text, cm.get("zh_phrases", [])):
        result.continuation_score += cm_score
        result.reasons.append(f"continuation:zh:{phrase}:+{cm_score}")

    for word in match_words(text, cm.get("en_words", [])):
        result.continuation_score += cm_score
        result.reasons.append(f"continuation:en:{word}:+{cm_score}")

    # --- task_type detection ---
    best_type = "unknown"
    best_count = 0

    for ttype, tdef in rules.get("task_types", {}).items():
        count = len(match_phrases(text, tdef.get("zh_phrases", []))) + \
                len(match_words(text, tdef.get("en_words", [])))
        if count > best_count:
            best_count = count
            best_type = ttype

    result.task_type = best_type

    # --- weak question markers (lower new_task_score) ---
    wq = rules.get("weak_question_markers", {})
    wq_score: float = wq.get("score", -0.5)

    for phrase in match_phrases(text, wq.get("zh_phrases", [])):
        result.new_task_score += wq_score
        result.reasons.append(f"weak_question:zh:{phrase}:{wq_score}")

    for word in match_words(text, wq.get("en_words", [])):
        result.new_task_score += wq_score
        result.reasons.append(f"weak_question:en:{word}:{wq_score}")

    # --- apply veto logic (3.3) ---
    _apply_veto(result, text, rules)

    return result


# ---------------------------------------------------------------------------
# 3.3  Continuation veto logic
# ---------------------------------------------------------------------------

def _apply_veto(result: IntentResult, text: str, rules: dict) -> None:
    """Mutate *result* in-place: set is_veto=True when continuation dominates."""
    if result.continuation_score < 2.0:
        return

    # Check for strong boundary markers — they cancel the veto
    bm = rules.get("boundary_markers", {})
    boundary_hits = (
        match_phrases(text, bm.get("zh_phrases", [])) +
        match_words(text, bm.get("en_words", []))
    )
    if boundary_hits:
        return

    result.is_veto = True
    result.reasons.append("veto:continuation_wins")


# ---------------------------------------------------------------------------
# 3.4  Todo extraction and classification
# ---------------------------------------------------------------------------

_TODO_LINE_RE = re.compile(r"^\s*[-*]\s*\[[ xX]\]")
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+\.\s+")

# Verbs that suggest the todo belongs to the *user* (what they want done)
_USER_TODO_VERBS_ZH = re.compile(r"实现|修复|添加|新增|开发|重构|优化|写|创建|完成|测试|修改")
_USER_TODO_VERBS_EN = re.compile(
    r"\b(implement|fix|add|create|build|write|develop|refactor|optimize|complete|test)\b",
    re.IGNORECASE,
)


def extract_todos(text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract and classify todo items from *text*.

    Returns:
        (user_todos, assistant_todos, tool_todos)

    Classification:
    - Lines matching ``- [ ]`` / ``- [x]`` checkbox syntax → candidate todos.
    - If the line contains user-intent verbs → user_todos.
    - If the line looks like an assistant plan item (numbered list or checkbox
      without strong user verbs) → assistant_todos.
    - Everything else → tool_todos.
    """
    user_todos: list[str] = []
    assistant_todos: list[str] = []
    tool_todos: list[str] = []

    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_checkbox = bool(_TODO_LINE_RE.match(line))
        is_numbered = bool(_NUMBERED_LINE_RE.match(line))

        if not (is_checkbox or is_numbered):
            continue

        # Determine classification
        has_user_verb = bool(
            _USER_TODO_VERBS_ZH.search(stripped) or
            _USER_TODO_VERBS_EN.search(stripped)
        )

        if is_checkbox and has_user_verb:
            user_todos.append(stripped)
        elif is_checkbox or is_numbered:
            # Numbered items typically come from assistant planning lists
            assistant_todos.append(stripped)
        else:
            tool_todos.append(stripped)

    return user_todos, assistant_todos, tool_todos
