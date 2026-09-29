import tempfile
import unittest
from pathlib import Path

from helpers import GitRepo, run_hook, warning_of
from guard_tests import is_test_file
from helm_config import DEFAULTS


def edit_event(path, tool="Edit"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {key: str(path)}}


class EsArchivoDePrueba(unittest.TestCase):
    GLOBS = DEFAULTS["testGlobs"]

    def test_reconoce_pruebas_de_los_stacks_habituales(self):
        for rel in [
            "apps/web/src/app/login.component.spec.ts",
            "libs/util/fecha.test.js",
            "src/Ventas.Tests/FacturaTests.cs",
            "src/Ventas/FacturaTest.cs",
            "tests/unit/test_factura.py",
            "pkg/test_factura.py",
            "pkg/factura_test.py",
            "internal/factura_test.go",
            "src/__tests__/factura.js",
            "apps/web/e2e/login.cy.ts",
        ]:
            with self.subTest(rel=rel):
                self.assertTrue(is_test_file(rel, self.GLOBS))

    def test_no_confunde_codigo_con_pruebas(self):
        for rel in [
            "apps/web/src/app/login.component.ts",
            "src/Ventas/Contest.cs",
            "latest/factura.py",
            "src/testing-utils.ts",
            "pkg/contest.py",
        ]:
            with self.subTest(rel=rel):
                self.assertFalse(is_test_file(rel, self.GLOBS))


class GuardiaDePruebas(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo()
        self.repo.branch("feature/factura")
        self.prueba = self.repo.path / "src" / "factura.spec.ts"

    def tearDown(self):
        self.repo.cleanup()

    def hook(self, path=None, tool="Edit"):
        return run_hook("guard_tests.py", edit_event(path or self.prueba, tool), self.repo.path)

    def test_permite_editar_pruebas_en_fase_roja(self):
        self.repo.commit("chore: preparar")
        result = self.hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(warning_of(result))

    def test_bloquea_editar_pruebas_tras_commit_test(self):
        self.repo.commit("test: factura con IVA", {"src/factura.spec.ts": "it()"})
        result = self.hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn("test:", result.stderr)

    def test_bloquea_con_write_multiedit_y_notebookedit(self):
        self.repo.commit("test: factura con IVA")
        for tool, path in [
            ("Write", self.repo.path / "tests" / "nueva.spec.ts"),
            ("MultiEdit", self.prueba),
            ("NotebookEdit", self.repo.path / "tests" / "analisis.ipynb"),
        ]:
            with self.subTest(tool=tool):
                self.assertEqual(self.hook(path, tool).returncode, 2)

    def test_permite_editar_codigo_tras_commit_test(self):
        self.repo.commit("test: factura con IVA")
        result = self.hook(self.repo.path / "src" / "factura.ts")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reconoce_commit_test_con_scope_y_breaking(self):
        for subject in ["test(facturas): con IVA", "test!: cambia contrato", "test(api)!: x"]:
            with self.subTest(subject=subject):
                self.repo.commit(subject)
                self.assertEqual(self.hook().returncode, 2)
                self.repo.git("reset", "-q", "--hard", "HEAD~1")

    def test_no_confunde_otros_tipos_con_test(self):
        for subject in ["tests: plural", "testing: x", "chore: test de humo", "feat: test"]:
            with self.subTest(subject=subject):
                self.repo.commit(subject)
                self.assertEqual(self.hook().returncode, 0)

    def test_ignora_commits_test_que_ya_estaban_en_la_base(self):
        self.repo.git("checkout", "-q", "develop")
        self.repo.commit("test: de otra historia")
        self.repo.git("checkout", "-q", "-b", "feature/otra")
        self.assertEqual(self.hook().returncode, 0)

    def test_usa_origin_base_si_no_hay_base_local(self):
        self.repo.commit("test: factura con IVA")
        self.repo.git("update-ref", "refs/remotes/origin/develop", "develop")
        self.repo.git("branch", "-q", "-D", "develop")
        self.assertEqual(self.hook().returncode, 2)

    def test_respeta_base_branch_de_la_config(self):
        self.repo.git("branch", "-q", "-m", "develop", "main")
        self.repo.write_config({"baseBranch": "main"})
        self.repo.commit("test: factura con IVA")
        self.assertEqual(self.hook().returncode, 2)

    def test_respeta_test_globs_de_la_config(self):
        self.repo.write_config({"testGlobs": ["*.feature"]})
        self.repo.commit("test: factura con IVA")
        self.assertEqual(self.hook().returncode, 0)
        self.assertEqual(self.hook(self.repo.path / "specs" / "factura.feature").returncode, 2)

    def test_sin_rama_base_permite_y_avisa(self):
        self.repo.write_config({"baseBranch": "inexistente"})
        self.repo.commit("test: factura con IVA")
        result = self.hook()
        self.assertEqual(result.returncode, 0)
        self.assertIn("inexistente", warning_of(result))

    def test_fuera_de_un_repo_permite_y_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tests" / "a.spec.ts"
            result = run_hook("guard_tests.py", edit_event(path), tmp)
        self.assertEqual(result.returncode, 0)
        self.assertIsNotNone(warning_of(result))

    def test_config_invalida_usa_defaults_y_lo_dice_al_bloquear(self):
        self.repo.write_config("{no es json")
        self.repo.commit("test: factura con IVA")
        result = self.hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn("helm.config.json", result.stderr)

    def test_config_invalida_avisa_aunque_permita(self):
        self.repo.write_config('{"testGlobs": "no-es-lista"}')
        result = self.hook()
        self.assertEqual(result.returncode, 0)
        self.assertIn("testGlobs", warning_of(result))


if __name__ == "__main__":
    unittest.main()
