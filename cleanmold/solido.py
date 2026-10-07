"""Reconhecimento de peça de revolução na malha limpa e montagem do perfil que a reconstrói.

A malha vira: (1) um eixo de revolução; (2) um perfil no plano meridiano (raio × posição ao longo do eixo),
feito de retas e arcos; (3) uma revolução desse perfil. É isso que o STEP e a macro do SolidWorks reproduzem.
O que na peça não é de revolução (palhetas, rasgos, furos fora do eixo, dentes) fica de fora e é informado."""
import math

import numpy as np
from scipy.spatial import cKDTree

from . import ajuste


# ---------------------------------------------------------------------------
# eixo de revolução
# ---------------------------------------------------------------------------

def _complexo(P, N, w):
    """Reta que melhor é cortada por todas as retas normais (p, n): mínimos quadrados em coordenadas de Plücker.
    Devolve (ponto do eixo, direção)."""
    M = np.cross(P, N)
    X = np.hstack([N, M]) * np.sqrt(w)[:, None]
    G = X.T @ X
    A, B, C = G[:3, :3], G[:3, 3:], G[3:, 3:]
    Ai = np.linalg.pinv(A)
    S = C - B.T @ Ai @ B
    val, vec = np.linalg.eigh(S)
    a = vec[:, 0]
    ab = -Ai @ B @ a
    passo = float(a @ ab)
    ab = ab - passo * a
    return np.cross(a, ab), a


def _res_eixo(P, N, c, a):
    """Para cada ponto: distância entre a reta normal e o eixo; seno do ângulo entre a normal e o eixo;
    distância do ponto ao eixo."""
    x = np.cross(N, a)
    s = np.linalg.norm(x, axis=1)
    d = np.abs(np.einsum("ij,ij->i", P - c, x)) / np.maximum(s, 1e-9)
    Q = P - c
    rho = np.linalg.norm(Q - np.outer(Q @ a, a), axis=1)
    return d, s, rho


def _direcoes_planas(N, k=4):
    """Direções das maiores faces planas (picos da distribuição de normais, sem distinguir o sentido)."""
    rng = np.random.default_rng(0)
    sel = N if len(N) <= 60000 else N[rng.choice(len(N), 60000, replace=False)]
    sel = sel * np.where(sel[:, np.argmax(np.abs(sel).mean(0))] < 0, -1, 1)[:, None]
    out = []
    resto = np.ones(len(sel), bool)
    for _ in range(k):
        if resto.sum() < 200:
            break
        # pico: a direção com mais vizinhos a menos de 4°
        cand = sel[resto][rng.choice(resto.sum(), size=min(300, resto.sum()), replace=False)]
        cont = (np.abs(sel[resto] @ cand.T) > 0.9976).sum(0)
        d = cand[np.argmax(cont)]
        perto = np.abs(sel @ d) > 0.9976
        if perto.sum() < 0.03 * len(sel):
            break
        v = sel[perto] * np.sign(sel[perto] @ d)[:, None]
        d = v.mean(0)
        out.append(d / np.linalg.norm(d))
        resto &= np.abs(sel @ d) < 0.99
    return out


def _centro_no_plano(P, N, a, rng):
    """Com a direção do eixo dada, acha por onde ele passa: o ponto do plano por onde passam as normais das
    superfícies laterais. Votação (resiste a palhetas, nervuras e alvos) e depois mínimos quadrados."""
    e1, e2, a = ajuste.base_ortonormal(a)
    lat = np.abs(N @ a) < 0.5
    if lat.sum() < 100:
        return None
    P2 = np.c_[P[lat] @ e1, P[lat] @ e2]
    N2 = np.c_[N[lat] @ e1, N[lat] @ e2]
    N2 /= np.maximum(np.linalg.norm(N2, axis=1), 1e-9)[:, None]
    lo, hi = P2.min(0), P2.max(0)
    ext = float(max(hi - lo))
    meio = (lo + hi) / 2
    alc = 3.5 * ext                                    # num setor de anel o centro fica longe, fora da peça
    G = 320
    cel = 2 * alc / G
    idx = rng.choice(len(P2), size=min(12000, len(P2)), replace=False)
    t = np.arange(-alc * 1.42, alc * 1.42, cel * 0.7)
    X = P2[idx][:, None, :] + t[None, :, None] * N2[idx][:, None, :]
    ij = np.floor((X - (meio - alc)) / cel).astype(np.int64)
    ok = ((ij >= 0) & (ij < G)).all(-1)
    # cada reta vota uma vez por célula
    lin = np.repeat(np.arange(len(idx)), len(t)).reshape(len(idx), len(t))
    chave = (lin[ok] * G + ij[..., 0][ok]) * G + ij[..., 1][ok]
    chave = np.unique(chave)
    votos = np.bincount(chave % (G * G), minlength=G * G).reshape(G, G)
    from scipy import ndimage
    votos = ndimage.uniform_filter(votos.astype(float), 3)
    i, j = np.unravel_index(np.argmax(votos), votos.shape)
    c2 = meio - alc + (np.array([i, j]) + 0.5) * cel
    T2 = np.c_[-N2[:, 1], N2[:, 0]]
    d0 = np.einsum("ij,ij->i", T2, P2)
    for volta in range(12):
        res = T2 @ c2 - d0
        rho = np.maximum(np.linalg.norm(P2 - c2, axis=1), 1e-6)
        e = res / rho
        sc = max(1.4826 * np.median(np.abs(e)), 0.01) if volta > 2 else 0.08
        w = 1.0 / (1.0 + (e / (2 * sc)) ** 2) ** 2 / rho ** 2
        A = (T2 * w[:, None]).T @ T2
        if np.linalg.cond(A) > 1e12:
            break
        c2 = np.linalg.solve(A, (T2 * w[:, None]).T @ d0)
    return c2[0] * e1 + c2[1] * e2


