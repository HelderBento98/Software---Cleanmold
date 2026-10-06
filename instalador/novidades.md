## Cleanmold 1.0.0

Primeira versão.

- Procura os alvos de escaneamento na malha pelo padrão deles (pé cilíndrico em pé sobre a peça, pescoço, esfera, dodecaedro), mesmo amassados ou partidos em pedaços soltos.
- Retira cada alvo e fecha o furo continuando a superfície em volta: plano, cilindro, esfera, cone ou superfície curva suave. Refaz a aresta viva quando o alvo estava na beirada e a borda quando estava na borda da malha.
- Alvo que faltou pode ser indicado à mão; o que não for alvo pode ser desmarcado.
- Grava a malha limpa (STL ou PLY) e o relatório da limpeza (PDF, HTML, CSV).
- Para peça de revolução: reconhece o eixo e o perfil, grava o sólido em STEP (corpo único), o perfil em DXF e uma macro que reconstrói a peça no SolidWorks com esboço cotado e revolução.
