from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

import yaml

from audit_lab import __version__
from audit_lab import web


ROOT = Path(__file__).resolve().parents[1]


def cff_scalar(name: str) -> str:
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}:\s*[\"']?([^\n\"']+)[\"']?\s*$", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"missing scalar {name!r} in CITATION.cff")
    return match.group(1).strip()


class VersionMetadataTests(unittest.TestCase):
    def test_release_version_is_consistent_everywhere(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project_version = str(tomllib.load(handle)["project"]["version"])

        self.assertRegex(project_version, r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        self.assertEqual(__version__, project_version)
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        citation_versions = re.findall(r"^\s*version:\s*[\"']?([^\n\"']+)[\"']?\s*$", citation, re.MULTILINE)
        self.assertGreaterEqual(len(citation_versions), 2)
        self.assertEqual({value.strip() for value in citation_versions}, {project_version})
        self.assertEqual(
            cff_scalar("url"),
            f"https://github.com/mm1ladd-g/market-analysis-audit-lab/releases/tag/v{project_version}",
        )

        release_date = cff_scalar("date-released")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{project_version}] - {release_date}", changelog)
        self.assertIn(
            f"[Unreleased]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v{project_version}...HEAD",
            changelog,
        )

        self.assertEqual(web.app.version, project_version)
        self.assertEqual(web.health()["version"], project_version)
        template = (ROOT / "audit_lab" / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("v{{ app_version }}", template)
        self.assertNotRegex(template, r"v0\.1(?:\.\d+)?")

        outcome_source = (
            ROOT / "audit_lab" / "stages" / "fetch_outcomes.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MarketAnalysisAuditLab/{__version__}", outcome_source)

    def test_compose_forwards_public_accountability_without_api_credentials(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        environment = compose["services"]["audit-web"]["environment"]

        for name in (
            "AUDIT_RELATIONSHIP_DISCLOSURE",
            "CORRECTION_CONTACT",
            "CORRECTION_POLICY_URL",
        ):
            self.assertEqual(environment[name], f"${{{name}:-}}")
        self.assertNotIn("OPENAI_API_KEY", environment)


if __name__ == "__main__":
    unittest.main()
