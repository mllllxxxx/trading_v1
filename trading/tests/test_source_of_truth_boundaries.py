from __future__ import annotations

import re
from pathlib import Path

from rulebook import compile_rulebook


REPO_ROOT = Path(__file__).resolve().parents[2]
TRADING_ROOT = REPO_ROOT / "trading"
PROCESS_BANNER = (
    "> Development-process document only. This file is not trading policy, "
    "not runtime configuration, not LLM trading context, and not rulebook "
    "source of truth."
)


FORBIDDEN_POLICY_PATTERNS = [
    re.compile(r"\b\d+\s*x\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*%"),
    re.compile(r"risk\s+\d+", re.IGNORECASE),
    re.compile(r"max\s+positions?\s*[:=]?\s*\d+", re.IGNORECASE),
    re.compile(r"confidence\s*[><=]", re.IGNORECASE),
]


def test_root_readme_and_agents_do_not_define_concrete_trading_policy() -> None:
    """Root routing docs must not become trading policy sources."""
    for relative_path in ("README.md", "AGENTS.md"):
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_POLICY_PATTERNS:
            assert not pattern.search(content), (
                f"{relative_path} contains policy-looking value matching "
                f"{pattern.pattern!r}"
            )


def test_harness_docs_are_process_only() -> None:
    """Every demoted Harness doc must declare that it is not trading context."""
    harness_dir = REPO_ROOT / "docs" / "harness"
    docs = sorted(harness_dir.rglob("*.md"))
    assert docs
    for path in docs:
        content = path.read_text(encoding="utf-8")
        assert content.startswith(PROCESS_BANNER), path.relative_to(REPO_ROOT)


def test_runtime_context_docs_deny_process_sources() -> None:
    """Runtime/RAG policy must deny process docs and root routing docs."""
    required_docs = [
        TRADING_ROOT / "docs" / "architecture" / "RUNTIME_CONTEXT_BOUNDARIES.md",
        TRADING_ROOT / "docs" / "architecture" / "RAG_INDEXING_POLICY.md",
    ]
    for path in required_docs:
        content = path.read_text(encoding="utf-8")
        assert "Role: runtime contract" in content
        assert "`docs/harness/`" in content
        assert "`AGENTS.md`" in content
        assert "`README.md`" in content


def test_rulebook_compiler_uses_allowlisted_source_root_only() -> None:
    """Rulebook compiler source roots must stay inside canonical rulebook source."""
    source_root = compile_rulebook.SOURCE_ROOT.resolve()
    assert source_root == (TRADING_ROOT / "rulebook" / "source").resolve()
    assert "harness" not in source_root.as_posix().lower()


def test_runtime_python_does_not_reference_process_docs_as_context() -> None:
    """Trading runtime modules must not hardcode process docs as context sources."""
    runtime_roots = [
        "auto",
        "rulebook",
        "llm",
        "context",
        "verifier",
        "risk",
        "execution",
    ]
    forbidden_tokens = [
        "docs/harness",
        "docs\\harness",
        "HARNESS.md",
        "FEATURE_INTAKE.md",
        "AGENTS.md",
        "README.md",
    ]
    offenders: list[str] = []
    for root_name in runtime_roots:
        root = TRADING_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            content = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in content:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} references {token}")

    assert offenders == []
