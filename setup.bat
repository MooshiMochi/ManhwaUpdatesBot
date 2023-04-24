@echo off
set CONFIG_FILE_NAME=config.yml

REM Check if config.yml file exists
if not exist %CONFIG_FILE_NAME% (
  echo %CONFIG_FILE_NAME% not found
  exit /B 1
)

REM Get bot token from user input
set /p BOT_TOKEN=Enter bot token: 

REM Check if token key exists in config.yml file
findstr /B "token:" %CONFIG_FILE_NAME% >nul && (
  REM Replace token value if new value is not None/Empty
  if not "%BOT_TOKEN%"=="" (
    powershell -Command "(gc %CONFIG_FILE_NAME%).TrimEnd() -replace 'token:.+', 'token: %BOT_TOKEN%' | Out-File %CONFIG_FILE_NAME% -Encoding ASCII"
  )
) || (
  REM Add new token key-value pair to config.yml file
  if not "%BOT_TOKEN%"=="" (
    powershell -Command "(Get-Content %CONFIG_FILE_NAME% -Raw).TrimEnd() + [Environment]::NewLine + 'token: %BOT_TOKEN%' | Set-Content %CONFIG_FILE_NAME%"
  )
)