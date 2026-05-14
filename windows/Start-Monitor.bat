@echo off
REM Launch the Azure Secret Monitor GUI.
REM Assumes "python" is on PATH; edit PYTHON_EXE below if not.

set PYTHON_EXE=python
pushd "%~dp0..\python"
start "" "%PYTHON_EXE%" gui.py
popd
