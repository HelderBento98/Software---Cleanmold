# Monta o instalador do Cleanmold num Windows de verdade (é o que o GitHub Actions executa):
#   1. baixa o Python portátil (WinPython) e confere o arquivo;
#   2. instala nele as bibliotecas nas versões exatas de bibliotecas_windows.txt;
#   3. roda a validação (testes\validar.py) com esse Python;
#   4. junta o programa e compila o instalador com o NSIS;
#   5. instala em silêncio numa pasta de teste, abre o programa, confere e desinstala.
# Qualquer passo que falhe interrompe tudo: o instalador só sai se passou por todos.
#
#   pwsh instalador\montar.ps1            (na pasta do repositório)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# No GitHub Actions, o motivo da falha e os resultados principais aparecem como anotações da execução.
trap { Write-Host "::error title=Montagem do instalador::$($_.Exception.Message)"; exit 1 }

$raiz   = Split-Path -Parent $PSScriptRoot
$obra   = Join-Path $raiz 'obra'
$arvore = Join-Path $obra 'tree'
$saida  = Join-Path $raiz 'saida'
$versao = (Select-String -Path (Join-Path $raiz 'cleanmold\__init__.py') -Pattern '__version__ = "(.+?)"').Matches[0].Groups[1].Value
Write-Host "== Cleanmold $versao"

$WP_URL  = 'https://github.com/winpython/winpython/releases/download/17.12.20260522/WinPython/WinPython64-3.13.15.0dot.zip'
$WP_SHA  = '28e36408f0140c50b207ea059a599c664564e68a3cbb835f03a71f4601efd8f1'
$WP_DIR  = 'WPy64-313150'

function Conferir($codigo, $oque) { if ($codigo -ne 0) { throw "$oque falhou (código $codigo)" } }

Remove-Item $obra, $saida -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $obra, $arvore, $saida | Out-Null

# ---- 1. Python portátil
Write-Host '== 1. Python portátil'
$zip = Join-Path $obra 'winpython.zip'
Invoke-WebRequest $WP_URL -OutFile $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $WP_SHA) { throw "O WinPython baixado não confere (sha256 $hash)" }
Expand-Archive $zip -DestinationPath (Join-Path $obra 'wp')
Move-Item (Join-Path $obra "wp\$WP_DIR\python") (Join-Path $arvore 'python')
$py = Join-Path $arvore 'python\python.exe'
$sp = Join-Path $arvore 'python\Lib\site-packages'
# utilitários do WinPython que o Cleanmold não usa
foreach ($n in 'sqlite_bro*', 'wppm*', 'build', 'build-*.dist-info', 'pyproject_hooks*') {
  Get-ChildItem $sp -Filter $n -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
}

# ---- 2. bibliotecas (lista fechada: sem resolver dependências na hora)
Write-Host '== 2. bibliotecas'
& $py -I -m pip install --no-deps --no-compile --no-warn-script-location --disable-pip-version-check --only-binary=:all: -r (Join-Path $raiz 'instalador\bibliotecas_windows.txt')
Conferir $LASTEXITCODE 'A instalação das bibliotecas'
& $py -I -m pip check
Conferir $LASTEXITCODE 'A conferência de dependências (pip check)'
# O redutor de malha (pyfqmr) precisa da MSVCP140.dll, que só existe no Windows com o Visual C++ instalado.
# Vai ao lado dele a cópia que já vem dentro do numpy, com o nome que ele procura.
$dll = Get-ChildItem (Join-Path $sp 'numpy.libs') -Filter 'msvcp140*.dll' | Select-Object -First 1
if (-not $dll) { throw 'numpy.libs não trouxe a msvcp140: o redutor de malha não abriria em PC sem o Visual C++' }
Copy-Item $dll.FullName (Join-Path $sp 'pyfqmr\msvcp140.dll')

# ---- 3. validação com o Python que vai dentro do instalador
Write-Host '== 3. validação'
& $py -I (Join-Path $raiz 'testes\validar.py')
Conferir $LASTEXITCODE 'A validação'
Write-Host "::notice title=Validação em Windows::As peças de teste conferiram (testes/validar.py terminou com Tudo certo) no Python que vai dentro do instalador."

