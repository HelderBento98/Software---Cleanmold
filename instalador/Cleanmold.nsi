; Instalador do Cleanmold (NSIS 3, Unicode).
; Instala só para o usuário atual: não pede administrador e não precisa de internet.
; A pasta "tree" traz o programa pronto: Python portátil, bibliotecas e o Cleanmold.
;
;   makensis -DVERSAO=2.3.2 -DARVORE=/caminho/tree -DSAIDA=/caminho/Cleanmold_Setup_2.3.2.exe Cleanmold.nsi
;
; O arquivo é UTF-8 com BOM: sem o BOM, o makensis do Windows leria os acentos na página de código do sistema.

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef VERSAO
  !define VERSAO "1.0.0"
!endif
!ifndef ARVORE
  !define ARVORE "tree"
!endif
!ifndef SAIDA
  !define SAIDA "Cleanmold_Setup_${VERSAO}.exe"
!endif
!ifdef NSIS_WIN32_MAKENSIS
  !define B "\"
!else
  !define B "/"
!endif
!define CHAVE_DESINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\Cleanmold"
!define TESTE_BIBLIOTECAS "exec('import sys\ntry:\n import numpy, scipy, trimesh, tkinter\nexcept BaseException as e:\n sys.stderr.write(type(e).__name__ + chr(58) + chr(32) + str(e)[-600:]); sys.exit(1)')"

Name "Cleanmold ${VERSAO}"
OutFile "${SAIDA}"
InstallDir "$LOCALAPPDATA\Programs\Cleanmold"
InstallDirRegKey HKCU "Software\Cleanmold" "Pasta"
RequestExecutionLevel user
SetCompressor lzma                 ; por arquivo (não /SOLID): instala direto na pasta, sem temporário grande
SetCompressorDictSize 64
ManifestDPIAware true
BrandingText "Cleanmold ${VERSAO}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VERSAO}.0"
VIAddVersionKey /LANG=1046 "ProductName" "Cleanmold"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador do Cleanmold"
VIAddVersionKey /LANG=1046 "FileVersion" "${VERSAO}"
VIAddVersionKey /LANG=1046 "ProductVersion" "${VERSAO}"
VIAddVersionKey /LANG=1046 "LegalCopyright" "Cleanmold"

!define MUI_ICON "${ARVORE}${B}Cleanmold.ico"
!define MUI_UNICON "${ARVORE}${B}Cleanmold.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Instalar o Cleanmold ${VERSAO}"
!define MUI_WELCOMEPAGE_TEXT "Retira os alvos de escaneamento da malha e deixa o furo no lugar de cada um.$\r$\n$\r$\nA instalação é só para o seu usuário: não pede senha de administrador e não usa a internet. Ocupa cerca de 1,2 GB.$\r$\n$\r$\nSe o Cleanmold estiver aberto, feche-o antes de continuar."
!insertmacro MUI_PAGE_WELCOME

!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ConferirPasta
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Cleanmold agora"
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirCleanmold
!define MUI_FINISHPAGE_TEXT "O Cleanmold foi instalado. O ícone está no Menu Iniciar e na Área de Trabalho.$\r$\n$\r$\nA primeira abertura demora um pouco mais que as seguintes."
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "PortugueseBR"

; ---------------------------------------------------------------------------
; A instalação apaga e regrava as pastas "python", "cleanmold", "testes" e "exemplos" dentro da pasta escolhida.
; Por isso só aceita: pasta nova, pasta vazia, ou pasta de uma instalação anterior feita por este instalador.
; Devolve em $R9: "" se a pasta serve, ou o motivo de não servir.
Function .onInit
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "O Cleanmold precisa do Windows 10 ou 11 de 64 bits." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function PastaServe
  StrCpy $R9 ""
  StrLen $0 "$INSTDIR"
  ${If} $0 > 110
    StrCpy $R9 "O caminho desta pasta é comprido demais para os arquivos das bibliotecas. Escolha uma pasta com caminho mais curto."
    Return
  ${EndIf}
  ${IfNot} ${FileExists} "$INSTDIR\*.*"
    Return                                   ; pasta nova
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\Cleanmold.pyw"
    Return                                   ; pasta do Cleanmold feita por este instalador (inteira ou interrompida no meio)
  ${EndIf}
  ; vazia: serve
  FindFirst $1 $2 "$INSTDIR\*.*"
  ${DoWhile} $2 != ""
    ${If} $2 != "."
    ${AndIf} $2 != ".."
      StrCpy $R9 "Esta pasta já tem outros arquivos.$\r$\n$\r$\nEscolha uma pasta nova ou vazia para o Cleanmold."
      ${Break}
    ${EndIf}
    FindNext $1 $2
  ${Loop}
  FindClose $1
FunctionEnd

