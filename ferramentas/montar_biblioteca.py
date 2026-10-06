"""Monta cleanmold/alvos/biblioteca.json a partir das malhas de alvo isoladas.

    python ferramentas/montar_biblioteca.py PASTA_DOS_STL

Cada tipo de alvo vira um pé (raio e altura da base que encosta na peça) e um perfil: o raio externo do
alvo em cada milímetro de altura acima do plano de apoio. Também grava uma nuvem de pontos reduzida de
cada tipo (referencial do alvo: apoio em z=0, eixo +Z), usada nas peças de teste."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanmold import malha, ajuste, alvos

U = sys.argv[1]
SAIDA = alvos.PASTA
os.makedirs(SAIDA, exist_ok=True)


def achar(parte):
    for n in os.listdir(U):
        if parte.lower() in n.lower():
            return os.path.join(U, n)
    raise SystemExit("faltou o arquivo " + parte)


def pca(P):
    c = P.mean(0)
    w, v = np.linalg.eigh(np.cov((P - c).T))
    return c, v[:, 2]


def canonico(P, N, origem, eixo):
    """Leva pontos e normais ao referencial do alvo: origem no centro do apoio, eixo em +Z."""
    R = ajuste.rotacao_entre(eixo, [0, 0, 1.0])
    return (P - origem) @ R.T, N @ R.T


def perfil_de(P, altura):
    h = np.arange(alvos.PASSO_PERFIL / 2, altura, alvos.PASSO_PERFIL)
    rho = np.hypot(P[:, 0], P[:, 1])
    rm = []
    for x in h:
        s = np.abs(P[:, 2] - x) <= alvos.PASSO_PERFIL / 2
        rm.append(float(np.percentile(rho[s], 92)) if s.sum() >= 4 else float("nan"))
    return h, np.array(rm)


def reduzir(P, N, cel=0.6):
    q = np.floor(P / cel).astype(np.int64)
    _, i = np.unique(q, axis=0, return_index=True)
    return P[i].astype(np.float32), N[i].astype(np.float32)


# ---------------------------------------------------------------- peão
m = malha.carregar(achar("PEAO"))
P, N, _ = m.amostrar(0.25, suavizar=1)
c, a = pca(P)
z = (P - c) @ a
rho = np.linalg.norm((P - c) - np.outer(z, a), axis=1)
if rho[z < 0].mean() < rho[z > 0].mean():
    a = -a
lado = (rho > 8.5) & (np.abs(N @ a) < 0.3)
pc, pa, pr, rms = ajuste.cilindro(P[lado], a, c, 9.4)
if pa @ a < 0:
    pa = -pa
z = (P - pc) @ pa
zb = np.percentile(z, 0.5)
Pp, Np = canonico(P, N, pc + zb * pa, pa)
cab = Pp[:, 2] > Pp[:, 2].max() - 8.5
ec, er, _ = ajuste.esfera(Pp[cab])
print("peão: base r=%.3f (rms %.3f), cabeça r=%.3f em h=%.2f, altura %.2f" % (pr, rms, er, ec[2], Pp[:, 2].max()))
# altura da parede reta da base: até onde o raio externo fica perto do raio da base
hp, rp = perfil_de(Pp, np.ceil(Pp[:, 2].max()))
alt_base_peao = float(hp[np.flatnonzero(rp > pr - 0.6)[-1]] + 0.5)

# ---------------------------------------------------------------- dado impresso (esfera + pescoço + dodecaedro)
m = malha.carregar(achar("impr"))
P3, N3, _ = m.amostrar(0.25, suavizar=1)
c, a = pca(P3)
z = (P3 - c) @ a
rho = np.linalg.norm((P3 - c) - np.outer(z, a), axis=1)
if rho[z < 0].mean() > rho[z > 0].mean():      # esfera (menor) do lado negativo
    a = -a
    z = -z
# pescoço: fatia de menor raio; a esfera fica abaixo dele, o dodecaedro acima
fat = np.arange(z.min() + 2, z.max() - 2, 0.5)
rmed = np.array([np.percentile(rho[np.abs(z - f) < 0.5], 90) for f in fat])
zp = fat[np.argmin(rmed)]
bc, br, brms = ajuste.esfera(P3[(z < zp - 2.5)])
dc, dr, _ = ajuste.esfera(P3[z > zp + 2.5])
eixo3 = (dc - bc) / np.linalg.norm(dc - bc)
print("dado impresso: esfera r=%.3f (rms %.3f), pescoço r=%.2f, dodecaedro raio médio %.2f, distância esfera-dodecaedro %.2f"
      % (br, brms, rmed.min(), dr, np.linalg.norm(dc - bc)))
# montado sobre o peão: a esfera impressa abraça a cabeça do peão (mesmos centros)
P3c, N3c = canonico(P3, N3, bc, eixo3)
P3c = P3c + np.array([0, 0, ec[2]])
fora_da_esfera = np.linalg.norm(Pp - np.array([0, 0, ec[2]]), axis=1) > br - 0.3
Pc = np.vstack([Pp[fora_da_esfera], P3c])
Nc = np.vstack([Np[fora_da_esfera], N3c])

# ---------------------------------------------------------------- dado com base cilíndrica
m = malha.carregar(achar("DADO_MONTADO"))
Pd, Nd, _ = m.amostrar(0.25, suavizar=1)
c0, r0, _ = ajuste.esfera(Pd)
d = np.linalg.norm(Pd - c0, axis=1)
a = (Pd[d > np.percentile(d, 97)] - c0).mean(0)
a /= np.linalg.norm(a)                         # do centro do dodecaedro para a base
z = (Pd - c0) @ a
rho = np.linalg.norm((Pd - c0) - np.outer(z, a), axis=1)
lado = (z > 11.0) & (np.abs(Nd @ a) < 0.3) & (rho > 6.5)
bc2, ba2, br2, rms2 = ajuste.cilindro(Pd[lado], a, c0, 7.4)
if ba2 @ a < 0:
    ba2 = -ba2
z = (Pd - bc2) @ ba2
zf = np.percentile(z, 99.5)                    # fundo da base
Pdc, Ndc = canonico(Pd, Nd, bc2 + zf * ba2, -ba2)
hd, rd = perfil_de(Pdc, np.ceil(Pdc[:, 2].max()))
alt_base_dado = float(hd[np.flatnonzero(np.abs(rd[:10] - br2) < 0.6)[-1]] + 0.5)
print("dado com base: base r=%.3f (rms %.3f) altura %.1f, altura total %.2f" % (br2, rms2, alt_base_dado, Pdc[:, 2].max()))

# esferas de cada tipo (altura do centro sobre o apoio, raio) e altura do centro do dodecaedro, quando há
h_dodec = float(ec[2] + np.linalg.norm(dc - bc))
c0c = (c0 - (bc2 + zf * ba2)) @ (-ba2)
tipos = []
for ident, nome, Pt, Nt, raio, alt_base, esferas, hd in (
        ("peao", "Peão magnético", Pp, Np, pr, alt_base_peao, [[float(ec[2]), float(er)]], None),
        ("peao_dado", "Peão com dado impresso", Pc, Nc, pr, alt_base_peao, [[float(ec[2]), float(br)]], h_dodec),
        ("dado_base", "Dado com base cilíndrica", Pdc, Ndc, br2, alt_base_dado, [], float(c0c))):
    altura = float(np.ceil(Pt[:, 2].max()))
    h, rm = perfil_de(Pt, altura)
    rho = np.hypot(Pt[:, 0], Pt[:, 1])
    Pr, Nr = reduzir(Pt, Nt)
    np.savez_compressed(os.path.join(SAIDA, ident + ".npz"), P=Pr, N=Nr)
    tipos.append(dict(id=ident, nome=nome, raio_base=round(float(raio), 3), altura_base=round(alt_base, 2),
                      altura=altura, raio_max=round(float(np.percentile(rho, 99.5)), 2),
                      zona_pe=round(alt_base + 7.0, 1),
                      esferas=[[round(x, 2) for x in e] for e in esferas], h_dodecaedro=None if hd is None else round(hd, 1),
                      perfil_h=[round(float(x), 2) for x in h], perfil_rmax=[None if not np.isfinite(x) else round(float(x), 2) for x in rm]))
    print(f"{ident}: raio {raio:.2f} base {alt_base:.1f} altura {altura:.0f} raio máx {tipos[-1]['raio_max']}  pontos {len(Pr)}")
    print("   perfil:", " ".join("%.1f" % x for x in rm))
with open(os.path.join(SAIDA, "biblioteca.json"), "w", encoding="utf-8") as fh:
    json.dump(dict(versao=1, passo=alvos.PASSO_PERFIL, tipos=tipos), fh, ensure_ascii=False, indent=1)
print("gravado", os.path.join(SAIDA, "biblioteca.json"))