def eixo_de_revolucao(P, N, tol=0.6, angulo=3.0, semente=0):
    """Eixo em torno do qual a maior parte da superfície é de revolução. Devolve dict(ponto, eixo, fracao):
    fracao = parcela das superfícies laterais (as que não são faces planas perpendiculares ao eixo) cuja normal
    passa pelo eixo. Faces planas não contam: toda chapa tem duas. "Passa pelo eixo" = erra por menos de `tol` mm
    ou por menos de `angulo` graus vistos do ponto (numa peça grande, 1° de ruído na normal já são centímetros)."""
    rng = np.random.default_rng(semente)
    c0 = P.mean(0)
    esc = float(np.percentile(np.linalg.norm(P - c0, axis=1), 90)) or 1.0
    Q = (P - c0) / esc
    tg = math.tan(math.radians(angulo))
    n = len(P)

    def concorda(d, rho):
        return d * esc < np.maximum(tol, rho * esc * tg)

    def nota(c, a):
        d, s, rho = _res_eixo(Q, N, c, a)
        lat = s >= 0.2                                   # superfícies laterais: são elas que provam a revolução
        return (float(concorda(d, rho)[lat].mean()) if lat.sum() > 0.02 * n else 0.0), d, s, rho

    cands = []
    # caminho 1: reta cortada por todas as normais (bom para eixos, buchas, peças sem faces planas grandes)
    w = np.ones(n)
    c = a = None
    for _ in range(14):
        c, a = _complexo(Q, N, w)
        d, _, rho = _res_eixo(Q, N, c, a)
        e = d / np.maximum(rho, 1e-6)
        sc = max(1.4826 * np.median(e), 0.3 * tg)
        w = 1.0 / (1.0 + (e / (2.0 * sc)) ** 2)
    cands.append((c, a / np.linalg.norm(a)))
    # caminho 2: a direção vem das faces planas maiores (flanges, anéis, setores com palhetas); o centro, de votação
    for a in _direcoes_planas(N):
        c = _centro_no_plano(Q, N, a, rng)
        if c is not None:
            cands.append((c, a))
    melhor = max(cands, key=lambda ca: nota(*ca)[0])
    c, a = melhor
    frac, d, s, rho = nota(c, a)
    # refino só com quem concorda
    w = (concorda(d, rho) | (s < 0.08)).astype(float)
    if w.sum() > 50 and frac > 0.2:
        for _ in range(4):
            c2, a2 = _complexo(Q, N, w)
            f2, d, s, rho = nota(c2, a2)
            if f2 < frac - 0.02:
                break
            c, a, frac = c2, a2, f2
            w = (concorda(d, rho) | (s < 0.08)).astype(float)
    ponto = c * esc + c0
    a = a / np.linalg.norm(a)
    ponto = ponto + ((c0 - ponto) @ a) * a
    return dict(ponto=ponto, eixo=a, fracao=frac)


# ---------------------------------------------------------------------------
# cortes da malha por planos que contêm o eixo
# ---------------------------------------------------------------------------

