from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/nature-figure/scripts"


def load_module(name: str, filename: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PlotTemplatePathTests(unittest.TestCase):
    def test_dotted_prefix_is_not_clipped(self) -> None:
        try:
            module = load_module("plot_templates_regression", "plot_templates.py")
        except ImportError as exc:  # matplotlib/numpy are optional in minimal CI
            self.skipTest(str(exc))
        for prefix in ("Fig.2", "fig2.v3"):
            path = module.with_extension(Path("out") / prefix, ".svg")
            self.assertEqual(path.name, prefix + ".svg")
        self.assertNotEqual(
            module.with_extension(Path("Fig.2"), ".pdf"), module.with_extension(Path("Fig.3"), ".pdf")
        )


class ValidateFigureWidthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module("validate_figure_regression", "validate_figure.py")

    def test_figsize_in_millimetres_is_not_scaled_again(self) -> None:
        widths = self.module.candidate_widths_mm("plt.subplots(figsize=(183 / 25.4, 120 / 25.4))", "python")
        self.assertEqual(widths, [183.0])

    def test_figsize_in_inches_is_converted(self) -> None:
        widths = self.module.candidate_widths_mm("figsize=(3.5, 2)", "python")
        self.assertAlmostEqual(widths[0], 88.9)

    def test_r_arrow_assignment_is_detected(self) -> None:
        self.assertEqual(self.module.candidate_widths_mm("width_mm <- 183", "r"), [183.0])


if __name__ == "__main__":
    unittest.main()
