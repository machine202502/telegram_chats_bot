@echo off
setlocal
cd /d "%~dp0.."
docker compose --profile local-bot-api down
pause