def cortar(m, ponto, normal):
    """Corta a malha pelo plano (ponto, normal). Devolve lista de polilinhas 3D (cada uma N×3, na ordem)."""
    d = (m.V - ponto) @ normal
    d = np.where(d == 0, 1e-9, d)
    D = d[m.F]
    cruza = (D.min(1) < 0) & (D.max(1) > 0)
    F = m.F[cruza].astype(np.int64)
    D = D[cruza]
    if not len(F):
        return []
    nos_a, nos_b = [], []                         # cada triângulo liga as duas arestas que ele cruza
    for k in range(3):
        i, j = F[:, k], F[:, (k + 1) % 3]
        di, dj = D[:, k], D[:, (k + 1) % 3]
        c = (di * dj) < 0
        lo, hi = np.minimum(i, j), np.maximum(i, j)
        chave = np.where(c, lo * (m.n_vertices + 1) + hi, -1)
        nos_a.append(chave)
    K = np.stack(nos_a, axis=1)                   # 3 chaves por triângulo; duas válidas
    ordem = np.argsort(K < 0, axis=1, kind="stable")
    K = np.take_along_axis(K, ordem, axis=1)[:, :2]
    u, inv = np.unique(K.ravel(), return_inverse=True)
    inv = inv.reshape(-1, 2)
    lo, hi = u // (m.n_vertices + 1), u % (m.n_vertices + 1)
    t = d[lo] / (d[lo] - d[hi])
    X = m.V[lo] + t[:, None] * (m.V[hi] - m.V[lo])
    n = len(u)
    viz = [[] for _ in range(n)]
    for a, b in inv:
        viz[a].append(b)
        viz[b].append(a)
    visto = np.zeros(n, bool)
    cadeias = []
    grau = np.array([len(v) for v in viz])
    for ini in list(np.flatnonzero(grau == 1)) + list(range(n)):
        if visto[ini] or grau[ini] == 0:
            continue
        cad = [ini]
        visto[ini] = True
        atual = ini
        while True:
            seg = [v for v in viz[atual] if not visto[v]]
            if not seg:
                break
            atual = seg[0]
            visto[atual] = True
            cad.append(atual)
        fechada = len(cad) > 2 and cad[0] in viz[cad[-1]] and grau[cad[0]] == 2
        if fechada:
            cad.append(cad[0])
        if len(cad) >= 2:
            cadeias.append(X[cad])
    return cadeias


def _reamostrar(pl, passo):
    seg = np.linalg.norm(np.diff(pl, axis=0), axis=1)
    s = np.r_[0, np.cumsum(seg)]
    if s[-1] < passo:
        return pl
    t = np.linspace(0, s[-1], int(np.ceil(s[-1] / passo)) + 1)
    return np.c_[np.interp(t, s, pl[:, 0]), np.interp(t, s, pl[:, 1])]


def meridianos(m, ponto, eixo, n=18, passo=0.3):
    """Meias-seções da malha por planos que contêm o eixo. Devolve lista de dict(theta, linhas=[N×2 (z, r)])."""
    e1, e2, a = ajuste.base_ortonormal(eixo)
    out = []
    for k in range(n):
        th = math.pi * k / n
        u = math.cos(th) * e1 + math.sin(th) * e2
        t = -math.sin(th) * e1 + math.cos(th) * e2
        lados = {1: [], -1: []}
        for cad in cortar(m, ponto, t):
            Q = cad - ponto
            z, s = Q @ a, Q @ u
            # separa onde a linha atravessa o eixo
            sinal = np.where(s >= 0, 1, -1)
            cortes = np.flatnonzero(np.diff(sinal) != 0) + 1
            ini = 0
            for fim in list(cortes) + [len(s)]:
                if fim - ini >= 2:
                    pl = _reamostrar(np.c_[z[ini:fim], np.abs(s[ini:fim])], passo)
                    lados[int(sinal[ini])].append(pl)
                ini = fim
        out.append(dict(theta=th, linhas=lados[1]))
        out.append(dict(theta=th + math.pi, linhas=lados[-1]))
    return out


