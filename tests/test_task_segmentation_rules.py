"""Tests for ccwhat.task_segments.rules (tasks 3.1 – 3.5)."""

import unittest
from unittest import mock

from ccwhat.task_segments.rules import (
    classify_intent,
    extract_todos,
    load_rules,
    match_phrases,
    match_words,
)


class TestLoadRules(unittest.TestCase):
    def test_load_rules_returns_dict(self):
        rules = load_rules()
        self.assertIsInstance(rules, dict)
        self.assertIn("new_task_markers", rules)
        self.assertIn("continuation_markers", rules)
        self.assertIn("boundary_markers", rules)
        self.assertIn("task_types", rules)

    def test_load_rules_reads_resource_as_utf8(self):
        class _FakeResource:
            def joinpath(self, name):
                self.name = name
                return self

            def read_text(self, *, encoding=None):
                if encoding != "utf-8":
                    raise UnicodeDecodeError("gbk", b"\xae", 0, 1, "bad")
                return (
                    '{"new_task_markers": {}, "continuation_markers": {}, '
                    '"boundary_markers": {}, "task_types": {}}'
                )

        with mock.patch("ccwhat.task_segments.rules.resources.files", return_value=_FakeResource()):
            rules = load_rules()

        self.assertIn("new_task_markers", rules)


class TestMatchPhrases(unittest.TestCase):
    def test_hit(self):
        self.assertEqual(match_phrases("帮我实现一个功能", ["帮我", "修复"]), ["帮我"])

    def test_miss(self):
        self.assertEqual(match_phrases("这是什么", ["帮我", "修复"]), [])

    def test_multiple_hits(self):
        hits = match_phrases("帮我修复这个bug", ["帮我", "修复", "新增"])
        self.assertIn("帮我", hits)
        self.assertIn("修复", hits)
        self.assertNotIn("新增", hits)


class TestMatchWords(unittest.TestCase):
    def test_whole_word(self):
        self.assertEqual(match_words("please fix the bug", ["fix"]), ["fix"])

    def test_no_partial_match(self):
        # "fixed" should NOT match the word "fix"
        self.assertEqual(match_words("it is fixed now", ["fix"]), [])

    def test_case_insensitive(self):
        self.assertIn("implement", match_words("Please Implement the feature", ["implement"]))

    def test_miss(self):
        self.assertEqual(match_words("hello world", ["fix", "add"]), [])


# ---------------------------------------------------------------------------
# 3.2 + 3.3  classify_intent
# ---------------------------------------------------------------------------

class TestClassifyIntentNewTask(unittest.TestCase):
    """Pure new-task messages should have new_task_score > 0 and is_veto=False."""

    def test_zh_new_task(self):
        result = classify_intent("帮我实现一个登录功能")
        self.assertGreater(result.new_task_score, 0)
        self.assertFalse(result.is_veto)

    def test_en_new_task(self):
        result = classify_intent("Please implement a login feature")
        self.assertGreater(result.new_task_score, 0)
        self.assertFalse(result.is_veto)

    def test_reasons_recorded(self):
        result = classify_intent("帮我实现一个登录功能")
        self.assertTrue(any("new_task" in r for r in result.reasons))


class TestClassifyIntentContinuation(unittest.TestCase):
    """Pure continuation messages should trigger is_veto=True."""

    def test_zh_still_error(self):
        result = classify_intent("还是报错了")
        self.assertTrue(result.is_veto)
        self.assertIn("veto:continuation_wins", result.reasons)

    def test_en_still_failing(self):
        result = classify_intent("still not working")
        self.assertTrue(result.is_veto)

    def test_continuation_score_positive(self):
        result = classify_intent("继续帮我改一下")
        self.assertGreater(result.continuation_score, 0)


