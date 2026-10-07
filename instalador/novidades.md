## Cleanmold 2.0.0

Só a retirada dos alvos, feita para malha grande.

- **O programa foi enxugado.** Ficou o que retira os alvos: abrir a malha, achar os alvos, marcar ou desmarcar, retirar e salvar. Saíram o fechamento dos furos, o pincel, a redução de triângulos, o alisamento, o reparo e o sólido para o SolidWorks. Quem precisar deles tem a versão 1.1.0, que continua publicada.
- **No lugar de cada alvo fica um furo aberto**, um pouco maior que o pé. Nenhum triângulo é criado, movido ou reduzido: a malha limpa são os triângulos da malha aberta, menos os dos alvos.
- **Correção: a palheta vizinha não é mais cortada.** Até a 1.1.0, quando outra parte da peça passava por perto do alvo, um pedaço dela saía junto com ele. Na malha de 8 milhões de triângulos usada no desenvolvimento isso acontecia em 9 dos 44 alvos. Agora só sai o que está ligado ao pé.
- **Malha grande.** A malha de 8 milhões de triângulos abre e tem os alvos achados em 37 s, com pico de 1,3 GB de memória (eram 2,6 GB). Uma malha de 32 milhões de triângulos (1,6 GB de arquivo) passa inteira com 2,4 GB. A leitura do STL usa um terço da memória de antes.
- **Desfazer a retirada é imediato**, e dá para retirar de novo com outra seleção ou outra margem.
- **Alvo desmarcado fica inteiro**, com os pedaços soltos dele (antes, os pedaços soltos saíam mesmo assim).
- **Indicar à mão**: o clique pode ser em qualquer ponto do pé; o corte é centrado no pé, não no clique.
- **Vista 3D**: abre olhando para o lado escaneado; o avesso da malha aparece mais escuro, e por isso o furo aparece como furo; a luz acompanha a câmera com a peça em qualquer posição (antes, uma peça longe da origem ficava escura de alguns lados); em Depois, o contorno de cada furo aparece em verde.
- **PLY**: a mesma malha em menos da metade do tamanho do STL.
- O instalador ficou bem menor: o programa agora só precisa do numpy, do scipy e do trimesh.

## Cleanmold 1.1.0

Malha grande, pincel e reparo.

- **Malha grande não trava mais o computador.** A leitura do STL usa um quinto da memória de antes e é quatro vezes mais rápida. Ao abrir uma malha de milhões de triângulos, o Cleanmold mostra quanto ela pede de memória e oferece otimizar na abertura.
- **Otimizar a malha**: menos triângulos com a mesma forma. Onde a peça é lisa, muitos triângulos pequenos viram poucos grandes; onde há raio, canto ou ressalto, eles ficam. A tolerância é escolhida em mm (0,02, 0,05 ou 0,10) e o desvio que resultou é medido e mostrado. O arquivo STL sai menor na mesma proporção.
- **Pincel de seleção**: escolha o diâmetro e arraste sobre a malha. O que está pintado pode ser retirado com o furo fechado pela superfície em volta, só apagado, alisado, ou usado para preencher um vazio.
- **Furos**: lista dos contornos abertos, com fechamento de um por um ou de todos até um diâmetro, seguindo a geometria em volta (plano, cilindro, esfera, cone, superfície suave) e refazendo arestas vivas, inclusive quando o furo passa por mais de uma face. Onde nenhuma forma simples explica a vizinhança (ponta de palheta, parede fina), o furo é fechado com a superfície mais lisa que continua as bordas.
- **Exame e reparo automático**: pedaços soltos, arestas com três ou mais triângulos, triângulos virados e furos pequenos.
- **Desfazer** (Ctrl+Z) para todas as operações, inclusive a retirada dos alvos.
- **Vista 3D mais solta**: enquanto a vista gira, o modelo é mostrado com menos triângulos; parou, volta o modelo completo.
- Linha de comando: `--otimizar`, `--reparar` e `--furos`.

## Cleanmold 1.0.0

Primeira versão.

- Procura os alvos de escaneamento na malha pelo padrão deles (pé cilíndrico em pé sobre a peça, pescoço, esfera, dodecaedro), mesmo amassados ou partidos em pedaços soltos.
- Retira cada alvo e fecha o furo continuando a superfície em volta: plano, cilindro, esfera, cone ou superfície curva suave. Refaz a aresta viva quando o alvo estava na beirada e a borda quando estava na borda da malha.
- Alvo que faltou pode ser indicado à mão; o que não for alvo pode ser desmarcado.
- Grava a malha limpa (STL ou PLY) e o relatório da limpeza (PDF, HTML, CSV).
- Para peça de revolução: reconhece o eixo e o perfil, grava o sólido em STEP (corpo único), o perfil em DXF e uma macro que reconstrói a peça no SolidWorks com esboço cotado e revolução.
