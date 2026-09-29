# AI Agent's Helm

Plugin de Claude Code (`ai-agents-helm`) que funciona como el timón para trabajar con agentes de IA
en **modo YOLO** (sin confirmaciones) de forma segura y con calidad de diseño.

El agente trabaja en feature branches contra develop, con un flujo TDD en dos fases: primero las
pruebas (`test:`), luego la implementación (`feat:`), un solo PR a develop y revisión humana. El
merge develop → test es el paso manual, forzado con branch protection.

## Qué incluye hoy (v0.1.0)

| Pieza | Evento | Qué hace |
|---|---|---|
| `scripts/guard_tests.py` | PreToolUse `Edit\|Write\|MultiEdit\|NotebookEdit` | Si la rama ya tiene un commit `test:` (en `<base>..HEAD`), bloquea la edición de archivos de prueba |
| `scripts/guard_commands.py` | PreToolUse `Bash` | Bloquea recursos de test/prod, SQL destructivo, evasión de Git y borrado masivo |
| `scripts/session_start.py` | SessionStart | Avisa si falta `.claude/helm.config.json`, si es inválido o si no declara los patrones de test/prod |

En camino: skill `/tdd-feature`, subagente implementador (fase 2), revisor de ADRs/YAGNI/KISS,
skills de heurísticas de diseño y script de CI que verifica la separación `test:`/`feat:`.

## Instalación

Requiere `python3` (≥3.9, solo stdlib) y `git` en el PATH.

Todavía no está publicado en un marketplace; se carga desde el directorio:

```bash
claude --plugin-dir /ruta/a/AIAgentsHelm
```

## Configuración por repo

`.claude/helm.config.json` (todas las claves son opcionales):

```json
{
  "baseBranch": "develop",
  "protectedBranches": ["develop", "test", "main", "master"],
  "testGlobs": ["*.spec.*", "*.test.*", "*Tests.cs", "tests/*"],
  "forbiddenPatterns": ["sql-prod\\.empresa\\.com", "sql-test\\.empresa\\.com", "ConnectionStrings__Prod", "--env[= ]prod"]
}
```

| Clave | Default | Notas |
|---|---|---|
| `baseBranch` | `develop` | Se busca local y luego `origin/<base>` |
| `protectedBranches` | `develop`, `test`, `main`, `master` | Destinos a los que el agente nunca empuja |
| `testGlobs` | `*.spec.*`, `*.test.*`, `*Tests.cs`, `*Test.cs`, `test_*.py`, `*_test.py`, `*_test.go`, `tests/*`, `test/*`, `__tests__/*`, `e2e/*`, `*.Tests/*`, `*.Test/*` | Sin `/`: contra el nombre del archivo. Con `/`: contra la ruta relativa en cualquier nivel |
| `forbiddenPatterns` | *(vacío)* | Regex sin distinguir mayúsculas. **Declaralos**: sin ellos el guardia no reconoce test/prod |

## Qué bloquea el guardia de comandos

1. **Test/prod**: cualquier `forbiddenPatterns` en el texto del comando.
2. **SQL destructivo**: `DROP`, `TRUNCATE`, `ALTER TABLE` junto a `psql`, `sqlcmd`, `mysql`, `mariadb`
   o `sqlite3`; `dotnet ef database drop`, `prisma migrate reset`, `typeorm schema:drop`.
3. **Evadir Git**: `push` forzado (`--force`, `-f`, `--force-with-lease`, refspec `+`), `--no-verify`
   (y `commit -n`), push a ramas protegidas (incluido `--all`/`--mirror` y borrados remotos) y, con
   commit `test:` en la rama, `commit --amend`, `rebase`, `reset` que mueve HEAD y `filter-branch`.
4. **Borrado masivo**: `rm` recursivo sobre `/`, `~`, `$HOME`, `*` o cualquier ancestro del
   directorio actual; `git reset --hard`; `git clean -f`.

## Límites (a propósito)

- **Es una red de seguridad, no un sandbox.** Revisa el texto del comando; un agente decidido
  puede ofuscarlo. Los límites reales son el usuario de BD restringido, no tener credenciales de
  test/prod y las branch protections.
- **Falla abierto.** Si Git no responde (sin rama base, HEAD detached, fuera de un repo) o la config
  es inválida, permite y avisa al usuario y a Claude. El script de CI es la segunda línea de defensa.
- Editar pruebas vía Bash (`sed -i`, redirecciones) no pasa por el guardia de pruebas; lo detecta el CI.

## Fuera del plugin (en cada repo)

ADRs y su índice, `CLAUDE.md` del proyecto, script de verificación del CI, branch protections
(PR con aprobación humana en test y prod; el agente no aprueba ni empuja directo) y credenciales en
variables de entorno.

## Desarrollo

```bash
python3 -m unittest discover -s tests
claude plugin validate .
```

Diseño: [`docs/superpowers/specs/2026-09-29-esqueleto-plugin-design.md`](docs/superpowers/specs/2026-09-29-esqueleto-plugin-design.md).
Commits en Conventional Commits; el propio repo sigue el flujo `test:` → `feat:`.