; Devolve em $R8: "1" se o Cleanmold desta pasta está aberto (python.exe ou pythonw.exe em uso não abrem para escrita)
!macro CLEANMOLD_ABERTO
  StrCpy $R8 ""
  ${If} ${FileExists} "$INSTDIR\python\pythonw.exe"
    ClearErrors
    FileOpen $0 "$INSTDIR\python\pythonw.exe" a
    ${If} ${Errors}
      StrCpy $R8 "1"
    ${Else}
      FileClose $0
    ${EndIf}
  ${EndIf}
  ${If} $R8 == ""
  ${AndIf} ${FileExists} "$INSTDIR\python\python.exe"
    ClearErrors
    FileOpen $0 "$INSTDIR\python\python.exe" a
    ${If} ${Errors}
      StrCpy $R8 "1"
    ${Else}
      FileClose $0
    ${EndIf}
  ${EndIf}
!macroend
Function CleanmoldAberto
  !insertmacro CLEANMOLD_ABERTO
FunctionEnd
Function un.CleanmoldAberto
  !insertmacro CLEANMOLD_ABERTO
FunctionEnd

Function ConferirPasta
  Call PastaServe
  ${If} $R9 != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9"
    Abort
  ${EndIf}
  Call CleanmoldAberto
  ${If} $R8 == "1"
    MessageBox MB_OK|MB_ICONEXCLAMATION "O Cleanmold está aberto.$\r$\n$\r$\nFeche a janela do Cleanmold, espere uns 15 segundos e clique em Avançar de novo."
    Abort
  ${EndIf}
  ${GetRoot} "$INSTDIR" $0
  ${DriveSpace} "$0\" "/D=F /S=M" $3
  ${If} $3 < 600
    MessageBox MB_OK|MB_ICONEXCLAMATION "Falta espaço no disco $0 para instalar: é preciso ter 600 MB livres (há $3 MB)."
    Abort
  ${EndIf}
FunctionEnd

Function AbrirCleanmold
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\python\pythonw.exe" -I "$INSTDIR\Cleanmold.pyw"'
FunctionEnd

; ---------------------------------------------------------------------------
Section "Cleanmold" SecCleanmold
  SectionIn RO

  ; a mesma conferência da página da pasta, para instalação silenciosa (/S /D=pasta) não apagar nada alheio
  Call PastaServe
  ${If} $R9 != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9" /SD IDOK
    Abort "Instalação interrompida: a pasta escolhida não serve."
  ${EndIf}

  Call CleanmoldAberto
  ${If} $R8 == "1"
    MessageBox MB_OK|MB_ICONEXCLAMATION "O Cleanmold está aberto.$\r$\n$\r$\nFeche a janela do Cleanmold, espere uns 15 segundos e rode o instalador de novo." /SD IDOK
    Abort "Instalação interrompida: o Cleanmold está aberto."
  ${EndIf}

  ClearErrors
  SetOutPath "$INSTDIR"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONEXCLAMATION "Não consegui criar a pasta:$\r$\n$INSTDIR$\r$\n$\r$\nEscolha uma pasta dentro do seu usuário (a sugerida serve)." /SD IDOK
    Abort "Instalação interrompida: não foi possível criar a pasta."
  ${EndIf}
  File "${ARVORE}${B}Cleanmold.pyw"                ; marca da pasta: daqui em diante o instalador reconhece a pasta como sua
  DetailPrint "Preparando a pasta..."
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\cleanmold"
  RMDir /r "$INSTDIR\testes"
  RMDir /r "$INSTDIR\exemplos"

  SetOutPath "$INSTDIR"
  File /r "${ARVORE}${B}*.*"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  ; atalhos (pasta de trabalho = pasta do programa)
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\Cleanmold"
  CreateShortcut "$SMPROGRAMS\Cleanmold\Cleanmold.lnk" "$INSTDIR\python\pythonw.exe" '-I "$INSTDIR\Cleanmold.pyw"' "$INSTDIR\Cleanmold.ico" 0 SW_SHOWNORMAL "" "Cleanmold - limpeza de alvos em malha escaneada"
  CreateShortcut "$DESKTOP\Cleanmold.lnk" "$INSTDIR\python\pythonw.exe" '-I "$INSTDIR\Cleanmold.pyw"' "$INSTDIR\Cleanmold.ico" 0 SW_SHOWNORMAL "" "Cleanmold - limpeza de alvos em malha escaneada"
  CreateShortcut "$SMPROGRAMS\Cleanmold\Cleanmold (diagnóstico).lnk" "$INSTDIR\ABRIR_CLEANMOLD.bat" "" "$INSTDIR\Cleanmold.ico" 0 SW_SHOWNORMAL "" "Abre o Cleanmold com a janela de mensagens"
  CreateShortcut "$SMPROGRAMS\Cleanmold\Validar a instalação.lnk" "$INSTDIR\VALIDAR.bat" "" "$INSTDIR\Cleanmold.ico" 0 SW_SHOWNORMAL "" "Limpa peças de teste e confere os resultados"
  CreateShortcut "$SMPROGRAMS\Cleanmold\LEIA-ME.lnk" "$INSTDIR\LEIA-ME.html"
  CreateShortcut "$SMPROGRAMS\Cleanmold\Desinstalar o Cleanmold.lnk" "$INSTDIR\Desinstalar.exe"

  ; registro: pasta escolhida e entrada em Configurações > Aplicativos (do usuário)
  WriteRegStr HKCU "Software\Cleanmold" "Pasta" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE_DESINST}" "DisplayName" "Cleanmold"
  WriteRegStr HKCU "${CHAVE_DESINST}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE_DESINST}" "Publisher" "Cleanmold"
  WriteRegStr HKCU "${CHAVE_DESINST}" "DisplayIcon" "$INSTDIR\Cleanmold.ico"
  WriteRegStr HKCU "${CHAVE_DESINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE_DESINST}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKCU "${CHAVE_DESINST}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKCU "${CHAVE_DESINST}" "NoModify" 1
  WriteRegDWORD HKCU "${CHAVE_DESINST}" "NoRepair" 1
  SectionGetSize ${SecCleanmold} $0
  WriteRegDWORD HKCU "${CHAVE_DESINST}" "EstimatedSize" $0

  ; conferência: as bibliotecas carregam neste computador?
  DetailPrint "Conferindo as bibliotecas (pode levar um ou dois minutos)..."
  nsExec::ExecToStack /MBCS `"$INSTDIR\python\python.exe" -I -c "${TESTE_BIBLIOTECAS}"`
  Pop $0
  Pop $1
  ${If} $0 == "0"
    DetailPrint "Bibliotecas conferidas."
  ${Else}
    DetailPrint "As bibliotecas não carregaram (código $0)."
    MessageBox MB_OK|MB_ICONEXCLAMATION "O Cleanmold foi copiado, mas as bibliotecas não carregaram neste computador (código $0).$\r$\n$\r$\n$1$\r$\n$\r$\nTire uma foto desta mensagem e envie para quem cuida do Cleanmold. Pode ser o antivírus ou uma regra da empresa bloqueando programas nesta pasta." /SD IDOK
  ${EndIf}
