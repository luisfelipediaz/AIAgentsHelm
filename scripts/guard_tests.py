"""PreToolUse (Edit|Write|MultiEdit|NotebookEdit): protege las pruebas tras la fase roja.

Una vez que la rama tiene un commit `test:`, ningún archivo de prueba se edita. Si Git no puede
responder, se permite y se avisa: el script de CI es la segunda línea de defensa.
"""

import sys
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from helm_config import load_or_defaults, project_dir
from helm_git import GitUnknown, has_test_commit, repo_root
from hook_io import Block, Warn, emit, read_event


def _suffixes(rel):
    """`a/b/c.py` → `a/b/c.py`, `b/c.py`, `c.py`: un glob con carpeta vale en cualquier nivel."""
    parts = PurePosixPath(rel).parts
    return ["/".join(parts[i:]) for i in range(len(parts))]


def _matches(glob, rel):
    candidates = _suffixes(rel) if "/" in glob else [PurePosixPath(rel).name]
    return any(fnmatchcase(candidate, glob) for candidate in candidates)


def is_test_file(rel, globs):
    return any(_matches(glob, rel) for glob in globs)


def _relative(path, root):
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _unknown(rel, error):
    return Warn(
        f"no pude saber si la rama ya tiene un commit test: ({error}); se permite editar {rel}. "
        "Configurá baseBranch en .claude/helm.config.json; el CI lo verificará igual."
    )


def _closed(rel):
    return Block(
        f"{rel} es un archivo de prueba y la rama ya tiene un commit test: (fase roja cerrada). "
        "Nunca modifiques, borres ni saltes pruebas. Si una prueba choca con un ADR, detenete y "
        "reportá el conflicto sin hacer push."
    )


def evaluate(path, project, config):
    globs = config["testGlobs"]
    try:
        root = repo_root(path)
    except GitUnknown as error:
        rel = _relative(path, Path(project).resolve())
        return [_unknown(rel, error)] if is_test_file(rel, globs) else []
    rel = _relative(path, root)
    if not is_test_file(rel, globs):
        return []
    try:
        closed = has_test_commit(path, config["baseBranch"])
    except GitUnknown as error:
        return [_unknown(rel, error)]
    return [_closed(rel)] if closed else []


def main():
    event = read_event()
    project = project_dir(event)
    config, findings = load_or_defaults(project)
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return emit(findings)
    path = (Path(project) / target).resolve()
    return emit(findings + evaluate(path, project, config))


if __name__ == "__main__":
    sys.exit(main())
