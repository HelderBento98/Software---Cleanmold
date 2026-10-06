"""Gera as malhas de teste (testes/dados/*.npz): peças de forma conhecida com os alvos reais fundidos nelas,
como sairiam de um escaneamento (uma superfície só, com ruído, alvos amassados e pedaços soltos).

    python ferramentas/gerar_cenas.py            (precisa de scikit-image; só para quem for refazer os dados)

Os alvos vêm das nuvens de pontos de cleanmold/alvos/*.npz (referencial do alvo: apoio em z = 0, eixo +Z)."""
import json, os, sys
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import measure

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "testes"))
from cleanmold import ajuste, alvos
import pecas

H_ALVO = 0.3


def solido_do_alvo(ident):
    """Distância com sinal do alvo numa grade (negativa dentro). Devolve (grade, origem, passo)."""
    d = np.load(os.path.join(alvos.PASTA, ident + ".npz"))
    P = d["P"].astype(float)
    lo, hi = P.min(0) - 4.0, P.max(0) + 4.0
    n = np.ceil((hi - lo) / H_ALVO).astype(int) + 1
    gx, gy, gz = [lo[k] + H_ALVO * np.arange(n[k]) for k in range(3)]
    G = np.stack(np.meshgrid(gx, gy, gz, indexing="ij"), axis=-1).reshape(-1, 3)
    du, _ = cKDTree(P).query(G)
    du = du.reshape(n)
    casca = du < 0.9                                     # casca grossa: fecha as falhas pequenas do escaneamento
    rot, _ = ndimage.label(~casca)
    fora = rot == rot[0, 0, 0]
    dentro = ~fora
    # miolo: o que está dentro e longe da casca, mais a casca até a superfície verdadeira
    sdf = np.where(dentro & ~casca, -du, du)
    # a casca é ambígua: dentro da casca, o sinal vem de qual lado está mais perto do miolo
    d_miolo = ndimage.distance_transform_edt(~(dentro & ~casca)) * H_ALVO
    d_fora = ndimage.distance_transform_edt(~fora) * H_ALVO
    sdf = np.where(casca, np.where(d_miolo < d_fora, -du, du), sdf)
    tipo = next(t for t in alvos.biblioteca() if t.id == ident)
    # enchimento: o alvo escaneado é uma casca com falhas (fundo da base, rasgo da esfera impressa, cabeça do
    # peão escondida dentro da esfera). Enche-se o miolo com o sólido de revolução do perfil, um pouco para dentro.
    X = G.reshape(*n, 3)
    rho = np.hypot(X[..., 0], X[..., 1])
    h_max = max([tipo.altura_base] + [h + r * 0.9 for h, r in tipo.esferas])
    ok = np.isfinite(tipo.rmax) & (tipo.h <= h_max)
    r_de_z = np.interp(X[..., 2], tipo.h[ok], tipo.rmax[ok] - 0.45, left=tipo.rmax[ok][0] - 0.45, right=0.0)
    miolo = np.maximum(rho - r_de_z, np.maximum(0.3 - X[..., 2], X[..., 2] - h_max))
    sdf = np.minimum(sdf, miolo)
    # a base encosta na peça: fundo plano em z = 0
    base = np.maximum(rho - (tipo.raio - 0.15), np.maximum(-X[..., 2], X[..., 2] - max(1.5, tipo.altura_base - 1.2)))
    sdf = np.minimum(sdf, base)
    sdf = ndimage.gaussian_filter(sdf, 0.6)
    return sdf.astype(np.float32), lo, H_ALVO


_CACHE = {}


def alvo_em(ident, Q):
    """Distância com sinal do alvo `ident` nos pontos Q (referencial do alvo)."""
    if ident not in _CACHE:
        _CACHE[ident] = solido_do_alvo(ident)
    sdf, lo, h = _CACHE[ident]
    ij = ((Q - lo) / h).T
    v = ndimage.map_coordinates(sdf, ij, order=1, mode="nearest")
    fora = np.any((ij < 0) | (ij > (np.array(sdf.shape) - 1)[:, None]), axis=0)
    v[fora] = np.maximum(v[fora], 3.0)
    return v