SectionEnd

; ---------------------------------------------------------------------------
Function un.onInit
  ${IfNot} ${FileExists} "$INSTDIR\Cleanmold.pyw"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Não achei o Cleanmold nesta pasta. Nada foi removido." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  Call un.CleanmoldAberto
  ${If} $R8 == "1"
    MessageBox MB_OK|MB_ICONEXCLAMATION "O Cleanmold está aberto.$\r$\n$\r$\nFeche a janela do Cleanmold, espere uns 15 segundos e desinstale de novo." /SD IDOK
    Abort "Desinstalação interrompida: o Cleanmold está aberto."
  ${EndIf}

  Delete "$SMPROGRAMS\Cleanmold\Cleanmold.lnk"
  Delete "$SMPROGRAMS\Cleanmold\Cleanmold (diagnóstico).lnk"
  Delete "$SMPROGRAMS\Cleanmold\Validar a instalação.lnk"
  Delete "$SMPROGRAMS\Cleanmold\LEIA-ME.lnk"
  Delete "$SMPROGRAMS\Cleanmold\Desinstalar o Cleanmold.lnk"
  RMDir "$SMPROGRAMS\Cleanmold"
  Delete "$DESKTOP\Cleanmold.lnk"

  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\cleanmold"
  RMDir /r "$INSTDIR\testes"
  RMDir /r "$INSTDIR\exemplos"
  Delete "$INSTDIR\Cleanmold.ico"
  Delete "$INSTDIR\LEIA-ME.html"
  Delete "$INSTDIR\LEIA-ME.md"
  Delete "$INSTDIR\LICENCAS_DE_TERCEIROS.txt"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\_python.bat"
  Delete "$INSTDIR\ABRIR_CLEANMOLD.bat"
  Delete "$INSTDIR\VALIDAR.bat"
  Delete "$INSTDIR\Desinstalar.exe"
  ; a marca da pasta (Cleanmold.pyw) só sai se as pastas do programa saíram de verdade; se sobrou arquivo em uso,
  ; a marca fica e o instalador aceita instalar de novo por cima
  ${If} ${FileExists} "$INSTDIR\python\*.*"
  ${OrIf} ${FileExists} "$INSTDIR\cleanmold\*.*"
  ${OrIf} ${FileExists} "$INSTDIR\testes\*.*"
  ${OrIf} ${FileExists} "$INSTDIR\exemplos\*.*"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Alguns arquivos estavam em uso e ficaram em:$\r$\n$INSTDIR$\r$\n$\r$\nFeche os programas que estiverem com arquivos dessa pasta abertos e apague a pasta." /SD IDOK
  ${Else}
    Delete "$INSTDIR\Cleanmold.pyw"
  ${EndIf}
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${CHAVE_DESINST}"
  DeleteRegKey HKCU "Software\Cleanmold"
SectionEnd
