"""Install the native ARM64 Beat Saber runtime into an instance and launch it on ARM64 Proton.

Modules, one job each:
  cli        command line, the commands
  output     messages for people (text) or programs (--json)
  errors     failures with a stable code
  pins       versions.env and where the release files are
  config     paths the commands work with (prefix, Proton, cache, ...) and their defaults
  instance   a Beat Saber folder: versions, backup, install record
  install    install / uninstall
  fetch      Unity's ARM64 player and OpenXR plugin, from Unity's servers
  unity_pkg  stream-extract files from Unity's .pkg installers
  openxr_patch  make the UWP UnityOpenXR.dll load in a desktop process
  proton     a Proton build: version, wine, prefix creation
  prefix     the Wine prefix: our runtime dir, registry, running processes
  steam      Steam client files: reaper, foveation switch, versions
  launch     environment and command line that start the game
  report     status (for BSManager) and doctor (for bug reports)
"""
