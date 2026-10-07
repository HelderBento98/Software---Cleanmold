"""Ferramentas de edição e reparo da malha.

- seleção por pincel (bola 3D que só pega o que está ligado ao ponto tocado: o outro lado de uma parede fina fica de
  fora);
- apagar a seleção, com ou sem preenchimento do furo pela superfície vizinha;
- furos: lista dos contornos abertos e fechamento seguindo a geometria em volta (plano, cilindro, esfera, cone ou
  superfície suave; aresta viva refeita quando o furo desce por uma parede);
- alisar a seleção;
- diagnóstico e reparo automático (arestas com três ou mais triângulos, pedaços soltos, triângulos virados,
  furos pequenos).

Toda operação devolve uma malha NOVA e, para cada triângulo dela, o índice do triângulo de origem (ou -1 se é
novo), para quem guarda informação por triângulo poder acompanhar."""
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from . import ajuste, remendo, superficie
from .limpeza import _dividir_arestas, _normal, _remendar, orelhas
from .malha import Malha


# ---------------------------------------------------------------------------
# seleção por pincel
# ---------------------------------------------------------------------------

def _rotulos_locais(F):
    """Rótulo do pedaço ligado (por aresta) de cada triângulo de uma lista de triângulos."""
    k = len(F)
    if k == 0:
        return np.zeros(0, np.int64), 0
    i = np.concatenate([F[:, 0], F[:, 1], F[:, 2]]).astype(np.int64)
    j = np.concatenate([F[:, 1], F[:, 2], F[:, 0]]).astype(np.int64)
    base = int(max(i.max(), j.max())) + 1
    ch = np.minimum(i, j) * base + np.maximum(i, j)
    ordem = np.argsort(ch, kind="stable")
    chs = ch[ordem]
    f = ordem % k
    igual = chs[1:] == chs[:-1]
    a, b = f[:-1][igual], f[1:][igual]
    g = sparse.coo_matrix((np.ones(len(a), np.int8), (a, b)), shape=(k, k)).tocsr()
    n, rot = csgraph.connected_components(g, directed=False)
    return rot, n


def pintar(m, selecao, pinceladas):
    """Aplica pinceladas à seleção. pinceladas: N×5 (x, y, z, raio, modo); modo 1 pinta, 0 despinta.
    Cada pincelada pega os triângulos dentro da bola que estão ligados ao ponto tocado."""
    sel = np.zeros(m.n_faces, bool) if selecao is None else np.array(selecao, bool)
    P = np.asarray(pinceladas, float).reshape(-1, 5)
    g = m.grade()
    i = 0
    while i < len(P):
        j = i
        while j < len(P) and P[j, 4] == P[i, 4]:
            j += 1
        partes, sementes = [], []
        for x, y, z, r, _ in P[i:j]:
            c = np.array([x, y, z])
            idx = g.bola(c, r)
            if not len(idx):
                continue
            d = m.C[idx] - c
            sementes.append(int(idx[np.argmin(np.einsum("ij,ij->i", d, d))]))
            partes.append(idx)
        if partes:
            cand = np.unique(np.concatenate(partes))
            rot, _ = _rotulos_locais(m.F[cand])
            pos = np.searchsorted(cand, np.array(sementes))
            pega = np.isin(rot, np.unique(rot[pos]))
            sel[cand[pega]] = bool(P[i, 4])
        i = j
    return sel


def crescer(m, sel, voltas=1):
    """Aumenta (voltas > 0) ou encolhe (voltas < 0) a seleção em uma faixa de triângulos por volta."""
    sel = np.array(sel, bool)
    for _ in range(abs(int(voltas))):
        v = np.zeros(m.n_vertices, bool)
        if voltas > 0:
            v[m.F[sel].ravel()] = True
            sel = v[m.F].any(axis=1)
        else:
            v[m.F[~sel].ravel()] = True
            sel = sel & ~v[m.F].any(axis=1)
    return sel


# ---------------------------------------------------------------------------
# recorte local e fechamento de laços
# ---------------------------------------------------------------------------

class _Recorte:
    """Um pedaço da malha com índices próprios: triângulos `idx` (globais, em ordem)."""

    def __init__(self, m, idx):
        self.idx = np.asarray(idx, np.int64)
        self.vu, inv = np.unique(m.F[self.idx], return_inverse=True)
        self.V = m.V[self.vu]
        self.F = inv.reshape(-1, 3).astype(np.int64)

    def local(self, v_globais):
        """Índices locais de vértices globais (-1 para quem não está no recorte)."""
        v = np.asarray(v_globais, np.int64)
        pos = np.clip(np.searchsorted(self.vu, v), 0, len(self.vu) - 1)
        return np.where(self.vu[pos] == v, pos, -1)


def _normal_de_newell(P):
    """Normal de um contorno fechado (vetor de área). Para um furo percorrido com ele à direita, aponta para dentro
    da peça; por isso devolve com o sinal trocado: para fora."""
    Q = np.roll(P, -1, axis=0)
    n = np.array([np.sum((P[:, 1] - Q[:, 1]) * (P[:, 2] + Q[:, 2])),
                  np.sum((P[:, 2] - Q[:, 2]) * (P[:, 0] + Q[:, 0])),
                  np.sum((P[:, 0] - Q[:, 0]) * (P[:, 1] + Q[:, 1]))])
    k = np.linalg.norm(n)
    return -n / k if k > 1e-12 else np.array([0.0, 0.0, 1.0])


def _ajustar_fino(P, N, c, a):
    """Escolha do modelo com a tolerância acertada pelo ruído da própria vizinhança: numa malha limpa, uma
    superfície pouco curva não é confundida com um plano (o remendo sairia chato, sem a flecha da curva)."""
    registro = []
    modelo, sigma, fracao = superficie.ajustar(P, N, c, a, registro=registro)
    sigmas = [x[1] for x in (registro[0] if registro else []) if x[1] < 9.0]
    if sigmas:
        tol = float(np.clip(3.0 * min(sigmas), 0.03, 0.35))
        if tol < 0.3:
            modelo, sigma, fracao = superficie.ajustar(P, N, c, a, tol=tol)
    return modelo, sigma, fracao


def _gradiente(modelo, P, eps=0.02):
    """Normal do modelo em cada ponto de P (gradiente numérico da distância)."""
    g = np.zeros((len(P), 3))
    for k in range(3):
        e = np.zeros(3)
        e[k] = eps
        g[:, k] = (modelo.dist(P + e) - modelo.dist(P - e)) / (2 * eps)
    return g / np.maximum(np.linalg.norm(g, axis=1), 1e-9)[:, None]


