"""Fechamento de um furo da malha: triangula o contorno e assenta o remendo na superfície de referência."""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.spatial import Delaunay, cKDTree

from . import superficie


def lacos(bordas):
    """Organiza meias-arestas livres (de, para) em laços fechados. Devolve lista de arrays de vértices, na
    ordem das meias-arestas (o furo fica à direita de quem caminha). Pedaços que não fecham são descartados."""
    prox = {}
    for a, b in bordas:
        prox.setdefault(int(a), []).append(int(b))
    out = []
    while prox:
        ini = next(iter(prox))
        laco = [ini]
        atual = ini
        fechado = False
        for _ in range(len(bordas) + 2):
            lst = prox.get(atual)
            if not lst:
                break
            seg = lst.pop()
            if not lst:
                del prox[atual]
            if seg == ini:
                fechado = True
                break
            laco.append(seg)
            atual = seg
        if fechado and len(laco) >= 3:
            out += _sem_nos(laco)
    return out


def _sem_nos(laco):
    """Um laço que passa duas vezes pelo mesmo vértice (dois furos encostados num ponto) vira dois laços."""
    pilha, out = [list(laco)], []
    while pilha:
        l = pilha.pop()
        visto = {}
        corte = None
        for i, v in enumerate(l):
            if v in visto:
                corte = (visto[v], i)
                break
            visto[v] = i
        if corte is None:
            if len(l) >= 3:
                out.append(np.array(l, dtype=np.int64))
            continue
        i, j = corte
        pilha.append(l[i:j])
        pilha.append(l[:i] + l[j:])
    return out


def _area2(p):
    x, y = p[:, 0], p[:, 1]
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _dentro(pol, pts):
    """Pontos dentro do polígono (regra par-ímpar), vetorizado."""
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    x1, y1 = pol[:, 0][None], pol[:, 1][None]
    x2, y2 = np.roll(pol[:, 0], -1)[None], np.roll(pol[:, 1], -1)[None]
    cruza = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    return (np.sum(cruza & (x < xi), axis=1) % 2) == 1


def _simples(pol):
    """O polígono não se cruza? (teste de interseção entre todos os pares de lados não vizinhos)"""
    n = len(pol)
    if n > 2500:
        return True                                  # grande demais para o teste completo; a triangulação confere depois
    a, b = pol, np.roll(pol, -1, axis=0)
    d = b - a

    def lado(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    A, B = a[:, None], b[:, None]
    C, D = a[None], b[None]
    o1, o2 = lado(A, B, C), lado(A, B, D)
    o3, o4 = lado(C, D, A), lado(C, D, B)
    x = (o1 * o2 < 0) & (o3 * o4 < 0)
    i, j = np.nonzero(x)
    viz = (np.abs(i - j) <= 1) | (np.abs(i - j) == n - 1)
    return not np.any(~viz)


def triangular(pol, passo):
    """Triangula o interior de um polígono simples 2D sem mexer no contorno, com pontos internos a cada ~passo.
    Devolve (pontos 2D [contorno primeiro], triângulos em sentido anti-horário, divisões).
    `divisões` lista os lados do contorno que tiveram de ganhar um ponto no meio: (i, j, índice do ponto novo)."""
    pol = np.asarray(pol, float)
    if _area2(pol) < 0:
        raise ValueError("contorno em sentido horário")
    contorno = list(range(len(pol)))                 # sequência de índices de ponto ao longo do contorno
    pts = [p for p in pol]
    divisoes = []
    lo, hi = pol.min(0), pol.max(0)
    xs = np.arange(lo[0], hi[0] + passo, passo)
    ys = np.arange(lo[1], hi[1] + passo, passo * 0.8660254)
    gx, gy = np.meshgrid(xs, ys)
    gx = gx + (np.arange(len(ys)) % 2)[:, None] * passo / 2
    grade = np.c_[gx.ravel(), gy.ravel()]
    grade = grade[_dentro(pol, grade)]
    for _ in range(10):
        P = np.array(pts)
        C = P[contorno]
        g = grade
        if len(g):
            # longe do contorno: distância aos vértices e aos meios dos lados
            ref = np.vstack([C, (C + np.roll(C, -1, axis=0)) / 2])
            dmin, _ = cKDTree(ref).query(g)
            g = g[dmin > 0.6 * passo]
        todos = np.vstack([P, g]) if len(g) else P
        # pontos exatamente alinhados na borda seriam deixados de fora pelo triangulador: um tremor mínimo
        # (milionésimos de mm, só para triangular) garante que todos entram
        trem = todos + np.random.default_rng(len(todos)).normal(0, 2e-6 * max(passo, 0.1), todos.shape)
        try:
            tri = Delaunay(trem).simplices
        except Exception:
            tri = Delaunay(trem, qhull_options="QJ Qbb Qc Qz").simplices
        cen = todos[tri].mean(1)
        tri = tri[_dentro(C, cen)]
        a, b, c = todos[tri[:, 0]], todos[tri[:, 1]], todos[tri[:, 2]]
        ar = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        fino = np.abs(ar) > 2e-4 * passo * passo            # lascas entre pontos alinhados não entram
        tri = tri[fino]
        ar = ar[fino]
        tri[ar < 0] = tri[ar < 0][:, ::-1]
        # todos os lados do contorno precisam existir na triangulação, uma vez só
        e = np.vstack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
        n = len(todos)
        chaves = e[:, 0] * n + e[:, 1]
        ci = np.array(contorno)
        cj = np.roll(ci, -1)
        tem = np.isin(ci * n + cj, chaves)
        if tem.all():
            # cada aresta interna aparece nos dois sentidos; as do contorno, só no sentido do contorno
            inv = np.isin(cj * n + ci, chaves)
            if not inv.any():
                return todos, tri, divisoes
        falta = np.flatnonzero(~tem)
        if not len(falta):
            break
        novo_contorno = []
        for k, i in enumerate(contorno):
            novo_contorno.append(i)
            if not tem[k]:
                j = contorno[(k + 1) % len(contorno)]
                pts.append((np.array(pts[i]) + np.array(pts[j])) / 2)
                divisoes.append((i, j, len(pts) - 1))
                novo_contorno.append(len(pts) - 1)
        contorno = novo_contorno
    raise ValueError("não consegui triangular o contorno")


def harmonico(pts, tri, n_borda, valores, fixos=None):
    """Interpola `valores` (dados nos pontos fixos) para os demais pontos, suavemente (equação de Laplace
    com pesos de cotangente). `fixos`: máscara dos pontos de valor dado; padrão = os n_borda primeiros."""
    n = len(pts)
    if fixos is None:
        fixos = np.zeros(n, bool)
        fixos[:n_borda] = True
    livres = np.flatnonzero(~fixos)
    x = np.zeros(n)
    x[fixos] = valores
    if not len(livres):
        return x
    I, J, W = [], [], []
    for k in range(3):
        i, j, o = tri[:, k], tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
        u, v = pts[i] - pts[o], pts[j] - pts[o]
        cot = (u * v).sum(1) / np.maximum(np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]), 1e-12)
        w = np.maximum(cot, 0.02) / 2
        I += [i, j]
        J += [j, i]
        W += [w, w]
    I, J, W = np.concatenate(I), np.concatenate(J), np.concatenate(W)
    L = sparse.coo_matrix((W, (I, J)), shape=(n, n)).tocsr()
    D = sparse.diags(np.asarray(L.sum(1)).ravel())
    A = (D - L).tocsr()
    All = A[livres][:, livres].tocsc()
    b = -A[livres][:, np.flatnonzero(fixos)] @ x[fixos]
    x[livres] = spsolve(All, b)
    return x


