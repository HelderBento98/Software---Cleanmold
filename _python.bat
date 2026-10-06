@echo off
rem Localiza o Python que o Cleanmold vai usar. Serve Python 3.11 a 3.14, de 64 bits.
rem Ordem: a pasta python do instalador; WinPython extraido dentro desta pasta; qualquer python.exe dentro dela; o lancador "py" do python.org;
rem o Python que estiver no PATH. Cada candidato e testado antes de ser aceito.
set "PY="
set "PYW="
set "PY_RUIM="
if exist "%~dp0python\python.exe" call :testar "%~dp0python\python.exe"
if defined PY goto :achou
for /d %%D in ("%~dp0WPy64-*") do if not defined PY if exist "%%~D\python\python.exe" call :testar "%%~D\python\python.exe"
if defined PY goto :achou
for /f "delims=" %%F in ('dir /b /s "%~dp0python.exe" 2^>nul') do if not defined PY call :testar "%%F"
if defined PY goto :achou
for %%V in (3.13 3.12 3.14 3.11) do if not defined PY for /f "delims=" %%F in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do call :testar "%%F"
if defined PY goto :achou
for /f "delims=" %%F in ('where python.exe 2^>nul') do if not defined PY call :testar "%%F"
if defined PY goto :achou
goto :fim
:testar
"%~1" -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) and sys.maxsize > 2**32 else 1)" >nul 2>nul
if not errorlevel 1 (
  set "PY=%~1"
  exit /b 0
)
rem So guarda como "Python que nao serve" um Python que roda de verdade (o atalho da Microsoft Store nao roda).
if defined PY_RUIM exit /b 0
"%~1" -c "pass" >nul 2>nul
if not errorlevel 1 set "PY_RUIM=%~1"
exit /b 0
:achou
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"
:fim