def uniao_suave(a, b, k):
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def montar(forma, caixa, passo, alvos_, semente=0, ruido=0.02, **kw):
    """Funde os alvos na peça e extrai a superfície. alvos_: lista de dict(tipo, ponto, normal, [giro, escala,
    fusao (mm de 'derretimento' do pé), caroco (bolhas grudadas), inclinar])."""
    rng = np.random.default_rng(semente)
    lo, hi = np.array(caixa[0], float), np.array(caixa[1], float)
    n = np.ceil((hi - lo) / passo).astype(int) + 1
    ax = [lo[k] + passo * np.arange(n[k]) for k in range(3)]
    sdf = np.empty(n, np.float32)
    f = pecas.FORMAS[forma]
    for i in range(n[0]):                               # por fatias, para não estourar a memória
        G = np.stack(np.meshgrid(ax[1], ax[2], indexing="ij"), axis=-1).reshape(-1, 2)
        sdf[i] = f(np.c_[np.full(len(G), ax[0][i]), G], **kw).reshape(n[1], n[2])
    verdade = []
    for a in alvos_:
        tipo = next(t for t in alvos.biblioteca() if t.id == a["tipo"])
        p, nrm = np.asarray(a["ponto"], float), np.asarray(a["normal"], float)
        nrm = nrm / np.linalg.norm(nrm)
        R = ajuste.rotacao_entre([0, 0, 1.0], nrm) @ ajuste.rotacao_eixo([0, 0, 1.0], a.get("giro", 0.0))
        alc = tipo.raio_max + 14.0
        cen = p + nrm * tipo.altura / 2
        raio = np.hypot(tipo.altura / 2 + 8.0, alc)
        i0 = np.maximum(np.floor((cen - raio - lo) / passo).astype(int), 0)
        i1 = np.minimum(np.ceil((cen + raio - lo) / passo).astype(int) + 1, n)
        sub = [ax[k][i0[k]:i1[k]] for k in range(3)]
        G = np.stack(np.meshgrid(*sub, indexing="ij"), axis=-1).reshape(-1, 3)
        Q = (G - p) @ R                                  # para o referencial do alvo
        esc = a.get("escala", (1.0, 1.0, 1.0))
        Q = Q / np.asarray(esc, float)
        if a.get("inclinar"):                            # o corpo acima do pé tomba um pouco (alvo torto)
            k = a["inclinar"]
            z = np.maximum(Q[:, 2] - tipo.altura_base, 0)
            Q = Q - np.c_[k * z, 0 * z, 0 * z]
        d = alvo_em(a["tipo"], Q)
        for c in a.get("caroco", []):                    # bolhas de ruído grudadas no alvo
            d = uniao_suave(d, np.linalg.norm(Q - np.asarray(c[:3], float), axis=1) - c[3], 1.5)
        bloco = sdf[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]]
        novo = uniao_suave(bloco.reshape(-1), d.astype(np.float32), a.get("fusao", 0.6))
        sdf[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]] = novo.reshape(bloco.shape)
        verdade.append(dict(tipo=a["tipo"], ponto=[float(x) for x in p], normal=[float(x) for x in nrm],
                            raio=float(tipo.raio), dificil=bool(a.get("fusao", 0.6) > 2.0)))
    V, F, _, _ = measure.marching_cubes(sdf, level=0.0, spacing=(passo,) * 3)
    V = V + lo
    T = V[F]
    if np.einsum("ij,ij->i", T[:, 0], np.cross(T[:, 1], T[:, 2])).sum() < 0:
        F = F[:, ::-1].copy()                             # normais para fora
    # ruído do escaneamento ao longo da normal
    T = V[F]
    fn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    vn = np.zeros_like(V)
    for k in range(3):
        np.add.at(vn, F[:, k], fn)
    vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]
    V = V + vn * rng.normal(0, ruido, len(V))[:, None]
    return V, F, verdade


def gravar(nome, V, F, verdade, forma, extra=None, **kw):
    cam = os.path.join(RAIZ, "testes", "dados", nome + ".npz")
    np.savez_compressed(cam, V=V.astype(np.float32), F=F.astype(np.int32),
                        info=json.dumps(dict(forma=forma, params=kw, alvos=verdade, **(extra or {}))))
    print(f"{nome}: {len(F)} triângulos, {len(verdade)} alvos, {os.path.getsize(cam) / 1e6:.1f} MB")


