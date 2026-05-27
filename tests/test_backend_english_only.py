"""Banned-strings regression test for backend handlers.

Fails if any pt-BR prose substring reappears in the backend. Backend
responses must be English-only (Requirements 7.1, 7.4); the frontend
owns display translation.

Scope: source files under ``backend/handlers/``, excluding
``few_shot_exporter.py`` which intentionally carries pt-BR seed examples
used as training data for the prompt classifier (not user-facing prose).
"""
from pathlib import Path

import pytest

# Case-insensitive pt-BR prose markers. These substrings are distinctive
# enough to catch the Portuguese words the frontend catalogs would
# translate, while avoiding false positives from English code/identifiers.
BANNED_SUBSTRINGS = [
    "sucesso",
    "não",
    "usuário",
    "inválido",
    "acessível",
    "obrigatório",
    "agendamento",
    "desabilitado",
    "salvo",
    "habilitado",
    "indisponível",
]

HANDLER_ROOT = Path(__file__).resolve().parent.parent / "backend" / "handlers"

# ``few_shot_exporter.py`` contains intentional pt-BR seed examples used
# by the prompt classifier as training data. These are NOT user-facing
# strings returned by API handlers and must remain as-is.
EXCLUDED_FILES = {"few_shot_exporter.py"}


def _handler_files() -> list[Path]:
    return sorted(
        p for p in HANDLER_ROOT.glob("*.py") if p.name not in EXCLUDED_FILES
    )


@pytest.mark.parametrize("handler_file", _handler_files(), ids=lambda p: p.name)
def test_no_pt_br_prose(handler_file: Path) -> None:
    """Every handler source file is free of pt-BR prose substrings."""
    text = handler_file.read_text(encoding="utf-8").lower()
    found = [s for s in BANNED_SUBSTRINGS if s.lower() in text]
    assert not found, (
        f"pt-BR prose detected in {handler_file.name}: {found}. "
        "Backend responses must be English-only (Requirements 7.1, 7.4)."
    )
