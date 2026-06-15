@echo off
REM Launch the mdconvert Telegram bot (long polling).
REM
REM Set your bot token first (get one from @BotFather):
REM     set TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
REM ...or hard-code it on the line below.
REM
REM One-time setup (from the python\ folder):
REM     pip install "python-telegram-bot>=20"
REM     pip install -r mdconvert\requirements.txt   (for PDF/Excel/Word/PowerPoint)
REM Assumes "python" is on PATH; edit PYTHON_EXE below if not.

set PYTHON_EXE=python
if "%TELEGRAM_BOT_TOKEN%"=="" (
    echo TELEGRAM_BOT_TOKEN is not set. Run:  set TELEGRAM_BOT_TOKEN=^<your token^>
    pause
    exit /b 2
)
pushd "%~dp0..\python"
"%PYTHON_EXE%" -m mdconvert.bot
popd