if __name__ == "__main__":
    quais = sys.argv[1:] or ["chapa", "eixo", "casca"]
    if "chapa" in quais:
        # chapa plana: alvos no meio, um com o pé passando da aresta, um torto e com caroço
        al = [dict(tipo="peao_dado", ponto=(-40, 20, 0), normal=(0, 0, 1)),
              dict(tipo="peao", ponto=(10, -22, 0), normal=(0, 0, 1), giro=0.7),
              dict(tipo="dado_base", ponto=(45, 18, 0), normal=(0, 0, 1), giro=0.3),
              dict(tipo="peao_dado", ponto=(-30, -44.0, 0), normal=(0, 0, 1), inclinar=0.12,
                   caroco=[(6, 3, 30, 4.0), (-5, -2, 44, 5.0)], escala=(1.04, 0.97, 1.02)),
              dict(tipo="peao_dado", ponto=(50, -35, 0), normal=(0, 0, 1), giro=1.9)]
        V, F, ver = montar("chapa", [(-74, -54, -14), (74, 54, 64)], 0.45, al, semente=1)
        gravar("chapa", V, F, ver, "chapa")
    if "eixo" in quais:
        # eixo escalonado: alvos nos cilindros (referência = cilindro) e na face da ponta
        def na_lateral(z, ang, r):
            n = np.array([np.cos(ang), np.sin(ang), 0.0])
            return dict(ponto=tuple(n * r + np.array([0, 0, z])), normal=tuple(n))
        al = [dict(tipo="peao_dado", **na_lateral(68, 0.3, 25.0)),
              dict(tipo="peao", **na_lateral(20, 2.4, 18.0)),
              dict(tipo="dado_base", **na_lateral(75, 3.6, 25.0), giro=0.5),
              dict(tipo="peao", ponto=(0, 0, 120.0), normal=(0, 0, 1))]
        V, F, ver = montar("eixo", [(-88, -88, -3), (88, 88, 150)], 0.5, al, semente=2)
        gravar("eixo", V, F, ver, "eixo", extra=dict(perfil=pecas.EIXO))
    if "casca" in quais:
        # calota aberta (só o lado de cima, como num escaneamento de um lado): alvo na borda, pé derretido,
        # esfera e dodecaedro separados do pé
        R = 260.0
        def na_calota(x, y):
            z = np.sqrt(R * R - x * x - y * y) - R
            n = np.array([x, y, z + R]) / R
            return dict(ponto=(x, y, z), normal=tuple(n))
        al = [dict(tipo="peao_dado", **na_calota(-35, 15)),
              dict(tipo="peao_dado", **na_calota(30, 25), fusao=4.5),            # pé virou um caroço
              dict(tipo="peao_dado", **na_calota(20, -30), giro=1.0),
              dict(tipo="peao", **na_calota(-67, -35)),
              dict(tipo="peao_dado", **na_calota(71, -6))]                        # pé em cima da borda da malha
        V, F, ver = montar("casca", [(-80, -60, -26), (80, 60, 66)], 0.45, al, semente=3, R=R)
        # fica só o lado de cima: sai o que está no fundo e nas laterais da calota
        C = V[F].mean(1)
        rho = np.linalg.norm(C - np.array([0, 0, -R]), axis=1)
        fundo = (rho < R - 4.0) | (np.abs(C[:, 0]) > 74.6) | (np.abs(C[:, 1]) > 54.6)
        F = F[~fundo]
        # dodecaedro e esfera do 3º alvo separados do pé, como nos escaneamentos reais (o pescoço fino some)
        a = al[2]
        p, nrm = np.array(a["ponto"]), np.array(a["normal"])
        h = (V[F].mean(1) - p) @ nrm
        rr = np.linalg.norm((V[F].mean(1) - p) - np.outer(h, nrm), axis=1)
        pesc = (rr < 6.0) & (((h > 11.0) & (h < 13.2)) | ((h > 29.0) & (h < 31.5)))
        F = F[~pesc]
        usados = np.zeros(len(V), bool); usados[F.ravel()] = True
        novo = np.cumsum(usados) - 1
        V, F = V[usados], novo[F]
        gravar("casca", V, F, ver, "casca", R=R)
