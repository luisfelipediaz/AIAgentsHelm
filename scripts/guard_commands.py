"""PreToolUse (Bash): bloquea comandos peligrosos para el modo YOLO.

Es una red de seguridad sobre el texto del comando, no un sandbox: los límites reales son el
usuario de BD restringido y no tener credenciales de test ni prod. Cuatro categorías:
recursos de test/prod, SQL destructivo, evasión de las protecciones de Git y borrado masivo.
"""

import os
import re
import shlex
import sys
from pathlib import Path

from helm_config import load_or_defaults, project_dir
from helm_git import GitUnknown, current_branch, has_test_commit
from hook_io import Block, Warn, emit, read_event

# --- Categorías que miran el texto completo (cubren también `bash -c "…"` y `$(…)`) ---

DB_CLIENT = re.compile(r"\b(psql|sqlcmd|mysql|mariadb|sqlite3)\b", re.IGNORECASE)
DESTRUCTIVE_SQL = re.compile(r"\b(drop|truncate)\b|\balter\s+table\b", re.IGNORECASE)
SCHEMA_DESTROYERS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bdotnet\s+ef\s+database\s+drop\b",
        r"\bprisma\s+migrate\s+reset\b",
        r"\btypeorm\b.*\bschema:drop\b",
    )
]


def check_forbidden(command, config):
    findings = []
    for pattern in config["forbiddenPatterns"]:
        try:
            found = re.search(pattern, command, re.IGNORECASE)
        except re.error as error:
            findings.append(Warn(f"forbiddenPatterns tiene una regex inválida '{pattern}' ({error}); se ignora."))
            continue
        if found:
            findings.append(Block(
                f"el comando menciona un recurso de test/prod ('{found.group(0)}'). "
                "El agente solo trabaja contra develop."
            ))
    return findings


def check_destructive_sql(command, config):
    destroys_schema = any(tool.search(command) for tool in SCHEMA_DESTROYERS)
    if destroys_schema or (DB_CLIENT.search(command) and DESTRUCTIVE_SQL.search(command)):
        return [Block(
            "SQL destructivo (DROP, TRUNCATE, ALTER TABLE o una herramienta que borra el esquema). "
            "Si la historia de verdad lo necesita, que lo ejecute una persona."
        )]
    return []


TEXT_CHECKS = [check_forbidden, check_destructive_sql]

# --- Partición en segmentos (`&&`, `||`, `;`, `|`, `(`, `)`, saltos de línea) ---

PUNCTUATION = set("();<>|&")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec"}


def _tokens(command):
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:  # comillas sin cerrar: basta una partición aproximada
        return re.findall(r"[();<>|&]+|[^\s();<>|&]+", command)


def _strip_prefixes(tokens):
    """Quita `VAR=valor`, `sudo`, `env`… para llegar al programa que se ejecuta."""
    while tokens and (ASSIGNMENT.match(tokens[0]) or tokens[0] in WRAPPERS):
        tokens = tokens[1:]
    return tokens


def segments(command, cwd):
    """Pares (tokens, cwd) por comando simple; sigue los `cd` para saber dónde corre cada uno."""
    current = []
    for token in _tokens(command) + [";"]:
        if not set(token) <= PUNCTUATION:
            current.append(token)
            continue
        tokens = _strip_prefixes(current)
        current = []
        if not tokens:
            continue
        if tokens[0] == "cd":
            cwd = (cwd / os.path.expanduser(tokens[1] if len(tokens) > 1 else "~")).resolve()
            continue
        yield tokens, cwd


# --- Utilidades de flags ---


def _short_flags(args):
    """Letras de los grupos de flags cortos: `-uf` → {'u', 'f'}."""
    return {letter for arg in args if re.fullmatch(r"-[A-Za-z]+", arg) for letter in arg[1:]}


# --- rm ---

WHOLE_DIR_GLOBS = {"*", "/*", "./*", "~/*", "$HOME/*", "${HOME}/*"}


def _destroys_root(target, cwd):
    if target in WHOLE_DIR_GLOBS:
        return True
    expanded = os.path.expanduser(target.replace("${HOME}", "~").replace("$HOME", "~"))
    resolved = (cwd / expanded).resolve()
    return resolved in (Path("/"), Path.home().resolve()) or cwd.resolve().is_relative_to(resolved)


def check_rm(args, cwd, config):
    flags, targets = [], []
    for index, arg in enumerate(args):
        if arg == "--":
            targets += args[index + 1:]
            break
        (flags if arg.startswith("-") else targets).append(arg)
    recursive = "--recursive" in flags or {"r", "R"} & _short_flags(flags)
    doomed = [target for target in targets if _destroys_root(target, cwd)]
    if recursive and doomed:
        return [Block(f"rm recursivo sobre {', '.join(doomed)} borra la raíz, el home o el repo.")]
    return []


# --- git ---

GIT_GLOBALS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
PUSH_OPTIONS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
FORCE_FLAGS = {"--force", "--force-with-lease", "--force-if-includes"}
PUSH_EVERYTHING = {"--all", "--mirror", "--branches"}
RESET_MOVES_HEAD = {"--soft", "--mixed", "--keep", "--merge"}
HEAD_ANCESTOR = re.compile(r"^(HEAD|@)([~^]\d*)+$")