class TestClassifyIntentBoundaryVeto(unittest.TestCase):
    """Strong boundary marker + continuation → veto should NOT fire."""

    def test_boundary_cancels_veto(self):
        # "另外" is a boundary marker; "继续" is a continuation marker
        result = classify_intent("另外，继续帮我做一件不相关的事")
        self.assertFalse(result.is_veto)

    def test_en_boundary_cancels_veto(self):
        result = classify_intent("separately, still need this feature")
        self.assertFalse(result.is_veto)


class TestClassifyIntentWeakQuestion(unittest.TestCase):
    """Ambiguous question messages should have low/zero new_task_score or explanation task_type."""

    def test_zh_what_does_this_mean(self):
        result = classify_intent("这是什么意思")
        # Either task_type is explanation/unknown, or new_task_score is low
        self.assertIn(result.task_type, ("explanation", "unknown"))

    def test_en_explain(self):
        result = classify_intent("Can you explain why this happens?")
        self.assertIn(result.task_type, ("explanation", "unknown"))


class TestClassifyIntentTaskTypes(unittest.TestCase):
    """task_type should be correctly identified."""

    def test_bugfix(self):
        result = classify_intent("修复这个报错，程序崩溃了")
        self.assertEqual(result.task_type, "bugfix")

    def test_feature(self):
        result = classify_intent("新增一个用户注册功能")
        self.assertEqual(result.task_type, "feature")

    def test_test_type(self):
        result = classify_intent("帮我写测试，加单测覆盖这个模块")
        self.assertEqual(result.task_type, "test")

    def test_refactor(self):
        result = classify_intent("重构这段代码，优化一下结构")
        self.assertEqual(result.task_type, "refactor")

    def test_en_bugfix(self):
        result = classify_intent("fix the crash in the login flow")
        self.assertEqual(result.task_type, "bugfix")

    def test_en_feature(self):
        result = classify_intent("implement a new feature for user profile")
        self.assertEqual(result.task_type, "feature")


# ---------------------------------------------------------------------------
# 3.4  extract_todos
# ---------------------------------------------------------------------------

class TestExtractTodos(unittest.TestCase):

    def test_user_todo_checkbox_with_verb(self):
        text = "- [ ] 实现登录接口\n- [ ] 修复注册bug"
        user, assistant, tool = extract_todos(text)
        self.assertEqual(len(user), 2)
        self.assertEqual(len(assistant), 0)
        self.assertEqual(len(tool), 0)

    def test_assistant_numbered_list(self):
        text = "1. 读取配置文件\n2. 初始化数据库\n3. 启动服务"
        user, assistant, tool = extract_todos(text)
        self.assertEqual(len(assistant), 3)
        self.assertEqual(len(user), 0)

    def test_checkbox_without_verb_goes_to_assistant(self):
        text = "- [ ] 第一步\n- [x] 第二步"
        user, assistant, tool = extract_todos(text)
        # No user-intent verbs → assistant_todos
        self.assertEqual(len(assistant), 2)
        self.assertEqual(len(user), 0)

    def test_en_user_todo(self):
        text = "- [ ] implement the auth module\n- [ ] add unit tests"
        user, assistant, tool = extract_todos(text)
        self.assertGreater(len(user), 0)

    def test_empty_text(self):
        user, assistant, tool = extract_todos("")
        self.assertEqual(user, [])
        self.assertEqual(assistant, [])
        self.assertEqual(tool, [])

    def test_no_todo_lines(self):
        text = "这是一段普通的文字，没有任何待办事项。"
        user, assistant, tool = extract_todos(text)
        self.assertEqual(user + assistant + tool, [])

    def test_mixed_todos(self):
        text = (
            "- [ ] 实现接口\n"
            "1. 检查日志\n"
            "- [ ] 普通条目\n"
        )
        user, assistant, tool = extract_todos(text)
        # "实现接口" has user verb → user_todos
        self.assertGreater(len(user), 0)
        # numbered line → assistant_todos
        self.assertGreater(len(assistant), 0)


if __name__ == "__main__":
    unittest.main()
