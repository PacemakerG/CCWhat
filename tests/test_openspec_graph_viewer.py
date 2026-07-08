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


if __name__ == "__main__":
    unittest.main()
