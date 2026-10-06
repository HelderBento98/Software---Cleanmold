# Cleanmold

Retira os alvos de escaneamento de uma malha 3D e fecha os furos continuando a superfície da peça que está em volta. Da mesma família do Enmold.

Tudo roda no computador: a malha, a análise e os arquivos não são enviados pela internet.

## Instalar

Execute o `Cleanmold_Setup_<versão>.exe`. Instala só para o seu usuário, sem senha de administrador e sem internet, e ocupa cerca de 1,2 GB. O instalador não tem assinatura digital: no aviso do Windows, clique em *Mais informações > Executar assim mesmo*.

Depois de instalado, o Cleanmold fica no Menu Iniciar e na Área de Trabalho. Para atualizar, rode o instalador novo por cima.

## Usar

1. **Exporte a malha** do Control X ou do Design X em STL (também PLY, OBJ ou OFF), em milímetros, com os alvos como saíram do escaneamento. Não precisa alinhar nem separar nada.
2. **Abrir malha.** A procura dos alvos começa sozinha. Numa malha de 8 milhões de triângulos leva cerca de um minuto.
3. **Confira a lista.** Cada alvo aparece em verde no modelo e numa linha da lista, com a confiança. Clique numa linha para ver o alvo de perto.
   - Não é alvo: desmarque a linha. Fica em laranja e não é tocado.
   - Faltou um alvo: use a ferramenta com a mira, na barra de cima, informe o diâmetro do recorte e clique no **pé** do alvo.
4. **Retirar e fechar os furos.** Depois, use **Antes** e **Depois** para comparar. Os remendos aparecem em verde-claro.
5. **Gerar arquivos:** malha limpa (STL), relatório (PDF) e, para peça de revolução, sólido (STEP) e macro do SolidWorks.

### No modelo 3D

Arraste para girar, role para aproximar, botão direito para mover. Os botões de vista (Isométrica, Cima, Frente, Lado) usam os eixos da própria malha.

## O que o Cleanmold entende por alvo

Um alvo não é procurado pela malha exata dele, e sim pelo padrão:

- um **pé cilíndrico** de diâmetro conhecido em pé sobre a peça (a base magnética: Ø 18,8 mm no peão, Ø 14,9 mm no dado com base);
- acima do pé, um corpo cujo perfil de raios lembra o de um alvo: ressalto, pescoço fino, esfera, dodecaedro.

O corpo pode vir amassado, torto, com caroços ou partido em pedaços soltos. O que decide é o pé e o que vem logo acima dele. Quando o pé também saiu amassado (um caroço em vez de um cilindro), o alvo é achado pela esfera ou pelo dodecaedro que sobraram e aparece como **pé amassado**.

Tipos que vêm com o programa:

| Tipo | Pé | Corpo |
|---|---|---|
| Peão magnético | Ø 18,8 × 6 mm | pescoço e esfera Ø 9,8 mm; 25 mm de altura |
| Peão com dado impresso | Ø 18,8 × 6 mm | esfera Ø 15,3 mm e dodecaedro em cima; 59 mm de altura |
| Dado com base cilíndrica | Ø 14,9 × 4 mm | dodecaedro apoiado direto na base; 29 mm de altura |

**Pedaços soltos** (esferas, dodecaedros e lascas que o escaneamento separou da peça) são apagados junto. Para mantê-los, desmarque *Apagar pedaços soltos*.

A **confiança** vai de 0 a 100 %. Alvos com menos de 50 % entram na lista desmarcados: confira no modelo e marque se forem alvos.

## Como o furo é fechado

1. A superfície da peça em volta do pé é ajustada ao modelo mais simples que explica a vizinhança: **plano**, **cilindro**, **esfera**, **cone** ou **superfície curva suave** (para fundidos, chapas calandradas e raios grandes).
2. O pé é recortado junto com o que estiver grudado nele acima dessa superfície (rebarba, caroço do escaneamento). O corpo do alvo, que fica solto, é apagado.
3. O remendo é gerado sobre a superfície ajustada e emendado no contorno do furo.

Casos especiais tratados:

- **Alvo na beirada**, com o furo descendo por uma parede: a aresta viva entre a face de cima e a parede é refeita.
- **Alvo na borda da malha**: a borda é refeita em linha reta naquele trecho.
- **Peça fina ou eixo**: o lado oposto da peça nunca é tocado.

Dois ajustes, no painel da esquerda:

- **Margem** (padrão 1,2 mm): quanto o recorte entra na superfície limpa em volta do pé.
- **Alcance** (padrão 8 mm): até onde, em volta do pé, o que estiver grudado nele é recortado quando a rebarba não termina sozinha (por exemplo, quando ela vai até uma parede).

