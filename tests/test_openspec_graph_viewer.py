"""Static checks for the OpenSpec graph viewer surface."""

from __future__ import annotations

import unittest
from pathlib import Path


VIEWER_HTML = Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html"
GRAPH_DIAGNOSIS_DIR = Path(__file__).resolve().parents[1] / "viewer" / "graph-diagnosis"
GRAPH_DIAGNOSIS_STATIC_DIR = Path(__file__).resolve().parents[1] / "viewer" / "static" / "graph-diagnosis"


class OpenSpecGraphViewerTests(unittest.TestCase):
    def test_diagnostics_page_mounts_the_react_graph_island(self) -> None:
        html = VIEWER_HTML.read_text(encoding="utf-8")

        self.assertIn('id="openspecGraphChangeInput"', html)
        self.assertIn('id="openspecGraphContent"', html)
        self.assertIn("function loadOpenSpecGraph()", html)
        self.assertIn("/api/openspec-graph/", html)
        self.assertIn('href="/static/graph-diagnosis/graph-diagnosis.css"', html)
        self.assertIn('src="/static/graph-diagnosis/graph-diagnosis.js"', html)
        self.assertIn('id="graph-diagnosis-root"', html)
        self.assertIn("window.CCWhatGraphDiagnosis.mount", html)
        self.assertIn("ccwhat:navigate-to-event", html)
        self.assertIn("ccwhat-locale-change", html)
        self.assertIn("ccwhat-theme-change", html)
        self.assertIn('id="openspecGraphFeedbackInput"', html)
        self.assertIn('id="openspecGraphDiagnoseBtn"', html)
        self.assertIn('class="btn ops-diagnosis-generate-btn"', html)
        self.assertIn('.btn.ops-diagnosis-generate-btn { border-radius: 999px;', html)
        self.assertIn("function diagnoseOpenSpecGraph()", html)
        self.assertIn("/api/openspec-graph-diagnose", html)
        self.assertNotIn("renderPointLineGraph", html)

        feedback_pos = html.index('id="openspecGraphFeedbackInput"')
        graph_pos = html.index('id="openspecGraphContent"')
        self.assertLess(feedback_pos, graph_pos)
    def test_react_graph_diagnosis_sources_and_build_are_present(self) -> None:
        self.assertTrue((GRAPH_DIAGNOSIS_DIR / "package.json").exists())
        self.assertTrue((GRAPH_DIAGNOSIS_DIR / "src" / "main.tsx").exists())
        self.assertTrue((GRAPH_DIAGNOSIS_DIR / "src" / "GraphDiagnosisApp.tsx").exists())
        self.assertTrue((GRAPH_DIAGNOSIS_STATIC_DIR / "graph-diagnosis.js").exists())
        self.assertTrue((GRAPH_DIAGNOSIS_STATIC_DIR / "graph-diagnosis.css").exists())


if __name__ == "__main__":
    unittest.main()
