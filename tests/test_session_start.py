import tempfile
import unittest

from helpers import GitRepo, run_hook
from helm_config import DEFAULTS, ConfigError, load


class CargaDeConfig(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo()

    def tearDown(self):
        self.repo.cleanup()

    def test_sin_archivo_devuelve_defaults(self):
        self.assertEqual(load(self.repo.path), DEFAULTS)

    def test_completa_con_defaults_las_claves_ausentes(self):
        self.repo.write_config({"baseBranch": "main"})
        config = load(self.repo.path)
        self.assertEqual(config["baseBranch"], "main")
        self.assertEqual(config["testGlobs"], DEFAULTS["testGlobs"])

    def test_json_invalido_es_error(self):
        self.repo.write_config("{no es json")
        with self.assertRaises(ConfigError):
            load(self.repo.path)

    def test_tipo_incorrecto_es_error_con_la_clave(self):
        for config, clave in [
            ({"baseBranch": 3}, "baseBranch"),
            ({"testGlobs": "*.spec.ts"}, "testGlobs"),
            ({"forbiddenPatterns": [1]}, "forbiddenPatterns"),
        ]:
            with self.subTest(clave=clave):
                self.repo.write_config(config)
                with self.assertRaisesRegex(ConfigError, clave):
                    load(self.repo.path)

    def test_clave_desconocida_es_error(self):
        self.repo.write_config({"basebranch": "main"})
        with self.assertRaisesRegex(ConfigError, "basebranch"):
            load(self.repo.path)


class InicioDeSesion(unittest.TestCase):
    def run_session(self, project_dir):
        return run_hook("session_start.py", {"hook_event_name": "SessionStart"}, project_dir)

    def test_avisa_si_falta_la_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_session(tmp)
        self.assertEqual(result.returncode, 0)
        self.assertIn("helm.config.json", result.stdout)

    def test_avisa_si_no_hay_patrones_de_test_y_prod(self):
        repo = GitRepo()
        try:
            repo.write_config({"baseBranch": "develop"})
            result = self.run_session(repo.path)
        finally:
            repo.cleanup()
        self.assertIn("forbiddenPatterns", result.stdout)

    def test_avisa_si_la_config_es_invalida(self):
        repo = GitRepo()
        try:
            repo.write_config("{no es json")
            result = self.run_session(repo.path)
        finally:
            repo.cleanup()
        self.assertEqual(result.returncode, 0)
        self.assertIn("inválida", result.stdout)

    def test_calla_con_config_completa(self):
        repo = GitRepo()
        try:
            repo.write_config({"forbiddenPatterns": ["sql-prod"]})
            result = self.run_session(repo.path)
        finally:
            repo.cleanup()
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