# ---- 4. programa + instalador
Write-Host '== 4. instalador'
foreach ($d in 'cleanmold', 'testes', 'exemplos') { Copy-Item (Join-Path $raiz $d) (Join-Path $arvore $d) -Recurse }
foreach ($f in 'Cleanmold.ico', 'LEIA-ME.html', 'LEIA-ME.md', 'requirements.txt', '_python.bat', 'ABRIR_CLEANMOLD.bat', 'VALIDAR.bat') {
  Copy-Item (Join-Path $raiz $f) $arvore
}
Copy-Item (Join-Path $raiz 'instalador\Cleanmold.pyw') $arvore
# o que a validação compilou não vai no instalador (o Python recompila na primeira abertura)
foreach ($d in $sp, (Join-Path $arvore 'cleanmold'), (Join-Path $arvore 'testes')) {
  Get-ChildItem $d -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
}
& $py -I (Join-Path $raiz 'instalador\licencas.py') $sp (Join-Path $arvore 'LICENCAS_DE_TERCEIROS.txt')
Conferir $LASTEXITCODE 'A lista de licenças'

$makensis = (Get-Command makensis -ErrorAction SilentlyContinue).Source
if (-not $makensis) { $makensis = Join-Path ${env:ProgramFiles(x86)} 'NSIS\makensis.exe' }
if (-not (Test-Path $makensis)) {
  choco install nsis -y --no-progress
  Conferir $LASTEXITCODE 'A instalação do NSIS'
  $makensis = Join-Path ${env:ProgramFiles(x86)} 'NSIS\makensis.exe'
}
$exe = Join-Path $saida "Cleanmold_Setup_$versao.exe"
& $makensis /V2 "/DVERSAO=$versao" "/DARVORE=$arvore" "/DSAIDA=$exe" (Join-Path $raiz 'instalador\Cleanmold.nsi')
Conferir $LASTEXITCODE 'A compilação do instalador'
Write-Host ("   {0}: {1:N0} MB" -f (Split-Path $exe -Leaf), ((Get-Item $exe).Length / 1MB))

# ---- 5. teste do instalador: instala, abre, confere, desinstala
Write-Host '== 5. teste do instalador'
$alvo = Join-Path $env:LOCALAPPDATA 'Programs\Cleanmold Teste de Instalação'      # com espaço e acento, de propósito
Remove-Item $alvo -Recurse -Force -ErrorAction SilentlyContinue
$p = Start-Process $exe -ArgumentList '/S', "/D=$alvo" -Wait -PassThru
Conferir $p.ExitCode 'A instalação silenciosa'
foreach ($f in 'Cleanmold.pyw', 'Desinstalar.exe', 'python\pythonw.exe', 'cleanmold\__main__.py', 'cleanmold\alvos\biblioteca.json', 'testes\dados\chapa.npz') {
  if (-not (Test-Path (Join-Path $alvo $f))) { throw "Depois de instalar falta $f" }
}
$atalho = Join-Path ([Environment]::GetFolderPath('Programs')) 'Cleanmold\Cleanmold.lnk'
if (-not (Test-Path $atalho)) { throw 'O atalho do Menu Iniciar não foi criado' }
& (Join-Path $alvo 'python\python.exe') -I -c "import numpy, scipy, trimesh, matplotlib, ezdxf, cadquery, tkinter"
Conferir $LASTEXITCODE 'A carga das bibliotecas na pasta instalada'

