"""Static checks for the OpenSpec graph viewer surface."""

from __future__ import annotations

import unittest
from pathlib import Path


VIEWER_HTML = Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html"


class OpenSpecGraphViewerTests(unittest.TestCase):
    def test_diagnostics_page_exposes_openspec_graph_panel(self) -> None:
        html = VIEWER_HTML.read_text(encoding="utf-8")

        self.assertIn('id="openspecGraphChangeInput"', html)
        self.assertIn('id="openspecGraphContent"', html)
        self.assertIn("function loadOpenSpecGraph()", html)
        self.assertIn("/api/openspec-graph/", html)
        self.assertIn("renderPointLineGraph(t('action_graph')", html)
        self.assertIn("renderPointLineGraph(t('event_graph')", html)
        self.assertIn("source_kind", html)
        self.assertIn("milestone_fallback", html)
        self.assertIn("不是 session step 级细图", html)
        self.assertIn("function highlightOpenSpecGraphEvents", html)
        self.assertIn('id="openspecGraphFeedbackInput"', html)
        self.assertIn('id="openspecGraphDiagnoseBtn"', html)
        self.assertIn("function diagnoseOpenSpecGraph()", html)
        self.assertIn("/api/openspec-graph-diagnose", html)
        self.assertIn("function renderOpenSpecFeedbackDiagnosis", html)
        self.assertIn("function highlightOpenSpecGraphNode", html)

        feedback_pos = html.index('id="openspecGraphFeedbackInput"')
        graph_pos = html.index('id="openspecGraphContent"')
        self.assertLess(feedback_pos, graph_pos)
        self.assertIn('.ops-graph-event .ops-graph-canvas { max-height:', html)
        self.assertIn('class="ops-graph-block ops-graph-${kind}"', html)


if __name__ == "__main__":
    unittest.main()
