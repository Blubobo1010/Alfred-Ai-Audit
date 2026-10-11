#!/usr/bin/env python3
"""Alfred brand guard (standalone copy of alfred-build's G1 check, run by alfred-ci.yml).

Fails when "Hermes" / "Nous Research" / the upstream repo slug / the caduceus survive on a
user-visible surface, unless the match is covered by scripts/alfred/guard-allowlist.txt.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).resolve().parent / "guard-allowlist.txt"

SURFACES = (
    "locales/*.yaml",
    "hermes_cli/default_soul.py",
    "agent/prompt_builder.py",
    "SOUL.md",
    "docker/SOUL.md",
    "gateway/**",
    "plugins/platforms/**",
    "hermes_cli/banner.py",
    "hermes_cli/commands.py",
    "hermes_cli/setup*.py",
    "hermes_cli/update_cmd*.py",
    "ui-tui/src/**",
    "apps/desktop/src/**",
    "apps/desktop/electron/**",
    "apps/desktop/product-identity.cjs",
    "apps/desktop/electron-builder.config.cjs",
    "apps/desktop/index.html",
    "scripts/install.sh",
    "scripts/whatsapp-bridge/bridge.js",
)
SKILL_INDEX = ("skills/**", "optional-skills/**")
BRAND_RE = re.compile(r"\bHermes\b|Hermes Agent|Nous Research|NousResearch/hermes-agent|☤|setup\.hermes-agent|HermesSetupBot")
FILE_SKIP = (".test.", "_test.", "/tests/", "/__tests__/", "/test_")


def load_allowlist() -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    spans, lines = [], []
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        (lines if raw.startswith("line:") else spans).append(re.compile(raw.removeprefix("line:")))
    return spans, lines


def in_surface(rel: str, globs: tuple[str, ...]) -> bool:
    return any(rel.startswith(g[:-3] + "/") if g.endswith("/**") else fnmatch.fnmatch(rel, g) for g in globs)


def allowed(line: str, spans: list[re.Pattern[str]]) -> bool:
    covered = [m.span() for p in spans for m in p.finditer(line)]
    return all(any(a <= m.start() and m.end() <= b for a, b in covered) for m in BRAND_RE.finditer(line))


def main() -> int:
    spans, line_pats = load_allowlist()
    failures: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv")]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(ROOT).as_posix()
            surface = in_surface(rel, SURFACES)
            skill = not surface and name == "SKILL.md" and in_surface(rel, SKILL_INDEX)
            if not (surface or skill) or (surface and any(k in "/" + rel for k in FILE_SKIP)):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            keeping = False
            for i, line in enumerate(lines, 1):
                if "alfred:keep-start" in line:
                    keeping = True
                elif "alfred:keep-end" in line:
                    keeping = False
                if keeping or "alfred:keep" in line or not BRAND_RE.search(line):
                    continue
                if skill and not line.lstrip().startswith("description:"):
                    continue
                if any(p.search(line) for p in line_pats) or allowed(line, spans):
                    continue
                failures.append(f"{rel}:{i}: {line.strip()[:160]}")
    if failures:
        print(f"brand guard: {len(failures)} line(s) still mention Hermes/Nous on user-visible surfaces")
        print("\n".join(failures[:200]))
        return 1
    print("brand guard: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