def perfil_de_consenso(secoes, tol=0.4, minimo=0.6):
    """Parte do perfil que se repete em volta do eixo: fica o que aparece em pelo menos `minimo` das seções
    que têm malha. Devolve (lista de polilinhas (z, r) já médias entre as seções, nº de seções com malha)."""
    com = [s for s in secoes if sum(len(l) for l in s["linhas"]) > 10]
    if len(com) < 3:
        return [], len(com)
    arvs = [cKDTree(np.vstack(s["linhas"])) for s in com]
    pts = [np.vstack(s["linhas"]) for s in com]
    melhor = None
    for i, s in enumerate(com):
        total = 0.0
        marcas = []
        for l in s["linhas"]:
            cont = np.zeros(len(l), int)
            for j, arv in enumerate(arvs):
                if j != i:
                    d, _ = arv.query(l, distance_upper_bound=tol)
                    cont += np.isfinite(d)
            ok = cont >= minimo * (len(com) - 1)
            marcas.append(ok)
            total += ok.sum()
        if melhor is None or total > melhor[0]:
            melhor = (total, i, marcas)
    _, i, marcas = melhor
    linhas = []
    for l, ok in zip(com[i]["linhas"], marcas):
        # tapa buracos curtos e descarta trechos curtos
        ok = ok.copy()
        k = 0
        n = len(ok)
        while k < n:
            if not ok[k]:
                j = k
                while j < n and not ok[j]:
                    j += 1
                if k > 0 and j < n and j - k <= 4:
                    ok[k:j] = True
                k = j
            else:
                k += 1
        k = 0
        while k < n:
            if ok[k]:
                j = k
                while j < n and ok[j]:
                    j += 1
                if j - k >= 6:
                    trecho = l[k:j].copy()
                    # média entre as seções: cada ponto vai para o centro dos vizinhos das outras seções
                    soma, cnt = trecho.copy(), np.ones(len(trecho))
                    for jj, arv in enumerate(arvs):
                        if jj != i:
                            d, q = arv.query(trecho, distance_upper_bound=tol)
                            v = np.isfinite(d)
                            soma[v] += pts[jj][q[v]]
                            cnt[v] += 1
                    linhas.append(soma / cnt[:, None])
                k = j
            else:
                k += 1
    return linhas, len(com)


# ---------------------------------------------------------------------------
# polilinha -> retas e arcos
# ---------------------------------------------------------------------------

