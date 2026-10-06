"""Architecture rule: the domain layer imports only the standard library.

import-linter guards the boundaries between Masdar's own layers. This test
guards the boundary with the outside world, which import-linter cannot express
for packages that are not installed yet: any import in ``masdar.domain`` must
be stdlib or ``masdar.domain`` itself. See ADR-0001.
"""

import ast
import sys
from pathlib import Path

import masdar.domain

DOMAIN_DIR = Path(masdar.domain.__file__).parent


def _imported_top_level_modules(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _is_allowed(module: str) -> bool:
    return module.split(".", maxsplit=1)[0] in sys.stdlib_module_names or module.startswith(
        "masdar.domain"
    )


def test_domain_imports_only_stdlib_and_itself() -> None:
    violations = {
        f"{path.name}: {module}"
        for path in DOMAIN_DIR.rglob("*.py")
        for module in _imported_top_level_modules(path)
        if not _is_allowed(module)
    }
    assert not violations, f"domain must stay pure, found: {sorted(violations)}"


def test_rule_detects_a_third_party_import(tmp_path: Path) -> None:
    offender = tmp_path / "bad.py"
    offender.write_text("import numpy\nfrom masdar.adapters import x\n", encoding="utf-8")
    assert {m for m in _imported_top_level_modules(offender) if not _is_allowed(m)} == {
        "numpy",
        "masdar.adapters",
    }
