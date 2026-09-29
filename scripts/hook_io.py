"""Entrada y salida de los hooks PreToolUse según el contrato de Claude Code.

Bloquear: exit 2 con el motivo en stderr. Avisar sin bloquear: exit 0 con
`hookSpecificOutput.additionalContext` (lo ve Claude) y `systemMessage` (lo ve el usuario),
sin `permissionDecision` para no alterar el flujo normal de permisos.
"""

import json
import sys
from dataclasses import dataclass

PREFIX = "[helm]"


@dataclass(frozen=True)
class Block:
    message: str


@dataclass(frozen=True)
class Warn:
    message: str


def read_event():
    return json.loads(sys.stdin.read())


def emit(findings):
    blocks = [f"{PREFIX} Bloqueado: {f.message}" for f in findings if isinstance(f, Block)]
    warnings = [f"{PREFIX} Aviso: {f.message}" for f in findings if isinstance(f, Warn)]
    if blocks:
        print("\n".join(blocks + warnings), file=sys.stderr)
        return 2
    if warnings:
        text = "\n".join(warnings)
        print(json.dumps({
            "systemMessage": text,
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text},
        }))
    return 0
