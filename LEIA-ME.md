# Cleanmold

Retira os alvos de escaneamento de uma malha 3D e deixa um furo no lugar do pé de cada um. Só isso: o resto da malha sai do Cleanmold idêntico ao que entrou. Da mesma família do Enmold.

Tudo roda no computador: a malha e os arquivos não são enviados pela internet.

## Instalar

Execute o `Cleanmold_Setup_<versão>.exe`. Instala só para o seu usuário, sem senha de administrador e sem internet. O instalador não tem assinatura digital: no aviso do Windows, clique em *Mais informações > Executar assim mesmo*.

Depois de instalado, o Cleanmold fica no Menu Iniciar e na Área de Trabalho. Para atualizar, rode o instalador novo por cima.

## Usar

1. **Exporte a malha** do Control X ou do Design X em STL (também PLY, OBJ ou OFF), em milímetros, com os alvos como saíram do escaneamento. Não precisa alinhar, separar nem reduzir nada.
2. **Abrir malha.** A procura dos alvos começa sozinha.
3. **Confira a lista.** Cada alvo aparece em verde no modelo e numa linha da lista, com a confiança. Clique numa linha para ver o alvo de perto.
   - Não é alvo: desmarque a linha. Fica em laranja e não é tocado.
   - Faltou um alvo: use a ferramenta com a mira, na barra de cima, informe o diâmetro do pé e clique em qualquer ponto do **pé** do alvo.
4. **Retirar os alvos.** Depois, use **Antes** e **Depois** para comparar. Em Depois, o contorno de cada furo aparece em verde e, por dentro do furo, o avesso da malha aparece escuro.
5. **Salvar a malha limpa**, em STL ou em PLY. O arquivo é gravado ao lado da malha aberta, com `_limpa` no nome. A malha aberta não é alterada.

**Desfazer a retirada** (ou Ctrl+Z) volta à malha com os alvos na hora. Dá para retirar de novo com outra seleção ou outra margem quantas vezes quiser.

### No modelo 3D

Arraste para girar, role para aproximar (a aproximação vai para onde está o cursor), botão direito para mover. Enquanto a vista se mexe, o modelo é mostrado com menos triângulos; parou, volta o modelo completo.

A vista de abertura olha para o lado escaneado: num escaneamento de um lado só, o avesso da malha (mais escuro) fica para trás. Os botões Cima, Frente e Lado usam os eixos da própria malha.

## O que o Cleanmold faz, e o que não faz

- Ele **só retira**. No lugar de cada pé fica um **furo aberto**, um pouco maior que o pé. Fechar os furos é trabalho do Design X.
- Nenhum triângulo é criado, movido ou reduzido. A malha limpa são os triângulos da malha aberta, menos os dos alvos. A validação confere isso bit a bit.
- Outra parte da peça que passe perto de um alvo (a palheta vizinha, uma parede em frente) não tem ligação com o pé dele e não é tocada.
- O lado oposto de uma peça fina, ou de um eixo, nunca é tocado.

## Malha grande

A malha é aberta inteira, sem redução. O que foi medido num computador de 2 núcleos e 8 GB:

| Malha | Arquivo | Abrir e achar os alvos | Retirar | Pico de memória |
|---|---|---|---|---|
| 8 milhões de triângulos, 44 alvos | 382 MB | 37 s | 20 s | 1,3 GB |
| 32 milhões de triângulos, 174 alvos | 1,6 GB | 2 min 5 s | 80 s | 2,4 GB |

A conta, para outros tamanhos: cerca de **50 MB de memória por milhão de triângulos, mais 1 GB**. O tempo de retirar depende do número de alvos (perto de meio segundo por alvo), não do tamanho da malha.

Se a conta indicar que a malha não cabe folgada na memória livre do computador, o Cleanmold avisa antes de abrir.

Para abrir, use o botão **Abrir malha**. Arrastar o arquivo para a janela também funciona, mas faz uma cópia dele antes, o que demora num arquivo grande.

O **PLY** grava a mesma malha em menos da metade do tamanho do STL (38 % na malha de 8 milhões: 131 MB em vez de 345 MB), porque cada vértice é gravado uma vez só. Nada da malha muda.

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

O nome do tipo é só o rótulo da lista: o corte é decidido pelo pé.

**Pedaços soltos.** Os pedaços de um alvo que o escaneamento separou da peça (a esfera, o dodecaedro) saem com ele; os de um alvo desmarcado ficam. As outras lascas soltas do escaneamento saem também, a menos que você desmarque *Apagar também as lascas soltas*.

