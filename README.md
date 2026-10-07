# Cleanmold

Retira os alvos de escaneamento de uma malha 3D (peão magnético, dado impresso, dado com base) e fecha os furos continuando a superfície da peça em volta. Otimiza a malha (menos triângulos, com o desvio medido) e repara: pincel de seleção, furos, alisamento e reparo automático. Para peça de revolução, também gera o sólido em STEP e uma macro que reconstrói a peça no SolidWorks com árvore de projeto. Da mesma família do Enmold.

O manual de uso é o [LEIA-ME.md](LEIA-ME.md).

## Instalar

Em **Releases** (à direita, nesta página) fica o `Cleanmold_Setup_<versão>.exe`. Baixe e execute: instala só para o seu usuário, sem administrador e sem internet. O instalador não tem assinatura digital; no aviso do Windows, clique em *Mais informações > Executar assim mesmo*.

Ainda não há versão publicada: veja o passo abaixo para montar a primeira.

## Publicar uma versão

1. Altere o programa e a versão em `cleanmold/__init__.py`. Escreva o que mudou em `instalador/novidades.md`, atualize o LEIA-ME e rode `python instalador/leiame_html.py .` para refazer o `LEIA-ME.html`.
2. Envie as alterações para o ramo `main`.
3. No GitHub, abra a aba **Actions**, escolha o fluxo *Instalador*, clique em **Run workflow**, marque **Publicar em Releases** e confirme.
4. O GitHub faz o resto num Windows de verdade: baixa o Python portátil, instala as bibliotecas nas versões fixadas, roda a validação (`testes/validar.py`), compila o instalador, instala em silêncio, abre o programa, instala por cima, desinstala e confere. Só se tudo passar o instalador é publicado, com a marca `v<versão>`.

Sem marcar *Publicar*, o mesmo botão só monta e testa: o instalador fica nos *Artifacts* da execução por 3 dias.

## O que há em cada pasta

| Pasta / arquivo | Conteúdo |
|---|---|
| `cleanmold/` | o programa: `alvos.py` (procura dos alvos), `limpeza.py` e `remendo.py` (recorte e fechamento), `superficie.py` (referência do remendo), `otimizar.py` (redução de triângulos com desvio medido), `reparo.py` (pincel, furos, alisamento, exame e reparo), `solido.py` e `cad.py` (peça de revolução, STEP, DXF, macro), `app.py` (a sessão: malha de trabalho e desfazer), `servidor.py` e `web/` (interface) |
| `cleanmold/alvos/` | biblioteca de tipos de alvo: pé, perfil de raios e nuvem de pontos de cada um |
| `testes/` | peças de teste (`dados/*.npz`), a forma exata delas (`pecas.py`) e a validação (`validar.py`) |
| `ferramentas/` | como a biblioteca de alvos e as peças de teste foram geradas (não vão no instalador) |
| `exemplos/` | arquivos gerados para o eixo de teste |
| `instalador/` | roteiro do instalador (`Cleanmold.nsi`), lançador sem console, lista fechada de bibliotecas para Windows e o roteiro de montagem (`montar.ps1`) |

## Cuidados

- **Malhas de peças não entram neste repositório.** O `.gitignore` barra STL, PLY, OBJ e OFF; só as peças de teste sintéticas ficam aqui.
- As versões das bibliotecas são fixas (`requirements.txt` e `instalador/bibliotecas_windows.txt`): as do Enmold, mais o `pyfqmr` (redução de malha). Trocar uma versão só vale depois que a validação passar.
- A macro do SolidWorks ainda não foi executada num SolidWorks de verdade (veja o LEIA-ME).
- Os remendos são reconstruções: medidas tomadas em cima deles devem ser confirmadas na peça.