# abre como o atalho abre (pythonw, sem console) e pergunta o estado ao programa
$env:CLEANMOLD_SEM_NAVEGADOR = '1'; $env:CLEANMOLD_PORTA = '8791'; $env:CLEANMOLD_TOKEN = 'teste'
$prog = Start-Process (Join-Path $alvo 'python\pythonw.exe') -ArgumentList '-I', "`"$(Join-Path $alvo 'Cleanmold.pyw')`"" -WorkingDirectory $env:TEMP -PassThru
$ok = $false
foreach ($k in 1..60) {
  Start-Sleep -Seconds 2
  try {
    $r = Invoke-RestMethod 'http://127.0.0.1:8791/api/estado' -Headers @{ 'X-Cleanmold' = 'teste' } -TimeoutSec 5
    if ($r.versao_app -eq $versao) { $ok = $true; break }
  } catch { }
  if ($prog.HasExited) { break }
}
if (-not $prog.HasExited) { Stop-Process -Id $prog.Id -Force }
Remove-Item Env:CLEANMOLD_SEM_NAVEGADOR, Env:CLEANMOLD_PORTA, Env:CLEANMOLD_TOKEN
if (-not $ok) { throw 'O programa instalado não respondeu ao abrir sem console' }
Write-Host "   programa instalado respondeu: versão $versao"
Start-Sleep -Seconds 3

# atualização: o instalador rodado por cima de uma instalação existente (é assim que se troca de versão)
Set-Content (Join-Path $alvo 'cleanmold\sobra_da_versao_anterior.py') '# arquivo que só existia na versão anterior'
$p = Start-Process $exe -ArgumentList '/S', "/D=$alvo" -Wait -PassThru
Conferir $p.ExitCode 'A instalação por cima (atualização)'
if (Test-Path (Join-Path $alvo 'cleanmold\sobra_da_versao_anterior.py')) { throw 'A atualização deixou um arquivo da versão anterior na pasta do programa' }
$lida = & (Join-Path $alvo 'python\python.exe') -I -c "import sys; sys.path.insert(0, sys.argv[1]); import cleanmold, numpy, cadquery; print(cleanmold.__version__)" $alvo
Conferir $LASTEXITCODE 'A carga do programa depois da atualização'
if ("$lida".Trim() -ne $versao) { throw "Depois da atualização o programa diz ser a versão $lida, não $versao" }
Write-Host "   instalado por cima: versão $versao"
$p = Start-Process (Join-Path $alvo 'Desinstalar.exe') -ArgumentList '/S', "_?=$alvo" -Wait -PassThru
Conferir $p.ExitCode 'A desinstalação silenciosa'
foreach ($d in 'python', 'cleanmold', 'testes', 'exemplos') {
  if (Test-Path (Join-Path $alvo $d)) { throw "Depois de desinstalar sobrou a pasta $d" }
}
if (Test-Path $atalho) { throw 'O atalho do Menu Iniciar ficou depois de desinstalar' }
Remove-Item $alvo -Recurse -Force -ErrorAction SilentlyContinue

# pacote .zip (mesmo programa, sem o Python): para quem não puder usar o instalador
$zipar = Join-Path $obra 'Cleanmold'
New-Item -ItemType Directory -Force $zipar | Out-Null
foreach ($d in 'cleanmold', 'testes', 'exemplos') { Copy-Item (Join-Path $raiz $d) (Join-Path $zipar $d) -Recurse }
Get-ChildItem $raiz -File | Where-Object { $_.Name -notin '.gitignore', 'README.md' } | Copy-Item -Destination $zipar
Get-ChildItem $zipar -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Compress-Archive $zipar (Join-Path $saida "Cleanmold_$versao.zip")

$sha = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
$mb = [math]::Round((Get-Item $exe).Length / 1MB)
Write-Host "::notice title=Instalador testado::Cleanmold_Setup_$versao.exe ($mb MB) instalou em silêncio, abriu sem console, respondeu como versão $versao, instalou por cima (atualização) e desinstalou. SHA-256 $sha"
$novidades = (Get-Content (Join-Path $raiz 'instalador\novidades.md') -Raw -Encoding utf8).Trim()
@"
$novidades

**Para atualizar:** feche o Cleanmold e rode este instalador por cima da versão que já está no computador. Não precisa desinstalar.

Instalador validado e testado automaticamente em Windows: limpeza das peças de teste, instalação, abertura, atualização por cima e desinstalação.

**Para instalar:** baixe o ``Cleanmold_Setup_$versao.exe`` e execute. Não precisa de administrador nem de internet. O instalador não tem assinatura digital: no aviso do Windows, clique em *Mais informações > Executar assim mesmo*.

O ``Cleanmold_$versao.zip`` é o mesmo programa sem o Python, para quem não puder usar o instalador.

SHA-256 do instalador: ``$sha``
"@ | Set-Content (Join-Path $obra 'NOTAS.md') -Encoding utf8
Write-Host "== Pronto: $exe"