def _circulo(P):
    x, y = P[:, 0], P[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    s, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    c = s[:2]
    r = math.sqrt(max(s[2] + c @ c, 1e-12))
    return c, r, np.abs(np.linalg.norm(P - c, axis=1) - r)


def _desvio_reta(P):
    a, b = P[0], P[-1]
    v = b - a
    L = np.linalg.norm(v)
    if L < 1e-9:
        return np.linalg.norm(P - a, axis=1)
    return np.abs((P[:, 0] - a[0]) * v[1] - (P[:, 1] - a[1]) * v[0]) / L


def segmentar(pl, tol):
    """Aproxima a polilinha por retas e arcos encadeados, com erro máximo `tol`.
    Devolve lista de dict(tipo='linha'|'arco', p0, p1[, c, r, sentido])  (sentido +1 = anti-horário no plano (z, r))."""
    pl = np.asarray(pl, float)
    ents = []

    def rec(i, j):
        P = pl[i:j + 1]
        dr = _desvio_reta(P)
        if dr.max() <= tol or j - i < 2:
            ents.append(dict(tipo="linha", i=i, j=j))
            return
        if j - i >= 4:
            c, r, dc = _circulo(P)
            corda = np.linalg.norm(P[-1] - P[0])
            if dc.max() <= tol and r < 40 * corda and r > 0.2:
                a0 = math.atan2(P[0][1] - c[1], P[0][0] - c[0])
                am = math.atan2(P[len(P) // 2][1] - c[1], P[len(P) // 2][0] - c[0])
                sentido = 1 if math.sin(am - a0) > 0 else -1
                ents.append(dict(tipo="arco", i=i, j=j, c=c, r=r, sentido=sentido))
                return
        k = i + int(np.argmax(dr))
        k = min(max(k, i + 1), j - 1)
        rec(i, k)
        rec(k, j)
    rec(0, len(pl) - 1)
    # junta retas vizinhas que ficam numa reta só
    juntou = True
    while juntou:
        juntou = False
        for k in range(len(ents) - 1):
            a, b = ents[k], ents[k + 1]
            if a["tipo"] == b["tipo"] == "linha" and _desvio_reta(pl[a["i"]:b["j"] + 1]).max() <= tol:
                ents[k:k + 2] = [dict(tipo="linha", i=a["i"], j=b["j"])]
                juntou = True
                break
    # retas pelos mínimos quadrados dos seus pontos; cantos = interseção das vizinhas
    retas = {}
    for k, e in enumerate(ents):
        if e["tipo"] == "linha":
            P = pl[e["i"]:e["j"] + 1]
            c = P.mean(0)
            _, _, vt = np.linalg.svd(P - c, full_matrices=False)
            d = vt[0]
            if d @ (P[-1] - P[0]) < 0:
                d = -d
            retas[k] = (c, d)
    out = []
    for k, e in enumerate(ents):
        p0, p1 = pl[e["i"]].copy(), pl[e["j"]].copy()
        if e["tipo"] == "linha":
            c, d = retas[k]
            p0 = c + ((p0 - c) @ d) * d
            p1 = c + ((p1 - c) @ d) * d
            out.append(dict(tipo="linha", p0=p0, p1=p1))
        else:
            c, r = e["c"], e["r"]
            p0 = c + (p0 - c) / np.linalg.norm(p0 - c) * r
            p1 = c + (p1 - c) / np.linalg.norm(p1 - c) * r
            out.append(dict(tipo="arco", p0=p0, p1=p1, c=c, r=r, sentido=e["sentido"]))
    for k in range(len(out) - 1):
        a, b = out[k], out[k + 1]
        if a["tipo"] == b["tipo"] == "linha":
            (c1, d1), (c2, d2) = retas[k], retas[k + 1]
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) > 0.05:
                t = ((c2[0] - c1[0]) * d2[1] - (c2[1] - c1[1]) * d2[0]) / den
                x = c1 + t * d1
                if np.linalg.norm(x - a["p1"]) < 20 * tol + 0.5:
                    a["p1"] = x
                    b["p0"] = x.copy()
                    continue
        meio = (a["p1"] + b["p0"]) / 2 if a["tipo"] == b["tipo"] else (a["p1"] if a["tipo"] == "linha" else b["p0"])
        if a["tipo"] == "arco" and b["tipo"] == "linha":
            meio = a["p1"]
        a["p1"] = meio.copy()
        b["p0"] = meio.copy()
    return out


def sem_miudezas(ents, minimo):
    """Tira trechos menores que `minimo` (cantos arredondados pela malha, rebarbas): os vizinhos são esticados
    até se encontrarem."""
    ents = [dict(e) for e in ents]
    mudou = True
    while mudou and len(ents) > 2:
        mudou = False
        for k in range(1, len(ents) - 1):
            e = ents[k]
            comp = np.linalg.norm(e["p1"] - e["p0"])
            a, b = ents[k - 1], ents[k + 1]
            if comp >= minimo or a["tipo"] != "linha" or b["tipo"] != "linha":
                continue
            d1, d2 = a["p1"] - a["p0"], b["p1"] - b["p0"]
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) < 0.05 * np.linalg.norm(d1) * np.linalg.norm(d2):
                continue
            t = ((b["p0"][0] - a["p0"][0]) * d2[1] - (b["p0"][1] - a["p0"][1]) * d2[0]) / den
            x = a["p0"] + t * d1
            if np.linalg.norm(x - e["p0"]) > 3 * minimo or np.linalg.norm(x - e["p1"]) > 3 * minimo:
                continue
            a["p1"] = x
            b["p0"] = x.copy()
            ents.pop(k)
            mudou = True
            break
    return ents


def arrumar(ents, passo_cota=0.01, ang_reto=0.6):
    """Endireita o que é quase reto com o eixo ou quase perpendicular a ele e arredonda as cotas para `passo_cota`.
    Trabalha em (z, r): reta com r constante = cilindro; z constante = face plana."""
    def arred(v):
        return round(float(v) / passo_cota) * passo_cota if passo_cota > 0 else float(v)
    pts = [e["p0"].copy() for e in ents] + [ents[-1]["p1"].copy()]
    fechado = np.linalg.norm(pts[0] - pts[-1]) < 1e-6
    n = len(ents)
    for k, e in enumerate(ents):
        if e["tipo"] != "linha":
            continue
        d = pts[k + 1] - pts[k]
        ang = math.degrees(math.atan2(abs(d[1]), abs(d[0])))
        if ang < ang_reto:                              # cilindro: mesmo raio nas duas pontas
            r = (pts[k][1] + pts[k + 1][1]) / 2
            pts[k][1] = pts[k + 1][1] = r
            e["forma"] = "cilindro"
        elif ang > 90 - ang_reto:                       # face plana: mesma posição axial
            z = (pts[k][0] + pts[k + 1][0]) / 2
            pts[k][0] = pts[k + 1][0] = z
            e["forma"] = "face"
        else:
            e["forma"] = "cone"
    if fechado:
        pts[-1] = pts[0].copy()
    for p in pts:
        p[0], p[1] = arred(p[0]), max(0.0, arred(p[1]))
    if fechado:
        pts[-1] = pts[0].copy()
    out = []
    for k, e in enumerate(ents):
        p0, p1 = pts[k], pts[k + 1]
        if np.linalg.norm(p1 - p0) < 1e-9:
            continue
        if e["tipo"] == "linha":
            out.append(dict(tipo="linha", p0=p0.copy(), p1=p1.copy(), forma=e.get("forma", "cone")))
        else:
            # arco pelos dois pontos arredondados, com o raio arredondado e do mesmo lado do centro original
            r = max(arred(e["r"]), np.linalg.norm(p1 - p0) / 2 + 1e-6)
            m_ = (p0 + p1) / 2
            v = p1 - p0
            L = np.linalg.norm(v)
            nrm = np.array([-v[1], v[0]]) / L
            h = math.sqrt(max(r * r - (L / 2) ** 2, 0.0))
            c = m_ + nrm * h if (e["c"] - m_) @ nrm >= 0 else m_ - nrm * h
            out.append(dict(tipo="arco", p0=p0.copy(), p1=p1.copy(), c=c, r=float(r), sentido=e["sentido"], forma="raio"))
    return out


def pontos_do_perfil(ents, passo=0.5):
    """Polilinha densa (z, r) que percorre as entidades (para desenhar e para medir desvios)."""
    out = []
    for e in ents:
        if e["tipo"] == "linha":
            n = max(2, int(np.ceil(np.linalg.norm(e["p1"] - e["p0"]) / passo)) + 1)
            t = np.linspace(0, 1, n)[:, None]
            out.append(e["p0"] * (1 - t) + e["p1"] * t)
        else:
            a0 = math.atan2(e["p0"][1] - e["c"][1], e["p0"][0] - e["c"][0])
            a1 = math.atan2(e["p1"][1] - e["c"][1], e["p1"][0] - e["c"][0])
            if e["sentido"] > 0 and a1 < a0:
                a1 += 2 * math.pi
            if e["sentido"] < 0 and a1 > a0:
                a1 -= 2 * math.pi
            n = max(3, int(np.ceil(abs(a1 - a0) * e["r"] / passo)) + 1)
            t = np.linspace(a0, a1, n)
            out.append(np.c_[e["c"][0] + e["r"] * np.cos(t), e["c"][1] + e["r"] * np.sin(t)])
    return np.vstack(out)


# ---------------------------------------------------------------------------
# reconhecimento completo
# ---------------------------------------------------------------------------

class NaoRevolucao(ValueError):
    pass


def reconhecer(m, log=lambda s: None, passo_cota=0.01, tolerancia=None, minimo=0.3, detalhe=1.0):
    """Reconhece a peça de revolução. Devolve dict com eixo, perfis (retas e arcos), ângulo coberto, se fecha
    em sólido, cobertura e desvios. Levanta NaoRevolucao quando a malha não é de revolução."""
    passo = max(0.6, m.aresta_mediana() * 1.5, math.sqrt(m.area / 400_000))
    P, N, _ = m.amostrar(passo, suavizar=2, maximo=400_000)
    log("Procurando o eixo de revolução…")
    ex = eixo_de_revolucao(P, N)
    if ex["fracao"] < minimo:
        raise NaoRevolucao(f"Só {100 * ex['fracao']:.0f}% da superfície lateral é de revolução em torno de um eixo. "
                           "A árvore automática só existe para peça de revolução (eixo, bucha, flange, anel, tampa).")
    c, a = ex["ponto"], ex["eixo"]
    e1, e2, a = ajuste.base_ortonormal(a)
    Q = P - c
    z = Q @ a
    th = np.arctan2(Q @ e2, Q @ e1)
    rr = np.hypot(Q @ e1, Q @ e2)
    # origem axial na ponta de menor z; eixo apontando da ponta para o corpo
    z0 = float(np.percentile(z, 0.05))
    c = c + z0 * a
    z = z - z0
    comprimento = float(np.percentile(z, 99.95))
    # ângulo coberto pela malha
    nb = 180
    h = np.bincount((np.floor((th + math.pi) / (2 * math.pi) * nb).astype(int)) % nb, minlength=nb)
    cheio = h > 0.15 * np.median(h[h > 0])
    cobertura_ang = float(cheio.mean())
    setor = None
    if cobertura_ang < 0.93:
        # maior vazio circular define o setor
        dobro = np.r_[cheio, cheio]
        melhor, k = (0, 0), 0
        while k < 2 * nb:
            if not dobro[k]:
                j = k
                while j < 2 * nb and not dobro[j]:
                    j += 1
                if j - k > melhor[0]:
                    melhor = (j - k, k)
                k = j
            else:
                k += 1
        vazio, ini = melhor
        t0 = ((ini + vazio) % nb) / nb * 2 * math.pi - math.pi
        setor = (t0, (nb - vazio) / nb * 2 * math.pi)
        # gira e1 para o começo do setor
        e1n = math.cos(t0) * e1 + math.sin(t0) * e2
        e2 = np.cross(a, e1n)
        e1 = e1n
    log("Cortando a malha por planos que passam pelo eixo…")
    tol = tolerancia or max(0.15, 0.5 * m.aresta_mediana())
    secs = _meridianos_base(m, c, a, e1, e2, setor, passo=min(0.3, max(0.1, 0.5 * m.aresta_mediana())))
    linhas, n_sec = perfil_de_consenso(secs, tol=max(0.4, 2 * tol))
    if not linhas:
        raise NaoRevolucao("Não encontrei um perfil que se repita em volta do eixo.")
    log("Ajustando retas e arcos ao perfil…")
    linhas = _encadear(linhas, folga=max(1.0, 6 * tol))
    perfis = []
    for l in linhas:
        comp = float(np.linalg.norm(np.diff(l, axis=0), axis=1).sum())
        if comp < 3.0:
            continue
        ents = arrumar(sem_miudezas(segmentar(l, tol), detalhe), passo_cota)
        if ents:
            perfis.append(dict(entidades=ents, comprimento=comp))
    if not perfis:
        raise NaoRevolucao("Não encontrei um perfil que se repita em volta do eixo.")
    perfis.sort(key=lambda p: -p["comprimento"])
    principal = perfis[0]
    ents = principal["entidades"]
    # origem axial exatamente na primeira face do perfil principal
    zmin = min(min(e["p0"][0], e["p1"][0]) for e in ents)
    if abs(zmin) > 1e-9:
        for p_ in perfis:
            for e in p_["entidades"]:
                e["p0"][0] -= zmin
                e["p1"][0] -= zmin
                if e["tipo"] == "arco":
                    e["c"] = e["c"] - np.array([zmin, 0.0])
        c = c + zmin * a
        z = z - zmin
        comprimento -= zmin
    # fecha em sólido? (laço fechado, ou pontas no eixo, ou pontas próximas)
    p_ini, p_fim = ents[0]["p0"], ents[-1]["p1"]
    fechado = False
    if np.linalg.norm(p_ini - p_fim) < max(1.0, 8 * tol):
        ents[-1]["p1"] = p_ini.copy()
        fechado = True
    elif p_ini[1] < max(0.6, 4 * tol) and p_fim[1] < max(0.6, 4 * tol):
        p_ini[1] = 0.0
        p_fim[1] = 0.0
        ents[0]["p0"], ents[-1]["p1"] = p_ini, p_fim
        ents.append(dict(tipo="linha", p0=p_fim.copy(), p1=p_ini.copy(), forma="eixo"))
        fechado = True
    solido = fechado and setor is None
    # cobertura e desvio: distância de cada ponto da malha ao perfil, no plano (z, r)
    dens = np.vstack([pontos_do_perfil(p["entidades"], 0.25) for p in perfis if p is principal or p["comprimento"] > 8.0])
    d, _ = cKDTree(dens).query(np.c_[z, rr])
    explicado = d < max(0.5, 3 * tol)
    return dict(tipo="revolucao", ponto=c, eixo=a, e1=e1, e2=e2, comprimento=comprimento, raio_max=float(max(e["p0"][1] for e in ents)),
                setor=None if setor is None else float(setor[1]), fechado=bool(fechado), solido=bool(solido),
                perfil=ents, outros=[p["entidades"] for p in perfis[1:] if p["comprimento"] > 8.0],
                fracao_eixo=float(ex["fracao"]), cobertura=float(explicado.mean()),
                rms=float(np.sqrt(np.mean(d[explicado] ** 2))) if explicado.any() else None,
                tolerancia=float(tol), secoes=int(n_sec), passo_cota=float(passo_cota))


def _meridianos_base(m, c, a, e1, e2, setor, passo, n=18):
    """Como meridianos(), mas na base (e1, e2) dada e só dentro do setor que tem malha."""
    out = []
    if setor is None:
        angs = [math.pi * k / n for k in range(n)]
    else:
        larg = setor[1]
        k = max(6, int(round(n * 2 * larg / (2 * math.pi))))
        angs = [larg * (i + 0.5) / k for i in range(k)]
    for th in angs:
        u = math.cos(th) * e1 + math.sin(th) * e2
        t = -math.sin(th) * e1 + math.cos(th) * e2
        lados = {1: [], -1: []}
        for cad in cortar(m, c, t):
            Q = cad - c
            zz, s = Q @ a, Q @ u
            sinal = np.where(s >= 0, 1, -1)
            cortes = np.flatnonzero(np.diff(sinal) != 0) + 1
            ini = 0
            for fim in list(cortes) + [len(s)]:
                if fim - ini >= 2:
                    lados[int(sinal[ini])].append(_reamostrar(np.c_[zz[ini:fim], np.abs(s[ini:fim])], passo))
                ini = fim
        out.append(dict(theta=th, linhas=lados[1]))
        if setor is None:
            out.append(dict(theta=th + math.pi, linhas=lados[-1]))
    return out


def _encadear(linhas, folga):
    """Emenda polilinhas cujas pontas quase se tocam (o consenso costuma partir o perfil nos cantos)."""
    linhas = [np.asarray(l) for l in linhas]
    mudou = True
    while mudou and len(linhas) > 1:
        mudou = False
        melhor = None
        for i in range(len(linhas)):
            for j in range(len(linhas)):
                if i == j:
                    continue
                for vi in (False, True):
                    for vj in (False, True):
                        a = linhas[i][::-1] if vi else linhas[i]
                        b = linhas[j][::-1] if vj else linhas[j]
                        d = np.linalg.norm(a[-1] - b[0])
                        if d < folga and (melhor is None or d < melhor[0]):
                            melhor = (d, i, j, vi, vj)
        if melhor:
            _, i, j, vi, vj = melhor
            a = linhas[i][::-1] if vi else linhas[i]
            b = linhas[j][::-1] if vj else linhas[j]
            nova = np.vstack([a, b])
            linhas = [l for k, l in enumerate(linhas) if k not in (i, j)] + [nova]
            mudou = True
    # sentido padrão: z crescente no começo
    return [l if l[0][0] <= l[-1][0] else l[::-1] for l in linhas]


def cotas(sol):
    """Lista de cotas do perfil principal, na ordem em que aparecem: diâmetros, comprimentos, cones e raios."""
    out = []
    k = dict(d=0, l=0, c=0, r=0)
    for e in sol["perfil"]:
        if e["tipo"] == "linha":
            f = e.get("forma")
            if f == "cilindro":
                k["d"] += 1
                out.append(dict(nome=f"Ø{k['d']}", tipo="diametro", valor=2 * float(e["p0"][1]),
                                texto=f"de z = {min(e['p0'][0], e['p1'][0]):.2f} a {max(e['p0'][0], e['p1'][0]):.2f} mm"))
            elif f == "face":
                k["l"] += 1
                out.append(dict(nome=f"Z{k['l']}", tipo="posicao", valor=float(e["p0"][0]),
                                texto=f"face plana, de Ø {2 * min(e['p0'][1], e['p1'][1]):.2f} a Ø {2 * max(e['p0'][1], e['p1'][1]):.2f} mm"))
            elif f == "cone":
                k["c"] += 1
                ang = math.degrees(math.atan2(abs(e["p1"][1] - e["p0"][1]), abs(e["p1"][0] - e["p0"][0])))
                out.append(dict(nome=f"C{k['c']}", tipo="cone", valor=ang,
                                texto=f"cone ou chanfro, de Ø {2 * e['p0'][1]:.2f} a Ø {2 * e['p1'][1]:.2f} mm em {abs(e['p1'][0] - e['p0'][0]):.2f} mm"))
        else:
            k["r"] += 1
            out.append(dict(nome=f"R{k['r']}", tipo="raio", valor=float(e["r"]),
                            texto=f"arco perto de z = {e['c'][0]:.2f} mm"))
    return out


def malha_de_revolucao(sol, passo=1.0, max_div=180):
    """Malha de triângulos do perfil girado em torno do eixo (para a tela)."""
    pl = pontos_do_perfil(sol["perfil"], max(passo, sol["comprimento"] / 600))
    ang = sol["setor"] or 2 * math.pi
    nd = int(min(max_div, max(24, math.ceil(ang * sol["raio_max"] / max(passo, 2.0)))))
    fechado_ang = sol["setor"] is None
    t = np.linspace(0, ang, nd, endpoint=not fechado_ang)
    c, a, e1, e2 = sol["ponto"], sol["eixo"], sol["e1"], sol["e2"]
    n = len(pl)
    V = (c[None, None] + pl[:, 0][None, :, None] * a[None, None]
         + pl[:, 1][None, :, None] * (np.cos(t)[:, None, None] * e1[None, None] + np.sin(t)[:, None, None] * e2[None, None]))
    V = V.reshape(-1, 3)
    F = []
    nt = len(t)
    for i in range(nt if fechado_ang else nt - 1):
        j = (i + 1) % nt
        a0 = i * n + np.arange(n - 1)
        b0 = j * n + np.arange(n - 1)
        F.append(np.c_[a0, b0, a0 + 1])
        F.append(np.c_[a0 + 1, b0, b0 + 1])
    return V, np.vstack(F)
