"""Otimização da malha: menos triângulos com a mesma forma.

Onde a peça é plana ou pouco curva, muitos triângulos pequenos viram poucos grandes; onde há detalhe (raios, cantos,
ressaltos), os triângulos ficam. O critério é uma tolerância em mm: uma aresta só é desfeita se o vértice que sobra
continuar a menos dessa distância de todas as faces que ele substitui (erro quádrico, Garland e Heckbert).

A malha é reduzida em blocos, com a orla de cada bloco congelada, para o consumo de memória não depender do tamanho
da malha. Uma segunda passada, com os blocos cortados em outros lugares, reduz as faixas que ficaram nas orlas.
A borda aberta da malha (e o contorno de cada furo) não é mexida.

Depois de reduzir, o desvio é MEDIDO: distância de pontos da malha original à malha nova e vice-versa."""
import os
import sys

import numpy as np

from .malha import Malha

NIVEIS = dict(fiel=0.02, equilibrado=0.05, leve=0.10)       # tolerância em mm
BLOCO = 700_000                                              # triângulos por bloco


def _biblioteca_do_windows():
    """O redutor (pyfqmr) precisa da MSVCP140.dll, que só existe no Windows com o Visual C++ instalado. O numpy traz
    uma cópia dela; fica ao lado do redutor uma cópia com o nome que ele procura."""
    if not sys.platform.startswith("win"):
        return
    try:
        import glob
        import importlib.util
        import shutil
        spec = importlib.util.find_spec("pyfqmr")
        if spec is None or not spec.origin:
            return
        destino = os.path.join(os.path.dirname(spec.origin), "msvcp140.dll")
        if os.path.isfile(destino):
            return
        cand = glob.glob(os.path.join(os.path.dirname(os.path.dirname(np.__file__)), "numpy.libs", "msvcp140*.dll"))
        if cand:
            shutil.copyfile(cand[0], destino)
    except Exception:
        pass


def disponivel():
    try:
        import pyfqmr  # noqa: F401
        return True
    except Exception:
        pass
    _biblioteca_do_windows()
    for nome in [k for k in sys.modules if k == "pyfqmr" or k.startswith("pyfqmr.")]:
        sys.modules.pop(nome, None)
    try:
        import pyfqmr  # noqa: F401
        return True
    except Exception:
        return False


def _codigo(V):
    """Um número de 64 bits por ponto (para casar coordenadas iguais bit a bit)."""
    V = np.ascontiguousarray(V, dtype=np.float64) + 0.0
    u = V.view(np.uint64).reshape(len(V), 3)
    h = u[:, 0] * np.uint64(0x9E3779B97F4A7C15)
    h ^= (u[:, 1] * np.uint64(0xC2B2AE3D27D4EB4F)) >> np.uint64(7)
    h += u[:, 2] * np.uint64(0x165667B19E3779F9)
    h ^= h >> np.uint64(29)
    return h


def particionar(C, maximo, fracao=0.5):
    """Divide os triângulos em blocos compactos de até `maximo`, cortando sempre a direção mais comprida.
    `fracao` desloca o ponto de corte (0,5 = no meio), para duas passadas não cortarem no mesmo lugar."""
    blocos, pilha = [], [np.arange(len(C), dtype=np.int64)]
    while pilha:
        idx = pilha.pop()
        if len(idx) <= maximo:
            blocos.append(idx)
            continue
        P = C[idx]
        eixo = int(np.argmax(P.max(0) - P.min(0)))
        k = int(len(idx) * fracao)
        k = min(max(k, 1), len(idx) - 1)
        ordem = np.argpartition(P[:, eixo], k)
        pilha.append(idx[ordem[:k]])
        pilha.append(idx[ordem[k:]])
    return blocos


def _poly(V, F):
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    pd = vtkPolyData()
    pts = vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(V, np.float64), deep=True))
    pd.SetPoints(pts)
    ca = vtkCellArray()
    off = np.arange(0, 3 * len(F) + 1, 3, dtype=np.int64)
    ca.SetData(numpy_to_vtkIdTypeArray(off, deep=True), numpy_to_vtkIdTypeArray(np.ascontiguousarray(F, np.int64).ravel(), deep=True))
    pd.SetPolys(ca)
    return pd


def distancia_a_malha(P, V, F):
    """Distância exata de cada ponto de P à superfície da malha (V, F)."""
    from vtkmodules.vtkCommonCore import reference
    from vtkmodules.vtkCommonDataModel import vtkGenericCell, vtkStaticCellLocator
    pd = _poly(V, F)
    loc = vtkStaticCellLocator()
    loc.SetDataSet(pd)
    loc.BuildLocator()
    out = np.empty(len(P))
    cp = [0.0, 0.0, 0.0]
    cel = vtkGenericCell()
    cid, sid, d2 = reference(0), reference(0), reference(0.0)
    for i, p in enumerate(np.asarray(P, float)):
        loc.FindClosestPoint(p, cp, cel, cid, sid, d2)
        out[i] = d2.get()
    return np.sqrt(out)