def _positionals(args, with_value):
    found, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg in with_value:
            skip = True
        elif not arg.startswith("-"):
            found.append(arg)
    return found


def _destination(refspec, cwd):
    ref = refspec.lstrip("+")
    dst = ref.split(":", 1)[1] if ":" in ref else ref
    if dst == "HEAD":
        dst = current_branch(cwd)
    return dst.removeprefix("refs/heads/")


def git_no_verify(sub, args, cwd, config):
    skips_hooks = "--no-verify" in args or (sub == "commit" and "n" in _short_flags(args))
    return [Block("--no-verify salta los hooks de Git; no se evaden protecciones.")] if skips_hooks else []


def git_push_force(sub, args, cwd, config):
    refspecs = _positionals(args, PUSH_OPTIONS_WITH_VALUE)[1:]
    forced = (
        FORCE_FLAGS & set(args)
        or any(arg.startswith("--force-with-lease=") for arg in args)
        or "f" in _short_flags(args)
        or any(refspec.startswith("+") for refspec in refspecs)
    )
    return [Block("git push forzado (--force, -f, --force-with-lease o refspec +) reescribe la historia remota.")] if forced else []


def git_push_protected(sub, args, cwd, config):
    protected = set(config["protectedBranches"])
    if PUSH_EVERYTHING & set(args):
        return [Block("git push --all/--mirror/--branches incluye ramas protegidas.")]
    refspecs = _positionals(args, PUSH_OPTIONS_WITH_VALUE)[1:] or ["HEAD"]
    try:
        destinations = {_destination(refspec, cwd) for refspec in refspecs}
    except GitUnknown as error:
        return [Warn(f"no pude saber la rama actual ({error}); no se verificó si el push va a una rama protegida.")]
    hit = sorted(destinations & protected)
    if hit:
        return [Block(
            f"push a la rama protegida {', '.join(hit)}. El agente solo empuja su feature branch; "
            "la integración es por PR con aprobación humana."
        )]
    return []


def _rewrites_history(sub, args):
    return {
        "commit": lambda: "--amend" in args,
        "rebase": lambda: True,
        "reset": lambda: bool(RESET_MOVES_HEAD & set(args)) or any(HEAD_ANCESTOR.match(arg) for arg in args),
        "filter-branch": lambda: True,
        "filter-repo": lambda: True,
    }.get(sub, lambda: False)()


def git_rewrite_after_red(sub, args, cwd, config):
    if not _rewrites_history(sub, args):
        return []
    try:
        closed = has_test_commit(cwd, config["baseBranch"])
    except GitUnknown as error:
        return [Warn(f"no pude saber si la rama tiene un commit test: ({error}); se permite git {sub}.")]
    if closed:
        return [Block(
            f"git {sub} reescribe la historia y la rama ya tiene un commit test:. La separación "
            "test:/feat: se conserva hasta el PR; si algo no cuadra, detenete y reportá."
        )]
    return []


def git_mass_delete(sub, args, cwd, config):
    hard_reset = sub == "reset" and "--hard" in args
    forced_clean = sub == "clean" and ("--force" in args or "f" in _short_flags(args))
    if hard_reset or forced_clean:
        return [Block(f"git {sub} {'--hard' if hard_reset else '-f'} descarta trabajo local sin vuelta atrás.")]
    return []


GIT_CHECKS = {
    "push": [git_push_force, git_push_protected],
    "commit": [git_rewrite_after_red],
    "rebase": [git_rewrite_after_red],
    "reset": [git_rewrite_after_red, git_mass_delete],
    "filter-branch": [git_rewrite_after_red],
    "filter-repo": [git_rewrite_after_red],
    "clean": [git_mass_delete],
}


def check_git(args, cwd, config):
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] == "-C" and index + 1 < len(args):
            cwd = (cwd / args[index + 1]).resolve()
        index += 2 if args[index] in GIT_GLOBALS_WITH_VALUE else 1
    if index >= len(args):
        return []
    sub, rest = args[index], args[index + 1:]
    checks = [git_no_verify] + GIT_CHECKS.get(sub, [])
    return [finding for check in checks for finding in check(sub, rest, cwd, config)]


PROGRAM_CHECKS = {"git": check_git, "rm": check_rm}


def evaluate(command, cwd, config):
    findings = [finding for check in TEXT_CHECKS for finding in check(command, config)]
    for tokens, segment_cwd in segments(command, Path(cwd)):
        check = PROGRAM_CHECKS.get(os.path.basename(tokens[0]))
        if check:
            findings += check(tokens[1:], segment_cwd, config)
    return findings


def main():
    event = read_event()
    project = project_dir(event)
    config, findings = load_or_defaults(project)
    command = (event.get("tool_input") or {}).get("command", "")
    cwd = Path(event.get("cwd") or project)
    return emit(findings + evaluate(command, cwd, config))


if __name__ == "__main__":
    sys.exit(main())
