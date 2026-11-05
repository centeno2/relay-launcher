@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python
py -3 start.py %*
goto result
:python
where python >nul 2>nul
if errorlevel 1 goto missing
python start.py %*
:result
if errorlevel 1 goto failed
exit /b 0
:missing
echo Instala Python 3.12 o posterior desde python.org y activa Add python.exe to PATH.
:failed
echo No se pudo iniciar Relay. Revisa el mensaje anterior.
pause
exit /b 1