A **confiança** vai de 0 a 100 %. Alvos com menos de 50 % entram na lista desmarcados: confira no modelo e marque se forem alvos.

## Como o corte é feito

1. A superfície da peça em volta do pé é ajustada ao modelo mais simples que explica a vizinhança: **plano**, **cilindro**, **esfera**, **cone** ou **superfície curva suave**. Ela serve só de referência para o corte; nada é desenhado sobre ela.
2. Sai o que está acima dessa superfície e ligado ao pé: o pé, a rebarba ou o caroço do escaneamento grudados nele, e o corpo do alvo.
3. O contorno do furo é aparado: triângulos que ficariam pendurados por um lado só saem junto.

Dois ajustes, no painel da esquerda:

- **Margem** (padrão 1,2 mm): quanto o furo passa do pé, para o contorno cair em superfície limpa. Um pé de Ø 18,8 mm deixa um furo de uns 21,5 mm.
- **Alcance** (padrão 8 mm): até onde, em volta do pé, o que estiver grudado nele é recortado quando a rebarba não termina sozinha (por exemplo, quando ela vai até uma parede).

O contorno do furo segue os lados dos triângulos da malha, então é serrilhado na escala deles (meio milímetro, numa malha de escaneamento comum). Cortar triângulos ao meio para alisar o contorno criaria triângulos novos, e o Cleanmold não cria nenhum.

## Situação de cada alvo depois da retirada

- **Retirado**: saiu inteiro. O detalhe da linha mostra o diâmetro do furo e quantos triângulos saíram. Se o furo dá numa borda que já estava aberta na malha (alvo na beirada do escaneamento), o detalhe avisa.
- **Conferir**: o corpo do alvo estava grudado em outra parte da peça por uma rebarba do escaneamento, e pode ter sobrado um toco dela. Olhe no modelo.
- **Não saiu**: não havia superfície da peça em volta do pé para servir de referência. A malha ali ficou como estava.
- **Ficou**: estava desmarcado.

## Linha de comando

```
python -m cleanmold malha.stl
python -m cleanmold malha.stl --saida pasta --margem 1,5 --ply
```

Grava `malha_limpa.stl` ao lado da malha (com `--ply`, também o PLY). `--todos` retira também os alvos de confiança baixa; `--manter-soltos` não apaga as lascas soltas; `--alcance` muda o alcance das rebarbas.

## Conferir a instalação

*Menu Iniciar > Cleanmold > Validar a instalação* retira os alvos de três peças de teste de forma conhecida (chapa, eixo escalonado e calota aberta), com os alvos reais fundidos nelas, e confere contra o gabarito: alvos achados e retirados, nada de alvo sobrando acima da peça, o furo de cada um do tamanho do pé mais a margem, nada mais da peça retirado, e o arquivo gravado com os mesmos triângulos da malha original. Depois confere a leitura do arquivo, o alvo desmarcado, o alvo indicado à mão, o desfazer, a vista 3D e a linha de comando. Termina com "Tudo certo".

## Sem o instalador

O `Cleanmold_<versão>.zip` é o programa sem o Python. Extraia a pasta inteira para o disco do computador, coloque um Python 3.11 a 3.14 de 64 bits ao alcance (o WinPython extraído dentro da pasta serve) e rode `INSTALAR.bat`. Depois, `ABRIR_CLEANMOLD.bat` abre o programa e `CRIAR_ATALHO.bat` põe o ícone na Área de Trabalho.

## Se algo der errado

- **A janela não abre:** o Cleanmold usa o Edge ou o Chrome como janela. Se nenhum abrir, uma caixa mostra o endereço para colar no navegador.
- **Faltou memória ou o computador ficou lento:** feche outros programas e abra de novo. Veja a conta em *Malha grande*.
- **Nenhum alvo encontrado:** confira se a malha está em milímetros. Um pé de 18,8 mm numa malha em polegadas ou em metros não é reconhecido.
- **Um alvo de outro modelo** (outro diâmetro de pé) não está na biblioteca: indique à mão, com o diâmetro do pé dele.
- Em *Ajuda > Ver registro* fica o passo a passo da última análise.

## Onde foram parar as outras ferramentas

Até a versão 1.1.0 o Cleanmold também fechava os furos, reduzia e reparava a malha e gerava o sólido para o SolidWorks. A partir da 2.0.0 ele só retira os alvos. A 1.1.0 continua publicada em Releases para quem precisar daquelas ferramentas.