def fechar(V, laco, modelo, c, n, e1, e2):
    """Fecha o furo de contorno `laco` (índices em V, furo à direita) com um remendo sobre `modelo`.
    Devolve dict(V_novos, F, divisoes, area, degrau) ou levanta ValueError se o contorno não serve.
    F usa os índices de V para o contorno e len(V)+k para o k-ésimo vértice novo."""
    Q = V[laco] - c
    pol = np.c_[Q @ e1, Q @ e2]
    idx = np.asarray(laco)
    if _area2(pol) < 0:                                # visto de fora o furo é percorrido em sentido horário
        pol, idx = pol[::-1], idx[::-1]
    lados = np.linalg.norm(pol - np.roll(pol, -1, axis=0), axis=1)
    passo = float(np.clip(np.median(lados) * 1.05, 0.15, 4.0))
    # o contorno recortado por triângulos faz degraus; vistos de cima alguns degraus se sobrepõem. Para montar a
    # triangulação usa-se o contorno levemente alisado no plano (os vértices da malha não saem do lugar).
    for _ in range(3):
        if _simples(pol):
            break
        pol = 0.5 * pol + 0.25 * (np.roll(pol, 1, axis=0) + np.roll(pol, -1, axis=0))
    else:
        if not _simples(pol):
            raise ValueError("o contorno do furo se cruza")
    pol = 0.5 * pol + 0.25 * (np.roll(pol, 1, axis=0) + np.roll(pol, -1, axis=0))
    if not _simples(pol) or _area2(pol) <= 0:
        raise ValueError("o contorno do furo se cruza")
    pts, tri, divisoes = triangular(pol, passo)
    nb = len(pol)
    nt = len(pts)
    # altura do modelo em cada ponto, ao longo de n
    P0 = c + pts[:, :1] * e1 + pts[:, 1:2] * e2
    t_mod = superficie.altura_sobre(modelo, P0, n)
    # contorno: altura verdadeira; pontos criados no meio de um lado ficam na corda (não mexem na malha vizinha)
    fixos = np.zeros(nt, bool)
    fixos[:nb] = True
    t_real = np.zeros(nt)
    t_real[:nb] = (V[idx] - c) @ n
    pos3 = np.zeros((nt, 3))
    pos3[:nb] = V[idx]
    for i, j, k in divisoes:
        fixos[k] = True
        pos3[k] = (pos3[i] + pos3[j]) / 2
        t_real[k] = (pos3[k] - c) @ n
    delta = harmonico(pts, tri, nb, (t_real - t_mod)[fixos], fixos)
    t = t_mod + delta
    P = P0 + t[:, None] * n
    P[fixos] = pos3[fixos]
    # índices finais: contorno -> vértices existentes; o resto -> novos
    mapa = np.empty(nt, np.int64)
    mapa[:nb] = idx
    novos = np.arange(nb, nt)
    mapa[novos] = len(V) + np.arange(len(novos))
    F = mapa[tri]
    T = P[tri]
    area = float(np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1).sum() / 2)
    return dict(V_novos=P[novos], F=F, divisoes=[(int(mapa[i]), int(mapa[j]), int(mapa[k])) for i, j, k in divisoes],
                area=area, degrau=float(np.percentile(np.abs((t_real - t_mod)[:nb]), 95)), triangulos=int(len(F)), passo=passo)
