@echo off
chcp 65001 >nul
set "AQUI=%~dp0"
if "%AQUI:~0,2%"=="\\" (
  echo O Cleanmold esta numa pasta de rede. Copie a pasta para o disco deste computador ^(por exemplo C:\Cleanmold^).
  pause
  exit /b 1
)
pushd "%~dp0"
if errorlevel 1 (
  echo Nao consegui entrar na pasta do Cleanmold. Copie a pasta para o disco deste computador ^(por exemplo C:\Cleanmold^).
  pause
  exit /b 1
)
if not exist "%~dp0cleanmold\__main__.py" (
  echo Nao achei os arquivos do Cleanmold ao lado deste arquivo.
  echo Extraia a pasta inteira do .zip antes de usar ^(nao rode de dentro do zip^).
  popd
  pause
  exit /b 1
)
call "%~dp0_python.bat"
if not defined PY (
  if defined PY_RUIM (
    echo O Python encontrado nao serve: precisa ser 3.11 a 3.14, de 64 bits.
    echo Encontrado: "%PY_RUIM%"
  ) else (
    echo Python nao encontrado.
  )
  echo Rode o INSTALAR.bat e veja o LEIA-ME.
  popd
  pause
  exit /b 1
)
"%PY%" "%~dp0testes\validar.py"
popd
pause
