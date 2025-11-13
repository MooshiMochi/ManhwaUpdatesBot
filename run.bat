@echo off
setlocal enabledelayedexpansion
set CONFIG_FILE_NAME=config.yml
set VENV_NAME=venv
set PYTHON_EXE=python
set PYTHON_VERSION_REQUIRED=3.10

rem Check if the current Python version is at least the required version
%PYTHON_EXE% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if %errorlevel% neq 0 (
    set "PYTHON_EXE=python3"
    !PYTHON_EXE! -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Found a compatible Python version. Using !PYTHON_EXE!
        goto continue
    ) else (
    echo Using '!PYTHON_EXE!' executable: version %PYTHON_VERSION_REQUIRED% or later not found.
    set PYTHON_EXE=py
    echo Attempting to use '%PYTHON_EXE%' executable instead.

    for /L %%i in (19, -1, 10) do (
        set "PYTHON_EXE=py -3.%%i"
        !PYTHON_EXE! -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if !errorlevel! equ 0 (
            echo Found a compatible Python version. Using !PYTHON_EXE!
            goto continue
        )
    )
    echo Unable to find a compatible version of Python. Please install Python %PYTHON_VERSION_REQUIRED% or later and try again.
    goto common_exit
    )
)

:continue

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
%VENV_NAME%\Scripts\python -m pip install -r requirements.txt --upgrade
%VENV_NAME%\Scripts\python -m camoufox fetch

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

:common_exit
pause
exit /b 1