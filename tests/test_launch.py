"""launch: the command line (reaper, Proton, game arguments) and the environment the game gets."""
import time
import unittest

from fixture import PINS, Fixture

BS_APP_ID = "620980"


class LaunchTests(Fixture):
    def setUp(self):
        super().setUp()
        self.run_installer("install", mods=True)

    def launch(self, *extra: str, success: bool = True) -> tuple[dict, dict]:
        """Run launch in the foreground; return what the reaper and Proton were started with."""
        self.run_cli("launch", *extra, success=success)
        records = self.recorded()
        reaper = next((r for r in records if r.get("reaper")), None)
        proton = next(r for r in records if not r.get("reaper"))
        return reaper, proton

    def test_runs_proton_under_steams_reaper_with_game_arguments(self):
        reaper, proton = self.launch("--", "--no-yeet", "fpfc")
        game = str(self.instance / "Beat Saber.exe")
        self.assertEqual(reaper["argv"][1:], ["SteamLaunch", f"AppId={BS_APP_ID}", "--",
                                              str(self.proton / "proton"), "run", game, "--no-yeet", "fpfc"])
        self.assertEqual(proton["argv"][1:], ["run", game, "--no-yeet", "fpfc"])
        self.assertEqual(proton["cwd"], str(self.instance))

    def test_without_reaper_runs_proton_directly(self):
        (self.steam / "steamrtarm64/reaper").unlink()
        reaper, proton = self.launch()
        self.assertIsNone(reaper)
        self.assertEqual(proton["argv"][1], "run")

    def test_environment(self):
        env = self.launch()[1]["env"]
        for key in ("SteamAppId", "SteamGameId", "SteamOverlayGameId", "STEAM_COMPAT_APP_ID"):
            self.assertEqual(env[key], BS_APP_ID, key)
        self.assertEqual(env["STEAM_COMPAT_DATA_PATH"], str(self.prefix))
        self.assertEqual(env["STEAM_COMPAT_INSTALL_PATH"], str(self.instance))
        self.assertEqual(env["STEAM_COMPAT_CLIENT_INSTALL_PATH"], str(self.steam))
        self.assertEqual(env["WINEDLLPATH"], str(self.prefix / "pfx/drive_c/bs-arm64"))
        self.assertEqual(env["WINEDLLOVERRIDES"], "winhttp=n,b")
        self.assertEqual(env["DISPLAY"], ":0")
        self.assertNotIn("FDM_DEBUG", env)
        self.assertNotIn("VK_INSTANCE_LAYERS", env)

    def test_without_mods_wine_builtin_winhttp(self):
        self.assertEqual(self.launch("--no-mods")[1]["env"]["WINEDLLOVERRIDES"], "winhttp=b")

    def test_installed_without_mods_never_loads_doorstop(self):
        self.run_installer("install")
        self.assertEqual(self.launch()[1]["env"]["WINEDLLOVERRIDES"], "winhttp=b")

    def test_foveation_follows_steams_switch(self):
        self.set_foveation(True)
        env = self.launch()[1]["env"]
        self.assertEqual(env["FDM_DEBUG"], "enable")
        self.assertEqual(env["VK_INSTANCE_LAYERS"], "VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection")

    def test_foveation_switch_off(self):
        self.set_foveation(False)
        self.assertNotIn("VK_INSTANCE_LAYERS", self.launch()[1]["env"])

    def test_foveation_options_override_steam(self):
        self.set_foveation(True)
        self.assertNotIn("VK_INSTANCE_LAYERS", self.launch("--no-foveation")[1]["env"])
        self.record.unlink()
        self.set_foveation(False)
        self.assertIn("VK_INSTANCE_LAYERS", self.launch("--foveation")[1]["env"])

    def test_foveation_preset_from_environment(self):
        self.run_cli("launch", "--foveation", env=dict(self.env(), FDM_DEBUG="enable,hi"))
        self.assertEqual(self.recorded()[-1]["env"]["FDM_DEBUG"], "enable,hi")

    def test_proton_changed_since_install(self):
        self.set_proton(PINS["PROTON_TAGS"].strip('"').split()[-1] + "-new")
        result = self.run_cli("launch", success=False)
        self.assertIn("Proton changed", result.stderr)
        self.assertFalse(self.record.exists())

    def test_detach_returns_and_starts_the_game(self):
        result = self.run_cli("launch", "--detach")
        self.assertRegex(result.stdout, r"==> pid \d+")
        for _ in range(50):
            if self.record.exists() and any(not r.get("reaper") for r in self.recorded()):
                break
            time.sleep(0.1)
        self.assertEqual(self.recorded()[-1]["argv"][1], "run")


if __name__ == "__main__":
    unittest.main()
