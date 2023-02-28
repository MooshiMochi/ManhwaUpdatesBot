@echo off
set CONFIG_FILE_NAME=config.yml
set PYTHON_EXE=python
set VENV_NAME=.venv

%PYTHON_EXE% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed. Please install Python and try again.
    pause
    exit /b 1
)

rem Check Python version
%PYTHON_EXE% -c "import sys; sys.exit(not (sys.version_info.major >= 3 and sys.version_info.minor >= 11))"

if %errorlevel% neq 0 (
    echo You need at least Python 3.11 to run the bot.
    pause
    exit /b 1
)

rem Check if config file exists. If it doesn't, copy the example config file.
if not exist %CONFIG_FILE_NAME% (
    copy %CONFIG_FILE_NAME%.example %CONFIG_FILE_NAME%
)


rem Create virtual environment
if not exist %VENV_NAME% (
    %PYTHON_EXE% -m venv %VENV_NAME%
)

rem Upgrade pip and install requirements
%VENV_NAME%\Scripts\python -m pip install --upgrade pip
%VENV_NAME%\Scripts\python -m pip install -r requirements.txt

REM Check if token key exists in config.yml file
findstr /B "token:" %CONFIG_FILE_NAME% >nul
if %errorlevel% equ 0 (
    REM Token key exists
) else (
    REM Token key does not exist
    if "%BOT_TOKEN%"=="" (
        rem Run setup script
        call setup.bat
    )
)

cls

rem Run main.py
%VENV_NAME%\Scripts\python main.py