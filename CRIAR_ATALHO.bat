@echo off
rem Cria na Area de Trabalho um atalho "Cleanmold" com o icone do programa.
rem O caminho vai por variavel de ambiente: pastas com apostrofo, acento ou parenteses nao quebram o comando.
set "CLEANMOLD_DIR=%~dp0"
if not exist "%~dp0ABRIR_CLEANMOLD.bat" (
  echo Nao achei o ABRIR_CLEANMOLD.bat ao lado deste arquivo. Extraia a pasta inteira do .zip antes de usar.
  pause
  exit /b 1
)
powershell -NoProfile -Command "$d=$env:CLEANMOLD_DIR; $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Cleanmold.lnk')); $s.TargetPath=(Join-Path $d 'ABRIR_CLEANMOLD.bat'); $s.WorkingDirectory=$d; $s.IconLocation=((Join-Path $d 'Cleanmold.ico') + ',0'); $s.WindowStyle=1; $s.Description='Cleanmold'; $s.Save()"
if errorlevel 1 (
  echo Nao consegui criar o atalho. Crie a mao: botao direito em ABRIR_CLEANMOLD.bat, Enviar para, Area de trabalho;
  echo depois Propriedades do atalho, Alterar icone, e escolha o arquivo Cleanmold.ico desta pasta.
) else (
  echo Atalho "Cleanmold" criado na Area de Trabalho.
)
pause
