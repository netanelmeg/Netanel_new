# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Azure Secret Monitor.

Produces two one-file executables:
  - AzureSecretMonitor.exe     (windowed GUI)
  - AzureSecretMonitorCli.exe  (console CLI, used by the Scheduled Task)

Both bundle the helper PowerShell scripts so the GUI's "Install Scheduled
Task" button continues to work from a frozen install. The MSI also drops
these scripts in the install folder, where they take precedence.

Build:
    pyinstaller --noconfirm --clean windows\\AzureSecretMonitor.spec
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

REPO = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '.'))
PY_SRC = os.path.join(REPO, 'python')
WIN_SRC = os.path.join(REPO, 'windows')


def _hidden() -> list[str]:
    mods: list[str] = []
    for top in ('azure.identity', 'azure.keyvault.secrets',
                'azure.keyvault.keys', 'azure.keyvault.certificates',
                'msgraph_core'):
        mods += collect_submodules(top)
    return mods


common_hidden = _hidden()
common_datas = (
    collect_data_files('ttkbootstrap')
    + [(os.path.join(WIN_SRC, 'Install-ScheduledTask.ps1'), 'windows'),
       (os.path.join(WIN_SRC, 'Initialize-Permissions.ps1'), 'windows')]
)

# --- GUI -------------------------------------------------------------------

gui_a = Analysis(
    [os.path.join(PY_SRC, 'gui.py')],
    pathex=[PY_SRC],
    datas=common_datas,
    hiddenimports=common_hidden + collect_submodules('ttkbootstrap'),
    cipher=block_cipher,
    noarchive=False,
)
gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data, cipher=block_cipher)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    gui_a.binaries,
    gui_a.zipfiles,
    gui_a.datas,
    [],
    name='AzureSecretMonitor',
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=None,
    version=os.path.join(WIN_SRC, 'version_info.txt'),
)

# --- CLI -------------------------------------------------------------------

cli_a = Analysis(
    [os.path.join(PY_SRC, 'cli.py')],
    pathex=[PY_SRC],
    datas=[],
    hiddenimports=common_hidden,
    cipher=block_cipher,
    noarchive=False,
)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data, cipher=block_cipher)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.zipfiles,
    cli_a.datas,
    [],
    name='AzureSecretMonitorCli',
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    icon=None,
    version=os.path.join(WIN_SRC, 'version_info.txt'),
)
