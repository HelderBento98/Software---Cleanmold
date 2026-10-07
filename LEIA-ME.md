# Cleanmold

Retira os alvos de escaneamento de uma malha 3D e fecha os furos continuando a superfície da peça que está em volta. Também otimiza a malha (menos triângulos, mesma forma) e repara: pincel de seleção, furos, alisamento e reparo automático. Da mesma família do Enmold.

Tudo roda no computador: a malha, a análise e os arquivos não são enviados pela internet.

## Instalar

Execute o `Cleanmold_Setup_<versão>.exe`. Instala só para o seu usuário, sem senha de administrador e sem internet, e ocupa cerca de 1,2 GB. O instalador não tem assinatura digital: no aviso do Windows, clique em *Mais informações > Executar assim mesmo*.

Depois de instalado, o Cleanmold fica no Menu Iniciar e na Área de Trabalho. Para atualizar, rode o instalador novo por cima.

## Usar

1. **Exporte a malha** do Control X ou do Design X em STL (também PLY, OBJ ou OFF), em milímetros, com os alvos como saíram do escaneamento. Não precisa alinhar nem separar nada.
2. **Abrir malha.** A procura dos alvos começa sozinha. Em malha de milhões de triângulos, o Cleanmold pergunta antes se é para **otimizar ao abrir** (veja *Malha grande*, abaixo).
3. **Confira a lista.** Cada alvo aparece em verde no modelo e numa linha da lista, com a confiança. Clique numa linha para ver o alvo de perto.
   - Não é alvo: desmarque a linha. Fica em laranja e não é tocado.
   - Faltou um alvo: use a ferramenta com a mira, na barra de cima, informe o diâmetro do recorte e clique no **pé** do alvo.
4. **Retirar e fechar os furos.** Depois, use **Antes** e **Depois** para comparar. Os remendos aparecem em verde-claro.
5. **Repare o que faltar**, na aba **Malha e reparo**: pincel, furos, exame e reparo automático.
6. **Gerar arquivos:** malha limpa (STL), relatório (PDF) e, para peça de revolução, sólido (STEP) e macro do SolidWorks.

### No modelo 3D

Arraste para girar, role para aproximar (a aproximação vai para onde está o cursor), botão direito para mover. Os botões de vista (Isométrica, Cima, Frente, Lado) usam os eixos da própria malha. Enquanto a vista se mexe, o modelo é mostrado com menos triângulos; parou, volta o modelo completo.

Com o **pincel** aberto os botões mudam: o esquerdo pinta, o direito gira e o do meio desloca.

## Malha grande

Uma malha de escaneamento de vários milhões de triângulos pede gigabytes de memória. Quando o arquivo passa de 4 milhões de triângulos, o Cleanmold mostra, antes de abrir, quanto ele vai pedir e quanto o computador tem livre, e oferece duas saídas:

- **Otimizar ao abrir** (recomendado): a malha é lida e reduzida antes de qualquer outra coisa. A procura dos alvos e todas as ferramentas ficam várias vezes mais rápidas.
- **Abrir inteira**: todos os triângulos. Dá para otimizar depois.

Na malha de 8 milhões de triângulos usada no desenvolvimento (400 MB de STL): otimizando ao abrir com tolerância de 0,05 mm, ficaram 1,7 milhão de triângulos, com desvio máximo medido de 0,04 mm; abrir e achar os alvos levou cerca de um minuto, com pico de 1,6 GB de memória. Aberta inteira, o pico é de 2,6 GB.

### Otimizar: menos triângulos, mesma forma

Onde a peça é plana ou pouco curva, muitos triângulos pequenos viram poucos grandes. Onde há raio, canto ou ressalto, os triângulos ficam. O critério é uma **tolerância** em mm: uma aresta só é desfeita se a malha nova continuar a menos dessa distância da original.

| Nível | Tolerância | Para quê |
|---|---|---|
| Fiel | 0,02 mm | medir em cima da malha |
| Equilibrado | 0,05 mm | o uso normal |
| Leve | 0,10 mm | arquivo pequeno, visualização |

Depois de reduzir, o **desvio é medido**: distância de 200 mil pontos da malha original à malha nova, e da nova à original. O resultado (médio, 99 % e máximo) aparece no painel e vai para o relatório. A borda aberta da malha e o contorno dos furos não são mexidos.

O arquivo STL diminui na mesma proporção dos triângulos. Em PLY a mesma malha ocupa menos da metade do STL.

O que a otimização não faz: não tira ruído (uma superfície com ruído maior que a tolerância fica com os triângulos que tinha) e não fecha furos.

## Pincel, furos e reparo

As ferramentas ficam na aba **Malha e reparo**, à direita, e no menu **Malha**. Elas mexem na malha de trabalho: a malha como foi aberta, enquanto os alvos não foram retirados; a malha limpa, depois. **Desfazer** (Ctrl+Z) volta a última operação, até seis para trás.

### Pincel de seleção

