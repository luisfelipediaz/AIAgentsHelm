"""Consultas a Git con tres respuestas: sí, no y `GitUnknown` (no se pudo averiguar)."""

import re
import subprocess
from pathlib import Path

TEST_SUBJECT = re.compile(r"^test(\([^)]*\))?!?:")


class GitUnknown(Exception):
    pass


def _git(cwd, *args):
    try:
        result = subprocess.run(
            ["git", *args], cwd=existing_dir(cwd), capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitUnknown(str(error)) from error
    if result.returncode != 0:
        raise GitUnknown(result.stderr.strip() or f"git {args[0]} terminó con {result.returncode}")
    return result.stdout


def existing_dir(path):
    """El directorio existente más cercano: el archivo a crear o su carpeta pueden no existir aún."""
    path = Path(path)
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return path


def repo_root(path):
    return Path(_git(path, "rev-parse", "--show-toplevel").strip()).resolve()


def current_branch(cwd):
    branch = _git(cwd, "branch", "--show-current").strip()
    if not branch:
        raise GitUnknown("HEAD está detached")
    return branch


def _base_ref(cwd, base):
    for ref in (base, f"origin/{base}"):
        try:
            _git(cwd, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            return ref
        except GitUnknown:
            continue
    raise GitUnknown(f"no existe la rama base '{base}' ni 'origin/{base}'")


def has_test_commit(cwd, base):
    """¿La rama ya cerró la fase roja? Busca un asunto `test:` en `<base>..HEAD`."""
    subjects = _git(cwd, "log", "--format=%s", f"{_base_ref(cwd, base)}..HEAD").splitlines()
    return any(TEST_SUBJECT.match(subject) for subject in subjects)
