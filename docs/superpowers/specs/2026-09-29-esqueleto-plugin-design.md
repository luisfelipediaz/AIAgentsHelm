# Esqueleto del plugin AI Agent's Helm — diseño

Fecha: 2026-09-29 · Estado: aprobado (modo automático tras decisiones clave)

## Objetivo

Dejar instalable el plugin `ai-agents-helm` con las dos protecciones que hacen seguro el modo YOLO
del flujo TDD en dos fases (opción B), antes de construir `/tdd-feature`, los subagentes y las skills
de heurísticas:

1. **Guardia de pruebas**: una vez que la rama tiene un commit `test:`, el agente no puede editar
   archivos de prueba.
2. **Guardia de comandos**: el agente no puede ejecutar comandos contra test/prod, SQL destructivo,
   evasiones de las protecciones de Git ni borrados masivos.

**Éxito**: instalado el plugin en un repo cualquiera, (a) tras el commit `test:` el agente no puede
tocar pruebas con Edit/Write/MultiEdit/NotebookEdit; (b) los comandos de las cuatro categorías se
bloquean con un motivo claro; (c) `python3 -m unittest` pasa en el repo del plugin.

## Fuera de alcance (historias siguientes)

`/tdd-feature`, subagente implementador y revisor, skills de heurísticas de Jack, script de CI,
índice de ADRs. No se crean carpetas vacías para ellos (YAGNI).

## Decisiones

| Tema | Decisión |
|---|---|
| Lenguaje | Python 3 solo stdlib (≥3.9), pruebas `unittest`, igual que Timonel |
| Configuración | `.claude/helm.config.json` por repo, con defaults; los patrones test/prod no tienen default |
| Config ausente | Hook `SessionStart` avisa una vez por sesión; los guardias usan defaults |
| Estado TDD | Deducido de Git: `git log <base>..HEAD` contiene un asunto `test:` / `test(scope):` / `test!:` |
| Rama base | `baseBranch` (default `develop`); se prueba local y luego `origin/<base>` |
| Git no responde | **Falla abierto**: permite y avisa (`additionalContext` + `systemMessage`). El CI es la segunda línea |
| Bloqueo | `exit 2` y motivo en stderr (contrato de hooks de Claude Code) |
| Aviso | `exit 0` con `hookSpecificOutput.additionalContext` + `systemMessage`, sin `permissionDecision` |

## Configuración

```json
{
  "baseBranch": "develop",
  "protectedBranches": ["develop", "test", "main", "master"],
  "testGlobs": ["*.spec.*", "*.test.*", "..."],
  "forbiddenPatterns": ["sql-prod\\.empresa\\.com", "ConnectionStrings__Prod", "--env[= ]prod"]
}
```

- Cada clave es opcional; la que falta toma su default. `forbiddenPatterns` son regex sin
  distinguir mayúsculas.
- Un JSON inválido (o una regex inválida) es la tercera respuesta ("no sé"): los guardias aplican
  los defaults y avisan; si además bloquean, el aviso va junto al motivo.
- Globs: sin `/` se comparan contra el nombre del archivo; con `/` contra la ruta relativa al repo
  o cualquier sufijo que empiece en un límite de carpeta (`tests/*` cubre `src/tests/a.py`).

## Guardia de pruebas (`scripts/guard_tests.py`, PreToolUse `Edit|Write|MultiEdit|NotebookEdit`)

1. Toma `tool_input.file_path` (o `notebook_path`). Si no es prueba según `testGlobs` → permite.
2. Busca el commit `test:` en `<base>..HEAD` del repo del archivo.
   - Sí → bloquea: "la fase roja ya se cerró; si la prueba y el ADR chocan, detenete y reportá".
   - No → permite (estamos en fase roja).
   - No sé (sin repo, sin base, error de git) → permite y avisa.

Límite conocido: editar pruebas vía Bash (`sed -i`, `>`) no pasa por este hook; lo detecta el
script de CI (historia siguiente).

## Guardia de comandos (`scripts/guard_commands.py`, PreToolUse `Bash`)

Revisa el texto del comando: es una red de seguridad, no un sandbox. Los límites reales siguen
siendo el usuario de BD restringido y no tener credenciales de test/prod. Cada categoría es una
función `(comando, contexto) -> motivo | None`; la primera que devuelve motivo bloquea.

1. **Test/prod**: cualquier `forbiddenPatterns` que aparezca en el comando.
2. **SQL destructivo**: `DROP`, `TRUNCATE` o `ALTER TABLE` en un comando que invoca un cliente de
   BD (`psql`, `sqlcmd`, `mysql`, `mariadb`, `sqlite3`, `mongosh`), o comandos de herramientas que
   destruyen esquema (`dotnet ef database drop`, `prisma migrate reset`, `typeorm schema:drop`).
3. **Evadir Git**: `git push` con `--force`/`-f`/`--force-with-lease`/refspec `+`; `--no-verify` en
   cualquier subcomando; push a una rama protegida (refspec explícito o, sin refspec, rama actual
   protegida); y, si la rama ya tiene commit `test:`, `commit --amend`, `rebase` y `reset` que mueve
   HEAD (`--soft`/`--mixed`/`--keep`/`--merge`/`HEAD~`/`HEAD^`).
4. **Borrado masivo**: `rm` recursivo (con o sin `-f`) sobre `/`, `~`, `$HOME`, `.`, `..`, `*` o la raíz del
   repo; `git reset --hard`; `git clean -f…`.

El comando se parte en segmentos por `&&`, `||`, `;`, `|` y saltos de línea; cada segmento se
tokeniza con `shlex` (si falla, por espacios). Para Git se saltan las opciones globales (`-C dir`,
`-c k=v`) y se respeta `cd dir` y `-C dir` al consultar la rama. Las categorías 1 y 2 miran el
texto completo, así que también cubren `bash -c "…"` y `$(…)`.

## Estructura

```
.claude-plugin/plugin.json
hooks/hooks.json
scripts/helm_config.py     carga de config + defaults (tres respuestas)
scripts/helm_git.py        consultas a Git (tres respuestas)
scripts/hook_io.py         lectura del evento y salida bloquear/avisar/permitir
scripts/guard_tests.py
scripts/guard_commands.py
scripts/session_start.py
tests/                     unittest con repos Git temporales reales
```

## Pruebas

- Cada guardia se prueba de punta a punta (JSON por stdin → exit code / stdout) contra repos Git
  temporales, más pruebas unitarias de las reglas de comandos.
- Cada caso de bloqueo tiene su gemelo que permite, para que la aserción no sea vacua.
- Se cubre la rama "no sé" (sin base, fuera de repo, JSON inválido).
