"""SessionStart: avisa una vez por sesión si la config del repo falta, es inválida o está incompleta.

El stdout de SessionStart entra al contexto de Claude.
"""

import sys

from helm_config import CONFIG_FILE, ConfigError, load, project_dir
from hook_io import PREFIX, read_event

EXAMPLE = '{"baseBranch": "develop", "forbiddenPatterns": ["sql-prod\\\\.empresa\\\\.com"]}'


def messages(project):
    try:
        config = load(project)
    except ConfigError as error:
        return [f"{PREFIX} {CONFIG_FILE} inválida: {error}. Los guardias usan los defaults hasta que se corrija."]
    if not (project / CONFIG_FILE).is_file():
        return [
            f"{PREFIX} No existe {CONFIG_FILE}: los guardias usan los defaults (base develop) y no "
            f"reconocen los hosts de test y prod. Crealo con forbiddenPatterns, p. ej. {EXAMPLE}"
        ]
    if not config["forbiddenPatterns"]:
        return [
            f"{PREFIX} forbiddenPatterns está vacío en {CONFIG_FILE}: el guardia de comandos no "
            "reconoce los hosts ni las cadenas de conexión de test y prod."
        ]
    return []


def main():
    for line in messages(project_dir(read_event())):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
