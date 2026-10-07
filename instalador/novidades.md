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
