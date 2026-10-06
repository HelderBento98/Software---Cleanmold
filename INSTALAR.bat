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
echo ==========================================
echo  Cleanmold - instalacao das bibliotecas
echo ==========================================
call "%~dp0_python.bat"
if not defined PY (
  echo.
  if defined PY_RUIM (
    echo O Python encontrado nao serve: precisa ser 3.11 a 3.14, de 64 bits.
    echo Encontrado: "%PY_RUIM%"
  ) else (
    echo Python nao encontrado.
  )
  echo Opcao 1: extraia o WinPython 64 bits DENTRO desta pasta do Cleanmold e rode de novo.
  echo Opcao 2: instale o Python 3.12 ou 3.13 de 64 bits do python.org.
  echo Veja o LEIA-ME.
  popd
  pause
  exit /b 1
)
echo Usando: "%PY%"
"%PY%" --version
echo.
if exist "%~dp0pacotes\" (
  echo Instalando a partir da pasta "pacotes", sem internet...
  "%PY%" -m pip install --no-warn-script-location --disable-pip-version-check --no-index --find-links "%~dp0pacotes" -r "%~dp0requirements.txt"
) else (
  echo Baixando as bibliotecas: cerca de 320 MB. Leva de alguns minutos a meia hora, conforme a internet.
  "%PY%" -m pip install --no-warn-script-location --disable-pip-version-check -r "%~dp0requirements.txt"
)
if errorlevel 1 (
  echo.
  echo Falhou ao instalar as bibliotecas. O motivo esta nas linhas acima.
  echo O mais comum e a internet ou a rede da empresa bloqueando o download:
  echo nesse caso veja no LEIA-ME como instalar sem internet, pela pasta "pacotes".
  echo Tire uma foto desta tela e envie para quem cuida do Cleanmold.
  popd
  pause
  exit /b 1
)
echo.
echo Conferindo as bibliotecas, aguarde...
"%PY%" -c "import numpy, scipy, trimesh, matplotlib, ezdxf, cadquery, tkinter" >nul 2>nul
if errorlevel 1 (
  echo.
  echo As bibliotecas foram instaladas, mas nao carregam neste Python. O motivo:
  "%PY%" -c "import numpy, scipy, trimesh, matplotlib, ezdxf, cadquery, tkinter"
  echo Tire uma foto desta tela e envie para quem cuida do Cleanmold.
  popd
  pause
  exit /b 1
)
echo.
echo Instalado. Use ABRIR_CLEANMOLD.bat para abrir o programa.
echo Para um atalho com o icone na Area de Trabalho, rode CRIAR_ATALHO.bat.
echo Para conferir a instalacao, rode VALIDAR.bat.
popd
pause
