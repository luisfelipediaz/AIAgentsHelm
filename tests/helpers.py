import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Aísla las pruebas de la config Git del usuario (hooks, firma, rama por defecto).
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "helm",
    "GIT_AUTHOR_EMAIL": "helm@example.com",
    "GIT_COMMITTER_NAME": "helm",
    "GIT_COMMITTER_EMAIL": "helm@example.com",
}


class GitRepo:
    """Repo temporal en `develop` con un commit inicial."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name).resolve()
        self.git("init", "-q", "-b", "develop")
        self.commit("chore: inicio", {"README.md": "x"})

    def cleanup(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.path, env=GIT_ENV, check=True, capture_output=True, text=True
        ).stdout

    def branch(self, name):
        self.git("checkout", "-q", "-b", name)

    def commit(self, subject, files=None):
        for rel, content in (files or {"cambio.txt": subject}).items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject)

    def write_config(self, config):
        target = self.path / ".claude" / "helm.config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(config if isinstance(config, str) else json.dumps(config))


def run_hook(script, event, project_dir):
    env = {**GIT_ENV, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        input=json.dumps(event),
        env=env,
        capture_output=True,
        text=True,
    )


def warning_of(result):
    """El texto del aviso no bloqueante, o None si el hook no avisó."""
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
