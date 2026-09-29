import tempfile
import unittest
from pathlib import Path

from helpers import GitRepo, run_hook, warning_of
from guard_commands import evaluate
from helm_config import DEFAULTS
from hook_io import Block, Warn

PROD = {**DEFAULTS, "forbiddenPatterns": [r"sql-prod\.empresa\.com", r"--env[= ]prod"]}


class ConRepo(unittest.TestCase):
    """Cada prueba corre dentro de un repo en `feature/factura`, sin commit `test:`."""

    config = DEFAULTS

    def setUp(self):
        self.repo = GitRepo()
        self.repo.branch("feature/factura")

    def tearDown(self):
        self.repo.cleanup()

    def findings(self, command, cwd=None):
        return evaluate(command, Path(cwd or self.repo.path), self.config)

    def assertBlocks(self, command, cwd=None):
        found = self.findings(command, cwd)
        self.assertTrue(any(isinstance(f, Block) for f in found), f"no bloqueó: {command}")

    def assertAllows(self, command, cwd=None):
        found = self.findings(command, cwd)
        self.assertEqual(found, [], f"no permitió limpio: {command}")

    def assertEachBlocks(self, commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertBlocks(command)

    def assertEachAllows(self, commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertAllows(command)


class TestYProd(ConRepo):
    config = PROD

    def test_bloquea_patrones_de_test_y_prod(self):
        self.assertEachBlocks([
            'sqlcmd -S sql-prod.empresa.com -Q "select 1"',
            "SQLCMD -S SQL-PROD.EMPRESA.COM",
            "npm run deploy -- --env=prod",
            "npm run deploy -- --env prod",
            "bash -c 'curl https://sql-prod.empresa.com/health'",
        ])

    def test_permite_develop(self):
        self.assertEachAllows([
            'sqlcmd -S sql-dev.empresa.com -Q "select 1"',
            "npm run deploy -- --env=dev",
        ])

    def test_regex_invalida_avisa_y_sigue_aplicando_el_resto(self):
        self.config = {**PROD, "forbiddenPatterns": ["([", r"sql-prod\.empresa\.com"]}
        found = self.findings("sqlcmd -S sql-prod.empresa.com")
        self.assertTrue(any(isinstance(f, Block) for f in found))
        self.assertTrue(any(isinstance(f, Warn) and "([" in f.message for f in found))


class SqlDestructivo(ConRepo):
    def test_bloquea_ddl_destructivo_en_clientes_de_bd(self):
        self.assertEachBlocks([
            'psql -c "DROP TABLE clientes"',
            'sqlcmd -Q "truncate table facturas"',
            "mysql -e 'ALTER TABLE x ADD c int'",
            "mariadb -e 'drop database ventas'",
            "sqlite3 app.db 'DROP INDEX i'",
            'echo "DROP TABLE x" | psql',
        ])

    def test_bloquea_herramientas_que_destruyen_esquema(self):
        self.assertEachBlocks([
            "dotnet ef database drop -f",
            "npx prisma migrate reset --force",
            "npx typeorm schema:drop",
        ])

    def test_permite_consultas_y_menciones_fuera_de_un_cliente(self):
        self.assertEachAllows([
            'psql -c "select * from drops"',
            'grep -rn "DROP TABLE" migrations/',
            "dotnet ef database update",
            "npx prisma migrate dev",
        ])


class EvadirGit(ConRepo):
    def test_bloquea_push_forzado(self):
        self.assertEachBlocks([
            "git push --force",
            "git push -f origin feature/factura",
            "git push -uf origin feature/factura",
            "git push --force-with-lease",
            "git push --force-with-lease=feature/factura origin feature/factura",
            "git push origin +feature/factura",
        ])

    def test_permite_push_normal_de_la_feature(self):
        self.assertEachAllows([
            "git push -u origin feature/factura",
            "git push origin HEAD",
            "git push",
        ])

    def test_bloquea_no_verify(self):
        self.assertEachBlocks([
            "git commit --no-verify -m 'feat: x'",
            "git commit -n -m 'feat: x'",
            "git commit -anm 'feat: x'",
            "git push --no-verify origin feature/factura",
        ])

    def test_no_confunde_texto_del_mensaje_con_flags(self):
        self.assertAllows("git commit -m 'docs: no usar --no-verify ni --force'")

    def test_bloquea_push_a_ramas_protegidas(self):
        self.assertEachBlocks([
            "git push origin develop",
            "git push origin HEAD:develop",
            "git push origin feature/factura:refs/heads/main",
            "git push origin :develop",
            "git push origin --delete test",
            "git push --all",
            "git push --mirror",
            f"git -C {self.repo.path} push origin master",
        ])

    def test_push_sin_refspec_usa_la_rama_actual(self):
        self.repo.git("checkout", "-q", "develop")
        self.assertBlocks("git push")
        self.assertBlocks("git push origin HEAD")

    def test_respeta_protected_branches_de_la_config(self):
        self.config = {**DEFAULTS, "protectedBranches": ["release"]}
        self.assertBlocks("git push origin release")
        self.assertAllows("git push origin develop")

    def test_sigue_cd_para_saber_la_rama(self):
        otro = GitRepo()
        try:
            self.assertBlocks(f"cd {otro.path} && git push")
            self.assertAllows(f"cd {otro.path} && git status")
        finally:
            otro.cleanup()

    def test_fuera_de_un_repo_el_push_sin_refspec_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = self.findings("git push", cwd=tmp)
        self.assertEqual([type(f) for f in found], [Warn])


class ReescribirPruebas(ConRepo):
    REESCRITURAS = [
        "git commit --amend --no-edit",
        "git rebase develop",
        "git rebase -i HEAD~3",
        "git reset --soft HEAD~1",
        "git reset HEAD~1",
        "git reset HEAD^",
        "git filter-branch --tree-filter 'rm x'",
    ]

    def test_bloquea_reescribir_historia_tras_commit_test(self):
        self.repo.commit("test: factura con IVA")
        self.assertEachBlocks(self.REESCRITURAS)

    def test_permite_reescribir_en_fase_roja(self):
        self.assertEachAllows(self.REESCRITURAS)

    def test_permite_operaciones_normales_tras_commit_test(self):
        self.repo.commit("test: factura con IVA")
        self.assertEachAllows([
            "git commit -m 'feat: factura con IVA'",
            "git reset HEAD src/factura.ts",
            "git log --oneline",
        ])


class BorradoMasivo(ConRepo):
    def test_bloquea_rm_recursivo_sobre_raices(self):
        self.assertEachBlocks([
            "rm -rf /",
            "rm -rf /*",
            "rm -rf ~",
            "rm -rf ~/",
            "rm -rf $HOME",
            "rm -r .",
            "rm -rf *",
            "rm -rf ..",
            "rm -R ./",
            f"rm -fr {self.repo.path}",
            "rm --recursive --force /",
            "sudo rm -rf /",
            "rm -rf -- /",
        ])

    def test_permite_rm_acotado(self):
        self.assertEachAllows([
            "rm -rf node_modules dist",
            "rm -rf ./coverage",
            "rm -f .",
            "rm archivo.txt",
        ])

    def test_bloquea_reset_hard_y_clean(self):
        self.assertEachBlocks([
            "git reset --hard",
            "git reset --hard origin/develop",
            "git clean -fdx",
            "git clean -f",
            "git clean --force -d",
        ])

    def test_permite_clean_en_seco(self):
        self.assertAllows("git clean -n")


class Segmentos(ConRepo):
    def test_revisa_cada_segmento_del_comando(self):
        self.assertEachBlocks([
            "npm test && git push --force",
            "echo ok; rm -rf /",
            "false || git reset --hard",
            "ls\nrm -rf ~",
            "echo $(git push -f)",
        ])

    def test_permite_comandos_encadenados_inocuos(self):
        self.assertAllows("npm test -- --silent && git status | head -5")


class HookDePuntaAPunta(ConRepo):
    def run_bash(self, command):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                 "cwd": str(self.repo.path)}
        return run_hook("guard_commands.py", event, self.repo.path)

    def test_bloquea_con_exit_2_y_motivo(self):
        result = self.run_bash("git push --force")
        self.assertEqual(result.returncode, 2)
        self.assertIn("force", result.stderr)

    def test_permite_con_exit_0_sin_salida(self):
        result = self.run_bash("git status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(warning_of(result))

    def test_lee_forbidden_patterns_de_la_config_del_repo(self):
        self.repo.write_config({"forbiddenPatterns": [r"sql-prod\.empresa\.com"]})
        self.assertEqual(self.run_bash("sqlcmd -S sql-prod.empresa.com").returncode, 2)


if __name__ == "__main__":
    unittest.main()
