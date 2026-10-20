"""What BSManager relies on. Released BSManager versions call an unpacked release exactly like
`bash '<release>/bs-arm64.sh' install '<instance>' --prefix '<compatdata>' --proton '<proton>' [--no-mods]`
through a shell, read stdout/stderr lines and the exit code, and read files in .bs-arm64/ and the
prefix runtime dir. Newer ones use --json and status. None of this may change incompatibly."""
import json
import shutil
import subprocess
import unittest

from fixture import ARTIFACTS, PINS, ROOT, Fixture


class ReleaseFixture(Fixture):
    def setUp(self):
        super().setUp()
        # Unpacked release tarball, as build.sh package lays it out (with a ' in the path)
        self.release = self.root / "it's/bs-arm64-v9.9.9-proton"
        shutil.copytree(ROOT / "install/bs_arm64", self.release / "bs_arm64",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "install/bs-arm64.sh", self.release)
        shutil.copy(ROOT / "versions.env", self.release)
        (self.release / "VERSION").write_text("v9.9.9\n")
        for name in ARTIFACTS:
            shutil.copy(self.artifacts / name, self.release)
        # Default cache: ~/.cache/bs-arm64
        shutil.copytree(self.cache, self.home / ".cache/bs-arm64")

    @staticmethod
    def quote(value) -> str:  # BSManager's bs-arm64.service.ts quote()
        return "'" + str(value).replace("'", "'\"'\"'") + "'"

    def bsmanager(self, *args: str, success: bool = True) -> subprocess.CompletedProcess:
        command = " ".join(["bash", self.quote(self.release / "bs-arm64.sh"), *args])
        result = subprocess.run(command, check=False, shell=True, env=self.env(), capture_output=True, text=True,
                                timeout=45)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result


class OldBsManagerTests(ReleaseFixture):
    def prefix_args(self):
        return ["--prefix", self.quote(self.prefix), "--proton", self.quote(self.proton)]

    def test_install_writes_the_files_bsmanager_reads(self):
        self.bsmanager("install", self.quote(self.instance), *self.prefix_args())
        state = self.instance / ".bs-arm64"
        self.assertEqual((state / "installed").read_text().strip(), "1.44.1")
        self.assertEqual((state / "mods").read_text().strip(), "1")
        build = f'{PINS["PROTON_TAG"]}-arm64'
        self.assertEqual((state / "proton-version").read_text().strip(), build)
        # BSManager's launch sets WINEDLLPATH to this dir and checks this file against Proton
        self.assertEqual((self.prefix / "pfx/drive_c/bs-arm64/proton-version").read_text().strip(), build)

    def test_no_mods_and_uninstall(self):
        self.bsmanager("install", self.quote(self.instance), *self.prefix_args(), "--no-mods")
        self.assertEqual((self.instance / ".bs-arm64/mods").read_text().strip(), "0")
        self.bsmanager("uninstall", self.quote(self.instance), *self.prefix_args())
        self.assert_uninstalled()

    def test_failure_is_exit_code_and_last_stderr_line(self):
        self.set_proton("GE-Proton11-7")
        result = self.bsmanager("install", self.quote(self.instance), *self.prefix_args(), success=False)
        last = result.stderr.strip().splitlines()[-1]
        self.assertTrue(last.startswith("error: Proton is GE-Proton11-7"), last)
        self.assertFalse((self.instance / ".bs-arm64").exists())

    def test_steps_are_plain_lines_on_stdout(self):
        result = self.bsmanager("install", self.quote(self.instance), *self.prefix_args())
        self.assertIn("==> done", result.stdout.splitlines())


class JsonTests(ReleaseFixture):
    def args(self, command: str, *extra: str) -> list[str]:
        return [command, self.quote(self.instance), "--prefix", self.quote(self.prefix),
                "--proton", self.quote(self.proton), "--json", *extra]

    def json(self, *args: str, success: bool = True) -> list[dict]:
        return self.json_lines(self.bsmanager(*args, success=success))

    def test_install_reports_log_lines(self):
        lines = self.json(*self.args("install"))
        self.assertTrue(all(line["type"] == "log" for line in lines), lines)
        self.assertEqual(lines[-1]["message"], "done")

    def test_error_has_a_code(self):
        self.set_proton("GE-Proton11-7")
        lines = self.json(*self.args("install"), success=False)
        self.assertEqual(lines[-1]["type"], "error")
        self.assertEqual(lines[-1]["code"], "PROTON_UNTESTED")

    def test_status_before_and_after_install(self):
        before = self.json(*self.args("status"))[-1]
        self.assertEqual(before["type"], "result")
        self.assertEqual(before["api"], 1)
        self.assertEqual(before["version"], "v9.9.9")
        self.assertEqual(before["gameVersion"], "1.44.1")
        self.assertTrue(before["engineSupported"])
        self.assertFalse(before["installed"])
        self.assertFalse(before["ready"])

        self.json(*self.args("install", "--no-mods"))
        after = self.json(*self.args("status"))[-1]
        self.assertTrue(after["installed"])
        self.assertFalse(after["mods"])
        self.assertTrue(after["protonTested"])
        self.assertTrue(after["ready"])

        self.set_proton("proton-11.0-2e")  # Steam updated Proton: install must run again
        self.assertFalse(self.json(*self.args("status"))[-1]["ready"])

    def test_launch_not_installed(self):
        lines = self.json(*self.args("launch"), success=False)
        self.assertEqual(lines[-1]["code"], "NOT_INSTALLED")


class DoctorTests(ReleaseFixture):
    def test_report(self):
        self.bsmanager("install", self.quote(self.instance), "--prefix", self.quote(self.prefix),
                       "--proton", self.quote(self.proton))
        report = json.loads(self.bsmanager("doctor", self.quote(self.instance), "--prefix", self.quote(self.prefix),
                                           "--proton", self.quote(self.proton)).stdout)
        self.assertEqual(report["bs-arm64"]["version"], "v9.9.9")
        self.assertEqual(report["Proton"]["build"], f'{PINS["PROTON_TAG"]}-arm64')
        self.assertEqual(report["Instance"]["Beat Saber"], "1.44.1")
        self.assertEqual(report["Instance"]["bs-arm64 installed"], "yes")
        self.assertEqual(report["Steam"]["reaper"], "found")

    def test_without_instance_and_without_steam(self):
        shutil.rmtree(self.steam)
        report = json.loads(self.bsmanager("doctor").stdout)
        self.assertEqual(report["Steam"]["client"], "unknown")
        self.assertNotIn("Instance", report)


if __name__ == "__main__":
    unittest.main()
