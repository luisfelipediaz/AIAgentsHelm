"""Configuración por repo en `.claude/helm.config.json`, con defaults.

Tres respuestas: sin archivo → defaults; archivo válido → defaults + archivo; archivo ilegible o
mal tipado → `ConfigError` (no se sabe qué quiso configurar el repo).
"""

import json
import os
from pathlib import Path

from hook_io import Warn

CONFIG_FILE = Path(".claude") / "helm.config.json"

DEFAULTS = {
    "baseBranch": "develop",
    "protectedBranches": ["develop", "test", "main", "master"],
    "testGlobs": [
        "*.spec.*", "*.test.*", "*Tests.cs", "*Test.cs",
        "test_*.py", "*_test.py", "*_test.go",
        "tests/*", "test/*", "__tests__/*", "e2e/*", "*.Tests/*", "*.Test/*",
    ],
    # Sin default: cada repo declara sus hosts y cadenas de test y prod.
    "forbiddenPatterns": [],
}


def _is_text(value):
    return isinstance(value, str) and value != ""


def _is_text_list(value):
    return isinstance(value, list) and all(_is_text(item) for item in value)


EXPECTED = {
    "baseBranch": (_is_text, "un texto no vacío"),
    "protectedBranches": (_is_text_list, "una lista de textos"),
    "testGlobs": (_is_text_list, "una lista de textos"),
    "forbiddenPatterns": (_is_text_list, "una lista de regex (textos)"),
}


class ConfigError(Exception):
    pass


def project_dir(event):
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd())


def load(project):
    path = Path(project) / CONFIG_FILE
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"no se pudo leer: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("debe ser un objeto JSON")
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        raise ConfigError(f"claves desconocidas: {', '.join(unknown)}")
    for key, value in data.items():
        valid, description = EXPECTED[key]
        if not valid(value):
            raise ConfigError(f"{key} debe ser {description}")
    return {**DEFAULTS, **data}


def load_or_defaults(project):
    """La config y los avisos que produjo cargarla."""
    try:
        return load(project), []
    except ConfigError as error:
        return dict(DEFAULTS), [Warn(f"{CONFIG_FILE} inválida ({error}); se usan los defaults.")]