class _Vizinhanca:
    """A peça em volta de um contorno, separada em superfícies. Parte de um ponto liso junto ao contorno, ajusta um
    modelo à vizinhança dele e vai juntando os pontos em volta que o modelo explica (distância e normal); o que
    sobra é outra superfície, e assim por diante. O contorno fica dividido em trechos, um por superfície."""

    def __init__(self, V, laco, marcados, pares, nv_bruta, nvk, arv_v, ids_v, maximo=4):
        self.V, self.nvk = V, nvk
        self.marcados = np.asarray(marcados, np.int64)
        pts = V[self.marcados]
        c = pts.mean(0)
        self.R = float(np.linalg.norm(pts - c, axis=1).max())
        w = float(np.clip(1.0 * self.R, 6.0, 25.0))
        sub = pts[::max(1, len(pts) // 300)]
        viz = set()
        for lst in arv_v.query_ball_point(sub, w):
            viz.update(lst)
        viz = ids_v[np.fromiter(viz, dtype=np.int64)] if viz else np.zeros(0, np.int64)
        viz = np.unique(viz[viz < len(nvk)])
        self.viz = viz
        self.a_laco = _normal_de_newell(V[laco])
        self.superficies = []                                  # (modelo, normal no contorno, sigma, fração, nº de pontos)
        self.principal = -1
        if len(viz) < 20:
            return
        P, N = V[viz], nvk[viz]
        arv_l = cKDTree(V[laco])
        d_laco, _ = arv_l.query(P)
        beira = float(np.clip(0.12 * self.R, 0.6, 1.5))
        # ponto liso: a normal (sem alisar) quase não muda para os vizinhos
        dentro = np.zeros(len(nvk), bool)
        dentro[viz] = True
        e = pares[dentro[pares[:, 0]] & dentro[pares[:, 1]]]
        cosv = np.einsum("ij,ij->i", nv_bruta[e[:, 0]], nv_bruta[e[:, 1]])
        pior = np.ones(len(nvk))
        np.minimum.at(pior, e[:, 0], cosv)
        np.minimum.at(pior, e[:, 1], cosv)
        liso = pior[viz] > 0.95                                # 18°
        arv_p = cKDTree(P)
        livre = np.ones(len(viz), bool)
        rho = float(np.clip(0.45 * self.R, 3.5, 9.0))
        rot_laco = np.full(len(self.marcados), -1)
        for _ in range(maximo):
            # semente: junto do maior trecho do contorno ainda sem superfície
            sem = rot_laco < 0
            if sem.sum() < max(3, 0.04 * len(sem)):
                break
            tr = _maior_trecho(sem)
            meio = V[self.marcados[(tr[0] + tr[1] // 2) % len(sem)]]
            cand = np.flatnonzero(livre & liso & (d_laco > beira) & (d_laco < beira + 0.6 * w))
            if len(cand) < 12:
                cand = np.flatnonzero(livre & (d_laco > 0.5 * beira))
            if len(cand) < 12:
                break
            s = cand[np.argmin(np.linalg.norm(P[cand] - meio, axis=1))]
            loc = np.asarray(arv_p.query_ball_point(P[s], rho), np.int64)
            loc = loc[livre[loc] & (d_laco[loc] > 0.5 * beira)]
            if len(loc) < 12:
                livre[s] = False
                continue
            a = N[loc].sum(0)
            a = a / max(np.linalg.norm(a), 1e-12)
            try:
                mod, sigma, fracao = _ajustar_fino(P[loc], N[loc], P[s], a)
                inl = loc
                for _ in range(3):
                    tol = float(np.clip(3.0 * sigma, 0.08, 0.5))
                    ok = livre & (np.abs(mod.dist(P)) < tol)
                    ok[ok] = np.einsum("ij,ij->i", _gradiente(mod, P[ok]), N[ok]) > 0.8
                    novo = np.flatnonzero(ok & (d_laco > 0.5 * beira))
                    if len(novo) < 12 or len(novo) <= 1.05 * len(inl):
                        inl = novo if len(novo) >= len(inl) else inl
                        break
                    inl = novo
                    am = inl if len(inl) <= 1500 else inl[np.random.default_rng(0).choice(len(inl), 1500, replace=False)]
                    a = N[am].sum(0)
                    a = a / max(np.linalg.norm(a), 1e-12)
                    c0 = P[s] - mod.dist(P[s][None])[0] * a
                    mod, sigma, fracao = _ajustar_fino(P[am], N[am], c0, a)
            except Exception:
                livre[s] = False
                continue
            tol = float(np.clip(3.0 * sigma, 0.08, 0.5))
            do_modelo = livre & (np.abs(mod.dist(P)) < tol)
            if do_modelo.sum() < 12:
                livre[s] = False
                continue
            livre &= ~do_modelo
            livre[loc] = False
            k = len(self.superficies)
            d_m = np.abs(mod.dist(pts))
            pega = (rot_laco < 0) & (d_m < max(tol, 0.35))
            rot_laco[pega] = k
            pc = pts[pega].mean(0) if pega.any() else P[s]
            pc = pc - mod.dist(pc[None])[0] * a
            n = _gradiente(mod, pc[None])[0]
            if n @ a < 0.5:
                n = a
            self.superficies.append((mod, n, float(sigma), float(fracao), int(do_modelo.sum())))
        if self.superficies:
            cont = np.bincount(rot_laco[rot_laco >= 0], minlength=len(self.superficies))
            self.principal = int(np.argmax(cont)) if cont.max() > 0 else 0

    def achar(self, arco, modelo_atual, n_atual):
        """A superfície vizinha em que um trecho do contorno (fora do modelo atual) está assentado."""
        k = len(arco)
        q = max(3, min(k // 4, 12))
        pontas = np.asarray(arco[:q] + arco[-q:] if k >= 2 * q else arco, np.int64)
        melhor = None
        for mod, n, sigma, _, _ in self.superficies:
            if mod is modelo_atual or sigma > 0.3:
                continue
            f = float(np.mean(np.abs(mod.dist(self.V[pontas])) < 0.5))
            if f >= 0.8 and (melhor is None or f > melhor[0]):
                melhor = (f, mod)
        if melhor is None:
            return None
        mod = melhor[1]
        meio = self.V[np.asarray(arco, np.int64)].mean(0)
        a = self.nvk[pontas[pontas < len(self.nvk)]].sum(0)
        a = a / max(np.linalg.norm(a), 1e-12)
        n = _gradiente(mod, (meio - mod.dist(meio[None])[0] * a)[None])[0]
        if n @ a < 0.5:
            n = a
        if abs(n @ n_atual) > 0.9:
            return None
        return mod, n


def _maior_trecho(marca):
    """(início, comprimento) do maior trecho seguido de True numa sequência circular."""
    n = len(marca)
    if marca.all():
        return 0, n
    ini = int(np.flatnonzero(~marca)[0])
    rodado = np.roll(marca, -ini)
    melhor, k = (0, 0), 0
    while k < n:
        if rodado[k]:
            j = k
            while j < n and rodado[j]:
                j += 1
            if j - k > melhor[1]:
                melhor = ((k + ini) % n, j - k)
            k = j
        else:
            k += 1
    return melhor


def _triangular_minimo(P):
    """Triangulação de área mínima de um contorno fechado no espaço (programação dinâmica; nenhum ponto novo).
    Devolve N-2 triângulos de índices do contorno, percorrendo cada lado ao contrário do contorno."""
    n = len(P)
    W = np.zeros((n, n))
    O = np.zeros((n, n), np.int32)
    for L in range(2, n):
        i = np.arange(0, n - L)
        k = i + L
        m = i[:, None] + np.arange(1, L)[None]                    # candidatos entre i e k
        a = P[m] - P[i][:, None]
        b = P[k][:, None] - P[i][:, None]
        area = 0.5 * np.linalg.norm(np.cross(a, b), axis=2)
        # triângulo achatado (três pontos quase em linha, comum num contorno reto) não pode entrar: teria área
        # nula, sumiria da malha e deixaria um buraco no lugar. Entra com um custo proibitivo.
        lado2 = np.maximum(np.maximum((a * a).sum(2), (b * b).sum(2)), ((a - b) ** 2).sum(2))
        area = area + 0.01 * lado2 + np.where(area < 2e-3 * lado2, 1e3 * lado2, 0.0)
        custo = W[i[:, None], m] + W[m, k[:, None]] + area
        j = np.argmin(custo, axis=1)
        W[i, k] = custo[np.arange(len(i)), j]
        O[i, k] = m[np.arange(len(i)), j]
    tri, pilha = [], [(0, n - 1)]
    while pilha:
        i, k = pilha.pop()
        if k - i < 2:
            continue
        m = int(O[i, k])
        tri.append((i, k, m))
        pilha.append((i, m))
        pilha.append((m, k))
    return np.array(tri, np.int64)


def _refinar(P, T, h, maximo=80000):
    """Divide ao meio os lados internos compridos de um remendo (sempre o maior lado dos dois triângulos que o
    dividem, para os triângulos não degenerarem) até nenhum passar de h. Os lados do contorno não são tocados.
    Devolve (pontos, triângulos)."""
    P = [np.asarray(P, float)]
    n_p = len(P[0])
    T = np.asarray(T, np.int64)
    for _ in range(200):
        Pt = np.vstack(P)
        k = len(T)
        i = np.concatenate([T[:, 0], T[:, 1], T[:, 2]])
        j = np.concatenate([T[:, 1], T[:, 2], T[:, 0]])
        ch = np.minimum(i, j) * (len(Pt) + 1) + np.maximum(i, j)
        u, inv, cont = np.unique(ch, return_inverse=True, return_counts=True)
        comp = np.linalg.norm(Pt[i] - Pt[j], axis=1)
        interno = cont[inv] == 2
        c3 = np.where(interno, comp, -1.0).reshape(3, k)          # lado q do triângulo t: c3[q, t]
        maior = np.argmax(c3, axis=0)                              # o maior lado interno de cada triângulo
        eh_maior = np.zeros(3 * k, bool)
        eh_maior[maior * k + np.arange(k)] = c3[maior, np.arange(k)] > 0
        # lado terminal: é o maior dos dois triângulos que o dividem
        votos = np.bincount(inv[eh_maior], minlength=len(u))
        comp_e = np.zeros(len(u))
        comp_e[inv] = comp
        # Um triângulo encostado num lado comprido do contorno (que não pode ser dividido) não tem como ficar com os
        # outros lados menores que a metade dele: o limite, para os lados desse triângulo, acompanha o lado do contorno.
        borda_t = np.where(interno, 0.0, comp).reshape(3, k).max(axis=0)
        h_t = np.maximum(h, 0.9 * borda_t)
        h_e = np.zeros(len(u))
        np.maximum.at(h_e, inv, np.tile(h_t, 3))
        dividir = (votos == 2) & (comp_e > h_e)
        if not dividir.any() or n_p + int(dividir.sum()) > maximo:
            break
        novo_de = np.full(len(u), -1, np.int64)
        ids = np.flatnonzero(dividir)
        novo_de[ids] = n_p + np.arange(len(ids))
        a, b = u[ids] // (len(Pt) + 1), u[ids] % (len(Pt) + 1)
        P.append(0.5 * (Pt[a] + Pt[b]))
        n_p += len(ids)
        # cada triângulo com o lado q dividido vira dois
        meia = np.flatnonzero(dividir[inv] & eh_maior)             # meias-arestas (q·k + t) dos lados divididos
        q, t = meia // k, meia % k
        va, vb, vc = T[t, q], T[t, (q + 1) % 3], T[t, (q + 2) % 3]
        vm = novo_de[inv[meia]]
        fica = np.ones(k, bool)
        fica[t] = False
        T = np.vstack([T[fica], np.c_[va, vm, vc], np.c_[vm, vb, vc]])
    return np.vstack(P), T


def _fechar_geral(est, laco, V0, F0):
    """Preenchimento geral de um contorno qualquer (vazio na ponta de uma palheta, entre duas faces de uma parede
    fina, em superfície de forma livre): triangula o contorno pela menor área, refina até os triângulos ficarem do
    tamanho dos vizinhos e assenta o remendo como a superfície de menor dobra que continua, com tangência, o que
    está em volta. Devolve dict(area, vertices) ou levanta ValueError."""
    laco = np.asarray(laco, np.int64)
    n = len(laco)
    if n > 900:
        raise ValueError("contorno com vértices demais para fechar de uma vez: feche em partes, pintando trechos")
    V = est["V"]
    Pl = V[laco]
    lados = np.linalg.norm(Pl - np.roll(Pl, -1, axis=0), axis=1)
    h = float(np.clip(1.25 * np.median(lados), 0.2, 6.0))
    tri = _triangular_minimo(Pl)
    Pn, T = _refinar(Pl, tri, h)
    n_novos = len(Pn) - n
    base = len(V)
    g = np.concatenate([laco, base + np.arange(n_novos)])         # índice local do remendo -> índice em est["V"]
    Fp = g[T]
    Vt = np.vstack([V, Pn[n:]])
    if n_novos:
        # assenta: a menor dobra, com as faixas de triângulos em volta paradas servindo de contexto
        Ft = np.vstack([np.asarray(F0, np.int64), Fp])
        sel = np.zeros(len(Ft), bool)
        sel[len(F0):] = True
        for _ in range(3):
            mt = Malha(Vt, Ft)
            if mt.validos is not None:
                break                                           # triângulo achatado: fica como está, a conferência abaixo decide
            try:
                # remendo novo: os vértices podem se acomodar em qualquer direção (num trecho que já existia, não)
                r = alisar(mt, sel, 3, so_normal=False)
            except ValueError:
                break
            Vt = r["malha"].V
        Fp = Ft[sel]
    T3 = Vt[Fp]
    a2 = np.linalg.norm(np.cross(T3[:, 1] - T3[:, 0], T3[:, 2] - T3[:, 0]), axis=1)
    if (a2 <= 1e-13).any():
        raise ValueError("o contorno tem trechos dobrados sobre si mesmos e o remendo não fechou direito")
    est["V"] = Vt
    est["F"].append(Fp)
    est["area"] += float(a2.sum() / 2)
    est["degraus"].append(0.0)
    return dict(area=float(a2.sum() / 2), vertices=int(n_novos))


def fechar_lacos(V, F, lacos, tocados=None):
    """Fecha laços de borda de uma malha (V, F) com remendos que seguem a superfície em volta.

    lacos: lista de arrays de vértices (na ordem das meias-arestas livres). tocados: máscara por vértice dos que
    pertencem ao trecho a fechar (None = o laço inteiro); com ela, um laço só em parte marcado é fechado só nesse
    trecho, por uma corda que segue a superfície.
    Devolve dict(V (com os vértices novos ao fim), F_remendo, F_trocados (triângulos que substituem os vizinhos
    que tiveram um lado dividido), trocados (máscara sobre F), infos)."""
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    n0 = len(V)
    # estrangulamentos: dois vértices do contorno, não vizinhos, praticamente no mesmo lugar (lasca de triângulo
    # quase sem área). O contorno não triangula assim; saem os triângulos em volta desses vértices e o contorno é
    # refeito.
    fora = np.zeros(len(F), bool)
    lacos = [np.asarray(l, np.int64) for l in lacos]
    marca = None if tocados is None else np.array(tocados, bool)
    for _ in range(3):
        aperto = _estrangulamentos(V, lacos, marca)
        if not len(aperto):
            break
        ruim = np.zeros(n0, bool)
        ruim[aperto] = True
        tira = ruim[F].any(axis=1) & ~fora
        if not tira.any():
            break
        do_laco = np.zeros(n0, bool)
        for l in lacos:
            do_laco[l] = True
        do_laco[F[tira].ravel()] = True
        if marca is not None:
            marca[F[tira].ravel()] = True
        fora |= tira
        sub = Malha(V, F[~fora])
        lacos = [l for l in remendo.lacos(sub.bordas()[0]) if do_laco[l].any() and (marca is None or marca[l].any())]
    # orelhas: triângulo preso por um lado só, com os outros dois no contorno a fechar
    for _ in range(3):
        sub = Malha(V, F[~fora])
        do_laco = np.zeros(n0, bool)
        for l in lacos:
            do_laco[l if marca is None else l[marca[l]]] = True
        orelha = orelhas(sub, do_laco)
        if not orelha.any():
            break
        fora[np.flatnonzero(~fora)[orelha]] = True
        do_laco[sub.F[orelha].ravel()] = True
        if marca is not None:
            marca[sub.F[orelha].ravel()] = True
        sub = Malha(V, F[~fora])
        lacos = [l for l in remendo.lacos(sub.bordas()[0]) if do_laco[l].any() and (marca is None or marca[l].any())]
    tocados = marca
    viva = np.flatnonzero(~fora)
    mk = Malha(V, F[viva])
    if mk.validos is not None:
        raise ValueError("recorte com triângulos degenerados")
    Fk = mk.F
    usados = np.zeros(n0, bool)
    usados[Fk.ravel()] = True
    ids_v = np.flatnonzero(usados)
    arv_v = cKDTree(V[usados])
    nvk = mk.normais_de_vertice(1)
    nv_bruta = mk.normais_de_vertice(0)
    pares = mk.arestas()[1]
    est = dict(V=V, extra=[], F=[], divs=[], area=0.0, degraus=[], avisos=[], paredes=0)
    infos = []
    tudo = np.ones(n0, bool)
    for l in lacos:
        l = np.asarray(l, np.int64)
        toc = tudo if tocados is None else np.asarray(tocados, bool)
        marcados = l[toc[l]] if tocados is not None else l
        info = dict(preenchido=False, aviso=None, area=0.0, degrau=None, vertices=int(len(l)), parcial=bool(len(marcados) < len(l)),
                    referencia=None, sigma=None, explicado=None)
        if len(marcados) < 3:
            info["aviso"] = "trecho curto demais para fechar"
            info["ignorado"] = True
            infos.append(info)
            continue
        achar = None
        try:
            viz = _Vizinhanca(est["V"], l, marcados, pares, nv_bruta, nvk, arv_v, ids_v)
            r = viz.superficies[viz.principal][:4] if viz.principal >= 0 else None
            if r is None:
                pc, pn, _ = ajuste.plano(V[marcados])
                if pn @ viz.a_laco < 0:
                    pn = -pn
                modelo, n_ref, tol = superficie.Plano(pc, pn), pn, 0.35
                info["referencia"] = "plano pelo contorno"
            else:
                modelo, n_ref, sigma, fracao = r
                tol = float(np.clip(3.5 * sigma, 0.25, 0.8))
                info.update(referencia=modelo.descricao(), sigma=sigma, explicado=fracao)
                achar = viz.achar
            R = viz.R
        except Exception as e:                                 # vizinhança sem condição de ajuste
            info["aviso"] = f"não consegui ajustar a superfície em volta ({type(e).__name__})"
            infos.append(info)
            continue
        nF, nA, nAv, nD, nP = len(est["F"]), est["area"], len(est["avisos"]), len(est["degraus"]), est["paredes"]
        V_antes, n_divs = est["V"], len(est["divs"])
        try:
            _remendar(est, l, toc, modelo, n_ref, max(tol, 0.35), arv_v, ids_v, nvk, None, R, achar=achar)
        except Exception as e:
            est["avisos"].append(f"um furo não pôde ser fechado ({type(e).__name__})")
        # Remendo que não assenta: o contorno fica longe demais da superfície achada (corte que atravessou uma parede
        # fina, ou que pegou várias formas de uma vez). Melhor deixar aberto e dizer do que entregar uma superfície
        # inventada.
        pior = max(est["degraus"][nD:], default=0.0)
        if len(est["F"]) > nF and pior > max(3.0, 0.2 * R):
            est["V"], est["area"], est["paredes"] = V_antes, nA, nP
            del est["F"][nF:], est["degraus"][nD:], est["divs"][n_divs:], est["avisos"][nAv:]
            est["avisos"].append("não achei uma superfície que continue a vizinhança deste corte, e ele ficou aberto: pinte uma região menor, "
                                 "de um lado só da peça, ou feche em partes")
            info["recusado"] = float(pior)
        sem_modelo = info.get("referencia") == "plano pelo contorno"
        if not info["parcial"] and (len(est["F"]) == nF or sem_modelo):
            # nenhuma superfície simples explica a vizinhança (ou nem havia vizinhança lisa): preenchimento geral
            if len(est["F"]) > nF:
                est["V"], est["area"], est["paredes"] = V_antes, nA, nP
                del est["F"][nF:], est["degraus"][nD:], est["divs"][n_divs:]
            try:
                _fechar_geral(est, l, V, Fk)
                del est["avisos"][nAv:]
                est["avisos"].append("fechado como superfície lisa entre as bordas, sem uma forma de referência (plano, cilindro…) que explique a vizinhança: confira a forma")
                info.pop("recusado", None)
                info.update(referencia="superfície lisa entre as bordas", sigma=None, explicado=None, geral=True)
            except ValueError as e:
                est["avisos"].append(str(e))
            except Exception as e:
                est["avisos"].append(f"um furo não pôde ser fechado ({type(e).__name__})")
        info["preenchido"] = len(est["F"]) > nF
        info["area"] = float(est["area"] - nA)
        info["degrau"] = float(max(est["degraus"][nD:])) if len(est["degraus"]) > nD else None
        info["arestas_vivas"] = int(est["paredes"] - nP)
        novos_avisos = [x.replace("alvo na borda da malha", "corte na borda da malha") for x in est["avisos"][nAv:]]
        if novos_avisos:
            info["aviso"] = "; ".join(sorted(set(novos_avisos)))
        infos.append(info)
    Fd = _dividir_arestas(Fk, est["divs"])
    Fd = np.asarray(Fd, np.int64)
    trocados = fora.copy()
    F_trocados = np.zeros((0, 3), np.int64)
    if len(Fd) != len(Fk) or (est["divs"] and not np.array_equal(Fd[:len(Fk)], Fk)):
        troc = (Fd[:len(Fk)] != Fk).any(axis=1)
        trocados[viva[troc]] = True
        F_trocados = np.vstack([Fd[:len(Fk)][troc], Fd[len(Fk):]])
    F_rem = np.vstack(est["F"]).astype(np.int64) if est["F"] else np.zeros((0, 3), np.int64)
    return dict(V=est["V"], F_remendo=F_rem, F_trocados=F_trocados, trocados=trocados, infos=infos)


def _estrangulamentos(V, lacos, marca=None):
    """Vértices de contorno que quase encostam em outro vértice não vizinho do mesmo contorno (só no trecho
    marcado para fechar, quando há marca)."""
    out = []
    for l in lacos:
        n = len(l)
        if n < 6:
            continue
        P = V[l]
        lados = np.linalg.norm(P - np.roll(P, -1, axis=0), axis=1)
        eps = max(1e-6, 0.03 * float(np.median(lados)))
        pares = cKDTree(P).query_pairs(eps, output_type="ndarray")
        if not len(pares):
            continue
        gap = np.abs(pares[:, 0] - pares[:, 1])
        gap = np.minimum(gap, n - gap)
        pares = pares[gap >= 2]
        if marca is not None and len(pares):
            pares = pares[marca[l[pares[:, 0]]] & marca[l[pares[:, 1]]]]
        if len(pares):
            out.append(l[np.unique(pares)])
    return np.unique(np.concatenate(out)) if out else np.zeros(0, np.int64)


# ---------------------------------------------------------------------------
# apagar a seleção (com ou sem preenchimento)
# ---------------------------------------------------------------------------

def _sem_pontas(F, sel):
    """Acerta o contorno de uma seleção: fecha entalhes (triângulo de fora com os três vértices tocando a seleção)
    e tira pontas (triângulo de dentro preso por um lado só)."""
    sel = np.array(sel, bool)
    n = int(F.max()) + 1 if len(F) else 0
    for _ in range(2):
        v = np.zeros(n, bool)
        v[F[sel].ravel()] = True
        sel = sel | v[F].all(axis=1)
        idx = np.flatnonzero(sel)
        if len(idx) < 4:
            break
        Fs = F[idx]
        i = np.concatenate([Fs[:, 0], Fs[:, 1], Fs[:, 2]]).astype(np.int64)
        j = np.concatenate([Fs[:, 1], Fs[:, 2], Fs[:, 0]]).astype(np.int64)
        ch = np.minimum(i, j) * n + np.maximum(i, j)
        _, inv, cont = np.unique(ch, return_inverse=True, return_counts=True)
        dentro = (cont[inv] >= 2).reshape(3, -1).sum(0)       # lados de cada triângulo divididos com outro da seleção
        ponta = dentro <= 1
        if not ponta.any() or ponta.all():
            break
        sel[idx[ponta]] = False
    return sel


def apagar(m, sel, preencher=True, soltos=True):
    """Apaga os triângulos selecionados. Com `soltos`, o que ficar pendurado sem ligação com o resto da peça (o
    corpo de um alvo de que só o pé foi pintado, por exemplo) sai junto. Com `preencher`, os furos abertos pelo
    corte são fechados seguindo a superfície em volta.
    Devolve dict(malha, origem, novos=máscara dos triângulos de remendo, info)."""
    sel = np.asarray(sel, bool)
    f_sel = np.flatnonzero(sel)
    if not len(f_sel):
        raise ValueError("Nada selecionado. Pinte com o pincel o que deve sair.")
    lo, hi = m.C[f_sel].min(0).astype(float), m.C[f_sel].max(0).astype(float)
    g = m.grade()
    info = dict(apagados=int(len(f_sel)), pendurados=0, furos=0, fechados=0, area=0.0, avisos=[], referencias=[], degrau=None,
                arestas_vivas=0)
    limite = float(np.clip(40.0 * m.A[f_sel].sum(), 300.0, 6000.0))
    # O recorte local cresce até caber inteiro o que ficou pendurado (um alvo tem até 60 mm de altura): um pedaço
    # pequeno que ainda toca a orla do recorte pode ser só a parte de baixo de algo que continua lá fora.
    for R in (80.0, 200.0):
        R = float(max(R, min(0.5 * np.linalg.norm(hi - lo), 60.0)))
        idx = np.sort(g.caixa(lo - R, hi + R))
        rec = _Recorte(m, idx)
        sel_l = sel[idx]
        Cl = m.C[idx].astype(float)
        orla = ((Cl < lo - (R - 4.0)) | (Cl > hi + (R - 4.0))).any(axis=1)
        remover = _sem_pontas(rec.F, sel_l) & ~orla
        if not soltos:
            break
        fica = ~remover
        sub = Malha(rec.V, rec.F[fica])
        rot, n = sub.componentes()
        if n <= 1:
            break
        area = np.bincount(rot, weights=sub.A, minlength=n)
        na_orla = np.zeros(n, bool)
        na_orla[np.unique(rot[orla[fica]])] = True
        maior = int(np.argmax(area))
        v_corte = np.zeros(len(rec.V), bool)
        v_corte[rec.F[remover].ravel()] = True
        do_corte = np.zeros(n, bool)
        do_corte[np.unique(rot[v_corte[sub.F].any(axis=1)])] = True
        duvida = na_orla & (area < limite) & do_corte
        duvida[maior] = False
        if duvida.any() and R < 199.0:
            continue                                            # recorte maior, para saber se está preso ou pendurado
        preso = na_orla.copy()
        preso[maior] = True
        # só cai o que o corte soltou (encostava no que foi apagado); outros pedaços soltos por perto não são tocados
        v_corte = np.zeros(len(rec.V), bool)
        v_corte[rec.F[remover].ravel()] = True
        do_corte = np.zeros(n, bool)
        do_corte[np.unique(rot[v_corte[sub.F].any(axis=1)])] = True
        cai = ~preso & (area < limite) & do_corte
        # pedaços soltos pequenos logo junto do corte (o resto do corpo de um alvo que o escaneamento partiu)
        outros = np.flatnonzero(~preso & (area < limite) & ~do_corte)
        if len(outros) and v_corte.any():
            arv = cKDTree(rec.V[v_corte])
            for k in outros:
                vk = np.unique(sub.F[rot == k])
                d, _ = arv.query(rec.V[vk[::max(1, len(vk) // 400)]])
                if d.min() < 50.0:
                    cai[k] = True
                    info["soltos_perto"] = info.get("soltos_perto", 0) + 1
        if cai.any():
            pend = np.zeros(len(rec.F), bool)
            pend[np.flatnonzero(fica)[cai[rot]]] = True
            remover |= pend
            info["pendurados"] = int(pend.sum())
        if (~preso & ~cai & do_corte).any():
            info["avisos"].append("um pedaço grande ficou sem ligação com o resto da peça e foi mantido")
        break
    manter = np.ones(m.n_faces, bool)
    manter[idx[remover]] = False
    info["apagados"] = int(remover.sum()) - info["pendurados"]
    V_novos = np.zeros((0, 3))
    F_novos = np.zeros((0, 3), np.int64)
    n_troc = 0
    if preencher:
        tocados = np.zeros(len(rec.V), bool)
        tocados[rec.F[remover].ravel()] = True
        fica = np.flatnonzero(~remover)
        Fk = rec.F[fica]
        usados = np.zeros(len(rec.V), bool)
        usados[Fk.ravel()] = True
        tocados &= usados
        mk = Malha(rec.V, Fk)
        lacos = [l for l in remendo.lacos(mk.bordas()[0]) if tocados[l].any()]
        if lacos:
            r = fechar_lacos(rec.V, Fk, lacos, tocados=tocados)
            manter[idx[fica[r["trocados"]]]] = False
            n_loc = len(rec.V)
            g_de_l = np.concatenate([rec.vu, m.n_vertices + np.arange(len(r["V"]) - n_loc)])
            V_novos = r["V"][n_loc:]
            F_novos = g_de_l[np.vstack([r["F_trocados"], r["F_remendo"]])]
            n_troc = len(r["F_trocados"])
            info["furos"] = sum(1 for i in r["infos"] if not i.get("ignorado"))
            for i in r["infos"]:
                if i.get("ignorado"):
                    continue
                info["fechados"] += int(i["preenchido"])
                info["area"] += i["area"]
                info["arestas_vivas"] += int(i.get("arestas_vivas") or 0)
                if i.get("referencia"):
                    info["referencias"].append(i["referencia"])
                if i.get("aviso"):
                    info["avisos"].append(i["aviso"])
                if i.get("degrau") is not None:
                    info["degrau"] = max(info["degrau"] or 0.0, i["degrau"])
            if info["fechados"] < info["furos"]:
                info["avisos"].append(f"{info['furos'] - info['fechados']} contorno(s) do corte ficaram abertos")
    nova, origem = m.editar(manter, V_novos, F_novos)
    novos = (origem < 0) & ((-1 - origem) >= n_troc)
    info["avisos"] = sorted(set(info["avisos"]))
    return dict(malha=nova, origem=origem, novos=novos, info=info)


# ---------------------------------------------------------------------------
# furos
# ---------------------------------------------------------------------------

def furos(m):
    """Contornos abertos da malha, do menor para o maior. Cada um: dict(v=vértices na ordem, perimetro, diametro,
    centro, normal). O resultado fica guardado na malha."""
    if "furos" in m._cache:
        return m._cache["furos"]
    b, _ = m.bordas()
    out = []
    for l in remendo.lacos(b):
        P = m.V[l]
        per = float(np.linalg.norm(P - np.roll(P, -1, axis=0), axis=1).sum())
        c = P.mean(0)
        out.append(dict(v=l, perimetro=per, diametro=float(2.0 * np.linalg.norm(P - c, axis=1).max()), centro=c,
                        normal=_normal_de_newell(P)))
    out.sort(key=lambda f: f["perimetro"])
    if m.n_faces > 2_000_000:                                    # as tabelas de arestas da malha inteira não ficam guardadas
        for ch in ("arestas", "viz", "gf"):
            m._cache.pop(ch, None)
    m._cache["furos"] = out
    return out


def preencher_furos(m, lacos, sel_v=None, log=lambda s: None):
    """Fecha os contornos dados (listas de vértices globais). sel_v: máscara de vértices; com ela, um contorno só em
    parte marcado é fechado só no trecho marcado. Devolve dict(malha, origem, novos, infos)."""
    g = m.grade()
    manter = np.ones(m.n_faces, bool)
    V_partes, F_troc, F_rem = [], [], []
    n_extra = 0
    infos = []
    total = len(lacos)
    for feitos, l in enumerate(lacos, 1):
        l = np.asarray(l, np.int64)
        P = m.V[l]
        if sel_v is not None and not sel_v[l].all():
            P = P[sel_v[l]]
        lo, hi = P.min(0), P.max(0)
        R = float(0.5 * np.linalg.norm(hi - lo))
        info = None
        for folga in (1.0, 3.0):
            margem = (float(np.clip(1.0 * R, 6.0, 25.0)) + 6.0) * folga + 2.0 * g.cel
            if sel_v is not None:
                margem = max(margem, 40.0)                     # o resto do contorno tem de aparecer comprido no recorte
            idx = np.sort(g.caixa(lo - margem, hi + margem))
            idx = idx[manter[idx]]
            if len(idx) < 3:
                continue
            rec = _Recorte(m, idx)
            ll = rec.local(l)
            toc = None
            if sel_v is not None:
                # o contorno pode não caber inteiro no recorte: só o trecho marcado precisa estar nele
                marc = l[sel_v[l]]
                lm = rec.local(marc)
                if (lm < 0).any():
                    continue
                toc = np.zeros(len(rec.V), bool)
                toc[lm] = True
                sub = Malha(rec.V, rec.F)
                cand = [x for x in remendo.lacos(sub.bordas()[0]) if toc[x].any()]
            else:
                if (ll < 0).any():
                    continue
                cand = [ll]
            try:
                r = fechar_lacos(rec.V, rec.F, cand, tocados=toc)
            except ValueError as e:
                info = dict(preenchido=False, aviso=str(e), area=0.0, degrau=None, vertices=int(len(l)))
                break
            validas = [i for i in r["infos"] if not i.get("ignorado")]
            info = dict(validas[0]) if validas else dict(preenchido=False, aviso="trecho curto demais para fechar", area=0.0, degrau=None, vertices=int(len(l)))
            info["preenchido"] = any(i["preenchido"] for i in validas)
            info["area"] = float(sum(i["area"] for i in validas))
            if len(r["F_remendo"]) or r["trocados"].any():
                manter[idx[r["trocados"]]] = False
                n_loc = len(rec.V)
                g_de_l = np.concatenate([rec.vu, m.n_vertices + n_extra + np.arange(len(r["V"]) - n_loc)])
                V_partes.append(r["V"][n_loc:])
                n_extra += len(r["V"]) - n_loc
                if len(r["F_trocados"]):
                    F_troc.append(g_de_l[r["F_trocados"]])
                F_rem.append(g_de_l[r["F_remendo"]])
            break
        if info is None:
            info = dict(preenchido=False, aviso="não consegui isolar a vizinhança do contorno", area=0.0, degrau=None, vertices=int(len(l)))
        info["perimetro"] = float(np.linalg.norm(m.V[l] - np.roll(m.V[l], -1, axis=0), axis=1).sum())
        infos.append(info)
        if total > 4 and (feitos % max(1, total // 20) == 0 or feitos == total):
            log(f"Fechando furos… {int(100 * feitos / total)}%")
    V_novos = np.vstack(V_partes) if V_partes else np.zeros((0, 3))
    n_troc = sum(len(x) for x in F_troc)
    F_novos = np.vstack(F_troc + F_rem) if (F_troc or F_rem) else np.zeros((0, 3), np.int64)
    nova, origem = m.editar(manter, V_novos, F_novos)
    novos = (origem < 0) & ((-1 - origem) >= n_troc)
    return dict(malha=nova, origem=origem, novos=novos, infos=infos)


# ---------------------------------------------------------------------------
# alisar
# ---------------------------------------------------------------------------

def alisar(m, sel, forca=2, so_normal=True):
    """Alisa a região selecionada sem mexer no contorno dela nem na borda da malha. forca: 1 (tira o ruído),
    2 (tira ondulações) ou 3 (refaz a região como continuação lisa do que está em volta).
    Devolve dict(malha (mesmos triângulos), info)."""
    from scipy.sparse.linalg import splu
    sel = np.asarray(sel, bool)
    if not sel.any():
        raise ValueError("Nada selecionado. Pinte com o pincel a região a alisar.")
    # contexto: duas faixas de triângulos em volta da seleção entram na conta, paradas, para a emenda sair lisa
    ctx = crescer(m, sel, 2)
    f = np.flatnonzero(ctx)
    vs, inv = np.unique(m.F[f], return_inverse=True)
    Fl = inv.reshape(-1, 3)
    n = len(vs)
    X0 = m.V[vs]
    # vértice livre: todos os triângulos dele estão na seleção, e ele não está na borda da malha
    total = np.bincount(m.F.ravel(), minlength=m.n_vertices)[vs]
    na_sel = np.bincount(np.searchsorted(vs, m.F[sel].ravel()), minlength=n)
    livre = na_sel == total
    i = np.concatenate([Fl[:, 0], Fl[:, 1], Fl[:, 2]])
    j = np.concatenate([Fl[:, 1], Fl[:, 2], Fl[:, 0]])
    o = np.concatenate([Fl[:, 2], Fl[:, 0], Fl[:, 1]])
    ch = np.minimum(i, j).astype(np.int64) * n + np.maximum(i, j)
    u, cont = np.unique(ch, return_counts=True)
    borda = np.zeros(n, bool)
    borda[(u // n)[cont == 1]] = True
    borda[(u % n)[cont == 1]] = True
    em_todos = np.bincount(Fl.ravel(), minlength=n) == total       # vértice com a vizinhança inteira no recorte
    livre &= em_todos & ~borda
    if not livre.any():
        raise ValueError("A região pintada é pequena demais para alisar: pinte uma área maior.")
    # laplaciano de cotangentes (segue a forma, não o tamanho dos triângulos), com as linhas normalizadas
    a, b = X0[i] - X0[o], X0[j] - X0[o]
    cot = np.einsum("ij,ij->i", a, b) / np.maximum(np.linalg.norm(np.cross(a, b), axis=1), 1e-12)
    w = np.clip(cot, 0.05, 20.0)
    W = sparse.coo_matrix((np.r_[w, w], (np.r_[i, j], np.r_[j, i])), shape=(n, n)).tocsr()
    if not so_normal:
        # remendo novo: nos vértices dele o peso é igual para todos os vizinhos, o que os espalha por igual (triângulos
        # regulares, nenhum achatado); nos vértices do contorno e da vizinhança continua o peso que segue a forma
        U = sparse.coo_matrix((np.ones(2 * len(i)), (np.r_[i, j], np.r_[j, i])), shape=(n, n)).tocsr()
        U.data[:] = 1.0
        W = sparse.diags(livre.astype(float)) @ U + sparse.diags((~livre).astype(float)) @ W
    grau = np.asarray(W.sum(1)).ravel()
    L = sparse.identity(n, format="csr") - sparse.diags(1.0 / np.maximum(grau, 1e-12)) @ W
    # só as linhas de quem tem a vizinhança inteira no recorte valem
    L = sparse.diags(em_todos.astype(float)) @ L
    B = (L.T @ L).tocsr()                                           # energia de dobra
    li = np.flatnonzero(livre)
    fx = np.flatnonzero(~livre)
    if int(forca) >= 3:
        # a superfície de menor dobra que continua o que está em volta
        A = (B[li][:, li] + 1e-9 * sparse.identity(len(li))).tocsc()
        rhs = -(B[li][:, fx] @ X0[fx])
    else:
        t = 5.0 if int(forca) <= 1 else 1000.0
        A = (sparse.identity(len(li), format="csc") + t * B[li][:, li]).tocsc()
        rhs = X0[li] - t * (B[li][:, fx] @ X0[fx])
    X = X0.copy()
    X[li] = splu(A).solve(rhs)
    # só o deslocamento ao longo da normal vale: os vértices não escorregam pela superfície (o que deformaria os
    # triângulos sem alisar nada)
    if so_normal:
        nv = np.zeros((n, 3))
        cr = np.cross(X0[Fl[:, 1]] - X0[Fl[:, 0]], X0[Fl[:, 2]] - X0[Fl[:, 0]])
        for k in range(3):
            np.add.at(nv, Fl[:, k], cr)
        nv /= np.maximum(np.linalg.norm(nv, axis=1), 1e-12)[:, None]
        X = X0 + np.einsum("ij,ij->i", X - X0, nv)[:, None] * nv
    desloc = np.linalg.norm(X - X0, axis=1)
    nova = m.mover(vs[li], X[li])
    return dict(malha=nova, info=dict(vertices=int(len(li)), deslocamento_max=float(desloc.max()), deslocamento_medio=float(desloc[li].mean())))


# ---------------------------------------------------------------------------
# diagnóstico e reparo automático
# ---------------------------------------------------------------------------

def _invertidos(m):
    """Pares de triângulos vizinhos com sentidos de giro opostos (a aresta comum percorrida no mesmo sentido).
    Devolve (pares, máscara dos pares inconsistentes)."""
    p, a = m.vizinhos_de_face()
    if not len(p):
        return p, np.zeros(0, bool)
    fe, _, _ = m.arestas()
    F = m.F

    def sentido(f):
        k = np.argmax(fe[f] == a[:, None], axis=1)
        return F[f, k] < F[f, (k + 1) % 3]
    return p, sentido(p[:, 0]) == sentido(p[:, 1])


def diagnostico(m):
    """O que há para reparar na malha."""
    _, _, cont = m.arestas()
    rot, n = m.componentes()
    area = np.bincount(rot, weights=m.A, minlength=n)
    pequenos = area < 0.05 * area.max()
    p, inc = _invertidos(m)
    # triângulos muito finos: altura menor que 2% do maior lado
    finos = 0
    for i in range(0, m.n_faces, 1_000_000):
        f = m.F[i:i + 1_000_000]
        a, b, c = m.V[f[:, 0]], m.V[f[:, 1]], m.V[f[:, 2]]
        lado = np.maximum(np.maximum(np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1)), np.linalg.norm(a - c, axis=1))
        finos += int((2.0 * m.A[i:i + 1_000_000] / np.maximum(lado, 1e-12) < 0.02 * lado).sum())
    d = dict(triangulos=int(m.n_faces), vertices=int(m.n_vertices), area=float(m.area),
             nao_variedade=int((cont > 2).sum()), arestas_livres=int((cont == 1).sum()),
             pedacos=int(n), soltos=int(pequenos.sum()), soltos_triangulos=int(np.bincount(rot, minlength=n)[pequenos].sum()),
             invertidos=int(inc.sum()), finos=finos)
    lac = furos(m)
    d["furos"] = len(lac)
    d["furos_ate_10"] = sum(1 for f in lac if f["diametro"] <= 10.0)
    d["maior_contorno"] = float(lac[-1]["perimetro"]) if lac else 0.0
    d["fechada"] = not lac
    return d


def _orientar(m):
    """Vira os triângulos que estão ao contrário dos vizinhos (em cada pedaço, a minoria acompanha a maioria).
    Devolve (malha, nº de triângulos virados)."""
    p, inc = _invertidos(m)
    if not inc.any():
        return m, 0
    M = m.n_faces
    a = np.concatenate([p[~inc, 0], p[~inc, 0] + M, p[inc, 0], p[inc, 0] + M]).astype(np.int64)
    b = np.concatenate([p[~inc, 1], p[~inc, 1] + M, p[inc, 1] + M, p[inc, 1]]).astype(np.int64)
    g = sparse.coo_matrix((np.ones(len(a), np.int8), (a, b)), shape=(2 * M, 2 * M)).tocsr()
    _, rot = csgraph.connected_components(g, directed=False)
    r0, r1 = rot[:M], rot[M:]
    area = np.bincount(r0, weights=m.A, minlength=int(rot.max()) + 1)
    virar = (r0 != r1) & (area[r0] < area[r1])
    if not virar.any():
        return m, 0
    F = m.F.copy()
    F[virar] = F[virar][:, ::-1]
    N = m.N.copy()
    N[virar] *= -1
    return Malha._montada(m.V, F, m.A, N, m.C, nome=m.nome), int(virar.sum())


def _compor(o1, o2):
    """Origem composta de duas edições seguidas (triângulo novo em qualquer uma delas: -1)."""
    return np.where(o2 >= 0, o1[np.maximum(o2, 0)], -1)


def reparar(m, nao_variedade=True, soltos=True, orientar=True, furos_ate=None, log=lambda s: None):
    """Reparo automático. Devolve dict(malha, origem, novos, info)."""
    origem = np.arange(m.n_faces, dtype=np.int64)
    novos = np.zeros(m.n_faces, bool)
    info = dict(nao_variedade=0, soltos=0, soltos_triangulos=0, virados=0, furos_fechados=0, furos_abertos=0, avisos=[])
    atual = m
    if nao_variedade:
        log("Procurando arestas com três ou mais triângulos…")
        fe, _, cont = atual.arestas()
        ruim = (cont[fe] > 2).any(axis=1)
        if ruim.any():
            # sai a lasca: de cada aresta ruim ficam os triângulos do pedaço maior
            info["nao_variedade"] = int((cont > 2).sum())
            rot, n = atual.componentes()
            area = np.bincount(rot, weights=atual.A, minlength=n)
            tira = ruim & (area[rot] < 0.5 * area.max())
            if not tira.any():
                tira = ruim
            atual, o = atual.editar(~tira)
            origem, novos = _compor(origem, o), novos[np.maximum(o, 0)] & (o >= 0)
    if soltos:
        log("Procurando pedaços soltos…")
        rot, n = atual.componentes()
        if n > 1:
            area = np.bincount(rot, weights=atual.A, minlength=n)
            peq = area < 0.05 * area.max()
            if peq.any():
                tira = peq[rot]
                info["soltos"] = int(peq.sum())
                info["soltos_triangulos"] = int(tira.sum())
                atual, o = atual.editar(~tira)
                origem, novos = _compor(origem, o), novos[np.maximum(o, 0)] & (o >= 0)
    if orientar:
        log("Conferindo o sentido dos triângulos…")
        atual, k = _orientar(atual)
        info["virados"] = k
    if furos_ate:
        log("Procurando furos…")
        lac = [f for f in furos(atual) if f["diametro"] <= float(furos_ate)]
        if lac:
            r = preencher_furos(atual, [f["v"] for f in lac], log=log)
            info["furos_fechados"] = sum(1 for i in r["infos"] if i["preenchido"])
            info["furos_abertos"] = len(lac) - info["furos_fechados"]
            atual = r["malha"]
            origem = _compor(origem, r["origem"])
            novos = (novos[np.maximum(r["origem"], 0)] & (r["origem"] >= 0)) | r["novos"]
    return dict(malha=atual, origem=origem, novos=novos, info=info)
