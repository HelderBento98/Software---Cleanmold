"""Exploração: mede os três alvos enviados (eixo, base, esferas) para montar a biblioteca."""
import sys, numpy as np
sys.path.insert(0, '.')
from cleanmold import malha, ajuste
np.set_printoptions(precision=3, suppress=True, linewidth=200)
U = sys.argv[1]
peao = malha.carregar(U + '/9a33e564-PEAO_montado.stl')
dado = malha.carregar(U + '/268c475a-DADO_MONTADO.stl')
d3 = malha.carregar(U + '/4e063580-Dado_impr_3D_montado.stl')

def pca(P):
    c = P.mean(0); w, v = np.linalg.eigh(np.cov((P - c).T)); return c, v[:, 2]

# ---- peão
P, N, _ = peao.amostrar(0.25, suavizar=1)
c, a = pca(P)
z = (P - c) @ a
rho = np.linalg.norm((P - c) - np.outer(z, a), axis=1)
if rho[z < 0].mean() < rho[z > 0].mean(): a = -a; z = -z      # base (larga) do lado negativo
lado = (rho > 8.5) & (np.abs(N @ a) < 0.3)
pc, pa, pr, rms = ajuste.cilindro(P[lado], a, c, 9.4)
if pa @ a < 0: pa = -pa
z = (P - pc) @ pa
rho = np.linalg.norm((P - pc) - np.outer(z, pa), axis=1)
print("PEAO base: raio %.3f rms %.3f  z lado %.2f..%.2f  z min %.2f  z max %.2f" % (pr, rms, np.percentile(z[lado], 1), np.percentile(z[lado], 99), np.percentile(z, 0.2), np.percentile(z, 99.8)))
zb = np.percentile(z, 0.5)
cab = z > np.percentile(z, 99.8) - 8.5
ec, er, erms = ajuste.esfera(P[cab])
print("  cabeça: raio %.3f rms %.3f altura do centro sobre o fundo %.2f desvio lateral %.3f" % (er, erms, (ec - pc) @ pa - zb, np.linalg.norm((ec - pc) - ((ec - pc) @ pa) * pa)))
pesc = (z - zb > 9) & (z - zb < 13.5)
print("  pescoço: raio mediano %.2f min %.2f" % (np.median(rho[pesc]), np.percentile(rho[pesc], 5)))
for h in np.arange(0, 26, 1.0):
    s = (z - zb >= h) & (z - zb < h + 1)
    if s.sum(): print("   h %4.1f: rho med %.2f p95 %.2f" % (h, np.median(rho[s]), np.percentile(rho[s], 95)))

# ---- dado montado
P, N, _ = dado.amostrar(0.25, suavizar=1)
c0, r0, _ = ajuste.esfera(P)
d = np.linalg.norm(P - c0, axis=1)
print("\nDADO: esfera media r %.2f; dist min %.2f max %.2f" % (r0, d.min(), d.max()))
# faces planas: agrupa normais
longe = d > np.percentile(d, 97)
dirm = (P[longe] - c0).mean(0); print("  direção de assimetria (norma)", np.linalg.norm(dirm).round(2))
a = dirm / np.linalg.norm(dirm)
z = (P - c0) @ a; rho = np.linalg.norm((P - c0) - np.outer(z, a), axis=1)
for h in np.arange(-17, 18, 1.0):
    s = (z >= h) & (z < h + 1)
    if s.sum(): print("   z %5.1f: rho med %.2f p5 %.2f p95 %.2f n %d" % (h, np.median(rho[s]), np.percentile(rho[s], 5), np.percentile(rho[s], 95), s.sum()))

# ---- dado 3D
P, N, _ = d3.amostrar(0.25, suavizar=1)
c, a = pca(P)
z = (P - c) @ a
print("\nDADO 3D z", z.min().round(2), z.max().round(2))