## O que conferir antes de confiar

- O remendo é uma **reconstrução**. A superfície debaixo do alvo não foi escaneada. Em superfície lisa o erro fica na ordem do ruído da malha (nas peças de teste, média de 0,005 a 0,02 mm e máximo de 0,13 mm). Onde havia ressalto, cordão de solda ou rebarba passando por baixo do alvo, o remendo alisa.
- Situação **conferir**: o contorno do furo não assentou todo na referência, ou sobrou um toco de rebarba. Olhe esses remendos no modelo antes de medir em cima deles. O relatório lista cada um com o motivo.
- O **ruído da referência**, no detalhe de cada alvo e no relatório, é o espalhamento dos pontos da peça em volta do ajuste. É a precisão que se pode esperar daquele remendo.

## Sólido para o SolidWorks

Na aba **Sólido**, o Cleanmold reconhece **peça de revolução** (eixo, bucha, flange, anel, tampa): acha o eixo, corta a malha por planos que passam por ele, tira o perfil em retas e arcos e arredonda as cotas como você escolher.

O que sai:

- **STEP** (`_solido.step`): um corpo só, abre como peça e não como montagem. Nenhum STEP leva árvore de projeto: abre como corpo importado.
- **Macro do SolidWorks** (`_solidworks.swb`): é ela que dá a árvore editável. No SolidWorks, *Ferramentas > Macro > Executar* e escolha o arquivo. A macro cria uma peça nova com:
  1. o esboço **Perfil (Cleanmold)** no Plano Frontal, com as retas e arcos, as relações (cilindros paralelos ao eixo, faces perpendiculares) e as cotas (diâmetros, posições das faces, cones, raios);
  2. a **Revolução (Cleanmold)** em torno do eixo.

  Dois cliques na revolução ou no esboço mostram as cotas para editar.
- **Perfil em DXF** (`_perfil.dxf`): o mesmo perfil, para quem preferir inserir num esboço e revolucionar à mão.

Nos três, o eixo de revolução é o eixo X, com a origem na primeira face da peça.

Limites:

- Só **peça de revolução**. Peça prismática ou de forma livre não tem árvore automática nesta versão.
- O que na peça **não é de revolução** (palhetas, nervuras, rasgos de chaveta, furos fora do eixo, dentes) fica de fora: modele por cima no SolidWorks. A tela informa quanto da malha o perfil explica.
- Malha de **um lado só** da peça, ou de **um setor** da volta, não fecha um corpo: sai a superfície de revolução, não um sólido.
- A macro foi escrita pela documentação da API do SolidWorks e **ainda não foi executada num SolidWorks de verdade**. Se alguma cota ou relação não entrar, ela avisa quais e a geometria fica certa; se a macro parar com erro, anote a linha e a mensagem.

## Linha de comando

```
python -m cleanmold malha.stl
python -m cleanmold malha.stl --saida pasta --solido --margem 1,5
```

Grava `malha_limpa.stl`, o relatório em HTML e a planilha CSV. Com `--solido`, também STEP, DXF e macro. `--todos` retira também os alvos de confiança baixa; `--manter-soltos` não apaga os pedaços soltos.

## Conferir a instalação

*Menu Iniciar > Cleanmold > Validar a instalação* limpa três peças de teste de forma conhecida (chapa, eixo escalonado e calota aberta), com os alvos reais fundidos nelas, e confere contra o gabarito: alvos achados, furos fechados, erro do remendo, cotas do sólido. Termina com "Tudo certo".

## Sem o instalador

O `Cleanmold_<versão>.zip` é o programa sem o Python. Extraia a pasta inteira para o disco do computador, coloque um Python 3.11 a 3.14 de 64 bits ao alcance (o WinPython extraído dentro da pasta serve) e rode `INSTALAR.bat`. Depois, `ABRIR_CLEANMOLD.bat` abre o programa e `CRIAR_ATALHO.bat` põe o ícone na Área de Trabalho.

## Se algo der errado

- **A janela não abre:** o Cleanmold usa o Edge ou o Chrome como janela. Se nenhum abrir, uma caixa mostra o endereço para colar no navegador.
- **Faltou memória:** malhas de vários milhões de triângulos pedem alguns gigabytes livres (cerca de 5 GB para 8 milhões de triângulos). Feche outros programas ou exporte a malha com menos triângulos.
- **Nenhum alvo encontrado:** confira se a malha está em milímetros. Um pé de 18,8 mm numa malha em polegadas ou em metros não é reconhecido.
- Em *Análise > Ver registro* fica o passo a passo da última análise.