Botão do pincel na barra de cima. Escolha o **diâmetro** (campo, régua, teclas `[` e `]`, ou Ctrl + roda do mouse) e arraste sobre a malha. O pincel é uma bola: pega o que está dentro dela e ligado ao ponto tocado, então o outro lado de uma parede fina fica de fora. **Shift** (ou o modo *Despintar*) tira a pintura.

Com a região pintada:

- **Retirar e preencher**: apaga o que está pintado, e o que ficar pendurado no corte, e fecha o furo seguindo a superfície em volta. É o jeito de tirar um alvo que a procura não achou: um toque no pé dele, com o pincel um pouco maior que o pé, e o corpo do alvo sai junto.
- **Preencher o vazio**: para fechar um furo ou um entalhe na borda da malha, pinte por cima da beirada dele.
- **Alisar**: *leve* tira o ruído; *médio* tira ondulações; *refazer liso* refaz a região como continuação lisa do que está em volta (serve para um caroço ou um resto de rebarba). O contorno da região não se mexe.
- **Apagar**: só apaga, deixando o furo aberto.

Use o menor pincel que cobre o que precisa sair. Um corte grande, que atravessa uma parede fina ou pega várias faces ao mesmo tempo, pode não ter uma superfície que o explique: nesse caso o Cleanmold avisa e deixa o corte aberto, em vez de inventar um remendo.

### Furos

**Procurar furos** lista os contornos abertos da malha e os mostra em vermelho no modelo. Dá para fechar um por um (botão *Fechar* da linha) ou **todos até um diâmetro**. O contorno maior de um escaneamento de um lado só é a borda da peça, não um furo: aparece marcado como *borda da peça* e só é fechado se você pedir.

O fechamento usa o mesmo método dos alvos: a vizinhança do furo é separada em superfícies (plano, cilindro, esfera, cone, superfície suave), o remendo segue cada uma, e a aresta viva entre elas é refeita, inclusive quando o furo desce por uma parede e continua pelo fundo.

Quando nenhuma dessas formas explica a vizinhança (a ponta de uma palheta que o escaneamento não pegou, um vazio entre as duas faces de uma parede fina, um canto de três faces), entra o **preenchimento geral**: o contorno é triangulado pela menor área, o remendo é refinado até os triângulos ficarem do tamanho dos vizinhos e depois assentado como a superfície de menor dobra que continua, com tangência, o que está em volta. O resultado é liso e fechado, mas é a forma mais simples possível, não a forma que a peça tinha: esses remendos saem marcados para conferir. Na malha usada no desenvolvimento, os 17 vazios do escaneamento (nas pontas e nos pés das palhetas, de 28 a 149 mm) foram fechados assim, em 13 segundos.

### Exame e reparo automático

**Examinar a malha** conta: pedaços soltos pequenos, arestas com três ou mais triângulos (lascas), triângulos virados em relação aos vizinhos, contornos abertos e triângulos muito finos. **Reparar** corrige o que estiver marcado.

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

`--otimizar` reduz a malha ao abrir (tolerância de 0,05 mm; `--otimizar 0,02` para outra). `--reparar` apaga lascas e pedaços soltos e desvira triângulos depois da limpeza; `--furos 5` fecha também os furos de até 5 mm.

## Conferir a instalação

*Menu Iniciar > Cleanmold > Validar a instalação* limpa três peças de teste de forma conhecida (chapa, eixo escalonado e calota aberta), com os alvos reais fundidos nelas, e confere contra o gabarito: alvos achados, furos fechados, erro do remendo, cotas do sólido. Depois repete com a malha otimizada (desvio medido dentro da tolerância) e confere o pincel, os furos, o alisamento, o reparo automático e o desfazer. Termina com "Tudo certo".

## Sem o instalador

O `Cleanmold_<versão>.zip` é o programa sem o Python. Extraia a pasta inteira para o disco do computador, coloque um Python 3.11 a 3.14 de 64 bits ao alcance (o WinPython extraído dentro da pasta serve) e rode `INSTALAR.bat`. Depois, `ABRIR_CLEANMOLD.bat` abre o programa e `CRIAR_ATALHO.bat` põe o ícone na Área de Trabalho.

## Se algo der errado

- **A janela não abre:** o Cleanmold usa o Edge ou o Chrome como janela. Se nenhum abrir, uma caixa mostra o endereço para colar no navegador.
- **Faltou memória ou o computador ficou lento:** abra de novo escolhendo **Otimizar ao abrir**. Aberta inteira, uma malha pede cerca de 340 MB de memória por milhão de triângulos; otimizando ao abrir, cerca de 130 MB por milhão.
- **O giro da vista está pesado:** otimize a malha. A tela mostra até 1,2 milhão de triângulos parada e 150 mil em movimento; numa placa de vídeo integrada, a malha otimizada gira bem mais solta.
- **Nenhum alvo encontrado:** confira se a malha está em milímetros. Um pé de 18,8 mm numa malha em polegadas ou em metros não é reconhecido.
- Em *Análise > Ver registro* fica o passo a passo da última análise.