def _pontos_na_superficie(V, F, n, rng):
    T = V[F]
    a = np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    if a.sum() <= 0:
        return np.zeros((0, 3))
    f = rng.choice(len(F), size=n, p=a / a.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    b = np.c_[1 - s, s * (1 - r2), s * r2]
    return (T[f] * b[:, :, None]).sum(1)


def _reduzir_bloco(V, F, eps, voltas=20):
    """Reduz um bloco com a orla congelada. Devolve (V2, F2) ou None se não deu para reduzir."""
    import pyfqmr
    s = pyfqmr.Simplify()
    s.setMesh(np.ascontiguousarray(V, np.float64), np.ascontiguousarray(F, np.int32))
    s.simplify_mesh_lossless(epsilon=float(eps), max_iterations=int(voltas), preserve_border=True, verbose=False)
    V2, F2, _ = s.getMesh()
    V2 = np.asarray(V2, np.float64)
    F2 = np.asarray(F2, np.int64).reshape(-1, 3)
    if len(F2) == 0 or len(F2) >= len(F):
        return None
    return V2, F2


def _n_bordas(F, n_v):
    """Nº de arestas com um triângulo só."""
    n = n_v + 1
    ch = np.concatenate([np.minimum(F[:, k], F[:, (k + 1) % 3]).astype(np.int64) * n + np.maximum(F[:, k], F[:, (k + 1) % 3]) for k in range(3)])
    _, c = np.unique(ch, return_counts=True)
    return int((c == 1).sum())


def _passada(V, F, C, eps, maximo, fracao, log, rotulo, medir=0, medidas=None, rng=None):
    """Uma passada por blocos. Devolve (V novo, F novo, origem de cada triângulo novo ou -1)."""
    blocos = particionar(C, maximo, fracao)
    V_extra, F_out = [], []
    n_v = len(V)
    n_extra = 0
    feito = 0
    total = len(F)
    for b, idx in enumerate(blocos):
        Fb = F[idx]
        vu, inv = np.unique(Fb, return_inverse=True)
        Vb = V[vu]
        Fl = inv.reshape(-1, 3)
        r = None
        try:
            r = _reduzir_bloco(Vb, Fl, eps)
        except MemoryError:
            raise
        except Exception:
            r = None
        if r is not None:
            V2, F2 = r
            # vértices que já existiam (todos os da orla, e os de dentro que não saíram do lugar) mantêm o número
            hb = _codigo(Vb)
            ordem = np.argsort(hb, kind="stable")
            h2 = _codigo(V2)
            pos = np.clip(np.searchsorted(hb[ordem], h2), 0, len(hb) - 1)
            cand = ordem[pos]
            igual = (hb[cand] == h2) & (Vb[cand] == V2).all(axis=1)
            g = np.empty(len(V2), np.int64)
            g[igual] = vu[cand[igual]]
            n_novos = int((~igual).sum())
            g[~igual] = n_v + n_extra + np.arange(n_novos)
            # a orla do bloco tem de ter ficado inteira: se algum vértice dela sumiu, o bloco fica como estava
            orla = _orla(Fl, len(Vb))
            if np.isin(vu[orla], g[igual]).all():
                if medir and medidas is not None and len(F2) > 50:
                    k = int(np.clip(medir * len(idx) / max(total, 1), 300, 20000))
                    P = _pontos_na_superficie(V2, F2, k, rng)
                    if len(P):
                        try:
                            medidas.append(distancia_a_malha(P, Vb, Fl))
                        except Exception:
                            pass
                V_extra.append(V2[~igual])
                n_extra += n_novos
                F_out.append(g[F2])
            else:
                F_out.append(Fb.astype(np.int64))
        else:
            F_out.append(Fb.astype(np.int64))
        feito += len(idx)
        log(f"{rotulo} {int(100 * feito / max(total, 1))}%")
    Vn = np.vstack([V] + V_extra) if V_extra else V
    Fn = np.vstack(F_out)
    return Vn, Fn


def _orla(F, n_v):
    """Vértices na orla de um bloco (em arestas com um triângulo só)."""
    n = n_v + 1
    i = np.concatenate([F[:, k] for k in range(3)]).astype(np.int64)
    j = np.concatenate([F[:, (k + 1) % 3] for k in range(3)]).astype(np.int64)
    ch = np.minimum(i, j) * n + np.maximum(i, j)
    u, inv, c = np.unique(ch, return_inverse=True, return_counts=True)
    livre = c[inv] == 1
    v = np.zeros(n_v, bool)
    v[i[livre]] = True
    v[j[livre]] = True
    return np.flatnonzero(v)


def reduzir(m, tolerancia=0.05, log=lambda s: None, bloco=BLOCO, medir=200_000, semente=0):
    """Reduz a malha `m`. Devolve (malha nova, info).

    info: dict(antes, depois, tolerancia, desvio=dict(medio, p99, maximo, pontos) ou None, bordas_iguais)."""
    if not disponivel():
        raise RuntimeError("A biblioteca de redução de malha (pyfqmr) não está instalada neste computador.")
    tol = float(tolerancia)
    if not (0.001 <= tol <= 1.0):
        raise ValueError("A tolerância precisa ficar entre 0,001 e 1 mm.")
    eps = tol * tol
    rng = np.random.default_rng(semente)
    n0 = m.n_faces
    V, F = m.V, m.F
    bordas0 = _n_bordas(F, len(V))
    medidas = []
    log("Otimizando a malha… 0%")
    V, F = _passada(V, F, m.C, eps, bloco, 0.5, log, "Otimizando a malha…", medir=medir, medidas=medidas, rng=rng)
    # segunda passada: os cortes caem em outros lugares, e as faixas das orlas da primeira são reduzidas
    usados = np.zeros(len(V), bool)
    usados[F.ravel()] = True
    renum = np.cumsum(usados) - 1
    V, F = V[usados], renum[F]
    if len(F) > 50:
        C = (V[F[:, 0]] + V[F[:, 1]] + V[F[:, 2]]) / 3.0
        V, F = _passada(V, F, C, eps, int(bloco * 1.37), 0.38, log, "Acertando as emendas…")
        usados = np.zeros(len(V), bool)
        usados[F.ravel()] = True
        renum = np.cumsum(usados) - 1
        V, F = V[usados], renum[F]
    nova = Malha(V, F, nome=m.nome)
    bordas1 = _n_bordas(nova.F, nova.n_vertices)                 # conferido antes de tirar as lascas (que têm borda própria)
    inteira = nova                                               # o desvio é medido contra a malha antes de tirar as lascas
    # lascas: dois ou três triângulos de área quase nula que a redução deixou pendurados numa aresta, e triângulos
    # perdidos que já vinham soltos no arquivo
    rot, n = nova.componentes()
    if n > 1:
        cont = np.bincount(rot, minlength=n)
        area = np.bincount(rot, weights=nova.A, minlength=n)
        fe, _, c_ar = nova.arestas()
        pendurado = np.zeros(n, bool)
        pendurado[np.unique(rot[(c_ar[fe] > 2).any(axis=1)])] = True      # preso por uma aresta com três triângulos
        lasca = (cont <= 8) & ((area < 0.2) | pendurado)
        if lasca.any() and not lasca.all():
            nova, _ = nova.sub(~lasca[rot])
    info = dict(antes=int(n0), depois=int(nova.n_faces), tolerancia=tol, desvio=None, bordas_iguais=bool(bordas1 == bordas0),
                bordas=(int(bordas0), int(bordas1)))
    if bordas1 != bordas0:
        raise RuntimeError("A redução abriu a malha nas emendas dos blocos; a malha não foi alterada.")
    if medir:
        log("Medindo o desvio…")
        try:
            k = int(min(medir, m.n_vertices))
            P = m.V[rng.choice(m.n_vertices, size=k, replace=False)]
            d1 = distancia_a_malha(P, inteira.V, inteira.F)
            d2 = np.concatenate(medidas) if medidas else np.zeros(0)
            d = np.concatenate([d1, d2])
            info["desvio"] = dict(medio=float(d.mean()), p99=float(np.percentile(d, 99)), maximo=float(d.max()), pontos=int(len(d)),
                                  maximo_ida=float(d1.max()), maximo_volta=float(d2.max()) if len(d2) else None)
        except Exception as e:                                   # a medida é conferência: sem ela a redução vale, mas avisa
            info["desvio_erro"] = f"{type(e).__name__}: {e}"
    log(f"Malha otimizada: {n0:,} → {nova.n_faces:,} triângulos".replace(",", "."))
    return nova, info


def transferir_marca(m_velha, marca, m_nova, raio=None):
    """Leva uma marca por triângulo (por exemplo "é remendo") da malha velha para a nova, por proximidade."""
    from scipy.spatial import cKDTree
    out = np.zeros(m_nova.n_faces, bool)
    marca = np.asarray(marca, bool)
    if not marca.any():
        return out
    arv = cKDTree(m_velha.C[marca])
    r = raio if raio is not None else max(1.0, 2.0 * m_velha.aresta_mediana())
    d, _ = arv.query(m_nova.C, distance_upper_bound=r)
    out[np.isfinite(d)] = True
    return out
