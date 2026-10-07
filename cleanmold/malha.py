"""Malha de triângulos: leitura, gravação, vizinhança, bordas e amostragem.

Tudo em milímetros. A malha é um par (V, F): vértices N×3 e triângulos M×3 (índices de V).

A malha escaneada inteira ocupa pouco: vértices em 32 bits (como no arquivo STL), triângulos em 32 bits e a área
de cada triângulo. Normais e centros são calculados na hora, só para os triângulos pedidos (`normais`, `centros`).
As tabelas de arestas e de vizinhos (`arestas`, `grafo_faces`…) existem para os recortes pequenos em volta de cada
alvo; a malha inteira nunca passa por elas."""
import os
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

FORMATOS = (".stl", ".ply", ".obj", ".off")
_BLOCO = 1_000_000


class Malha:
    def __init__(self, V, F, nome=""):
        V = np.asarray(V)
        self.V = np.ascontiguousarray(V, dtype=np.float32 if V.dtype == np.float32 else np.float64)
        F = np.asarray(F).reshape(-1, 3)
        if len(self.V) >= 2**31 - 1:
            raise ValueError("Malha grande demais (mais de 2 bilhões de vértices).")
        F = np.ascontiguousarray(F, dtype=np.int32)
        m = len(F)
        A = np.empty(m, self.V.dtype)
        ok = np.empty(m, bool)
        soma = np.zeros(3)
        # em blocos: a malha inteira de uma vez pediria vários vetores temporários do tamanho dela
        for i in range(0, m, _BLOCO):
            f = F[i:i + _BLOCO]
            a = self.V[f[:, 0]].astype(np.float64)
            cr = np.cross(self.V[f[:, 1]] - a, self.V[f[:, 2]] - a)
            soma += cr.sum(axis=0)
            a2 = np.linalg.norm(cr, axis=1)
            ok[i:i + _BLOCO] = (a2 > 1e-14) & (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
            A[i:i + _BLOCO] = a2 / 2
        if not ok.all():
            F, A = F[ok], A[ok]
        self.F = np.ascontiguousarray(F)
        self.A = A                           # área de cada triângulo
        self.area_vetor = soma / 2           # soma das normais × área: zero numa malha fechada
        self.validos = None if ok.all() else ok   # triângulos de F (como veio) que ficaram; None = todos
        self.nome = nome
        self._cache = {}

    # ---- números gerais
    @property
    def n_faces(self):
        return len(self.F)

    @property
    def n_vertices(self):
        return len(self.V)

    @property
    def area(self):
        if "area" not in self._cache:
            self._cache["area"] = float(self.A.sum(dtype=np.float64))
        return self._cache["area"]

    def frente(self):
        """De que lado a malha foi escaneada: a direção média das normais, ou None se a malha dá a volta na peça
        (numa superfície fechada as normais se anulam; num escaneamento de um lado só, sobra uma direção)."""
        k = float(np.linalg.norm(self.area_vetor))
        return self.area_vetor / k if k > 0.2 * max(self.area, 1e-12) else None

    def caixa(self):
        if "caixa" not in self._cache:
            self._cache["caixa"] = (self.V.min(0).astype(np.float64), self.V.max(0).astype(np.float64))
        return self._cache["caixa"]

    # ---- por triângulo, só para os pedidos (idx: índices ou None = todos)
    def cantos(self, idx=None):
        """Os três vértices de cada triângulo pedido: K×3×3, em 64 bits."""
        f = self.F if idx is None else self.F[idx]
        return self.V[f].astype(np.float64)

    def centros(self, idx=None):
        return self.cantos(idx).mean(axis=1)

    def normais(self, idx=None):
        T = self.cantos(idx)
        cr = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        return cr / np.maximum(np.linalg.norm(cr, axis=1), 1e-300)[:, None]

    @property
    def N(self):
        """Normal de todos os triângulos (para os recortes pequenos; a malha inteira usa `normais(idx)`)."""
        if "N" not in self._cache:
            self._cache["N"] = self.normais()
        return self._cache["N"]

    @property
    def C(self):
        """Centro de todos os triângulos (para os recortes pequenos; a malha inteira usa `centros(idx)`)."""
        if "C" not in self._cache:
            self._cache["C"] = self.centros()
        return self._cache["C"]

    # ---- arestas (recortes pequenos)
    def arestas(self):
        """(meia_aresta -> id da aresta, pares de vértices por aresta, nº de triângulos por aresta)."""
        if "arestas" not in self._cache:
            F = self.F
            n = self.n_vertices + 1
            chave = np.empty(3 * len(F), np.int64)                # arestas 0→1 de todos, depois 1→2, depois 2→0
            for k in range(3):
                i, j = F[:, k], F[:, (k + 1) % 3]
                chave[k * len(F):(k + 1) * len(F)] = np.minimum(i, j).astype(np.int64) * n + np.maximum(i, j)
            u, inv, cont = np.unique(chave, return_inverse=True, return_counts=True)
            del chave
            pares = np.empty((len(u), 2), np.int32)
            pares[:, 0] = u // n
            pares[:, 1] = u % n
            self._cache["arestas"] = (np.ascontiguousarray(inv.astype(np.int32).reshape(3, -1).T), pares, cont.astype(np.int32))
        return self._cache["arestas"]

    def bordas(self):
        """Meias-arestas livres, orientadas como no triângulo: N×2 (de, para) e o triângulo de cada uma."""
        if "bordas" not in self._cache:
            fe, _, cont = self.arestas()
            livre = cont[fe] == 1                                # M×3
            f, k = np.nonzero(livre)
            de = self.F[f, k]
            para = self.F[f, (k + 1) % 3]
            self._cache["bordas"] = (np.c_[de, para], f)
        return self._cache["bordas"]

    def vizinhos_de_face(self):
        """Pares de triângulos que dividem uma aresta (só arestas com exatamente 2 triângulos): N×2 e a aresta."""
        if "viz" not in self._cache:
            fe, _, cont = self.arestas()
            m = self.n_faces
            aresta = fe.T.ravel()                                # mesma ordem da tabela de arestas
            ordem = np.argsort(aresta, kind="stable")
            a = aresta[ordem]
            dois = cont[a] == 2
            f = (ordem[dois] % m).astype(np.int32)               # a meia-aresta k·m + t pertence ao triângulo t
            self._cache["viz"] = (f.reshape(-1, 2), a[dois][::2])
        return self._cache["viz"]

    def grafo_faces(self):
        if "gf" not in self._cache:
            p, _ = self.vizinhos_de_face()
            m = self.n_faces
            g = sparse.coo_matrix((np.ones(len(p), np.int8), (p[:, 0], p[:, 1])), shape=(m, m)).tocsr()
            self._cache["gf"] = g + g.T
        return self._cache["gf"]

    def componentes(self):
        """Rótulo do pedaço ligado de cada triângulo (ligação por aresta) e o nº de pedaços."""
        if "comp" not in self._cache:
            n, rot = csgraph.connected_components(self.grafo_faces(), directed=False)
            self._cache["comp"] = (rot, n)
        return self._cache["comp"]

    # ---- pedaços da malha inteira, sem tabela de arestas
    def pedacos(self, bloco=4_000_000):
        """Rótulo do pedaço de cada VÉRTICE (ligação por triângulo). O rótulo é o menor índice de vértice do pedaço.

        Feito aos poucos: cada bloco de triângulos junta os pedaços que ele liga. A memória pedida é a de um bloco
        mais umas poucas listas do tamanho dos vértices, não a de uma tabela de arestas da malha inteira."""
        if "pedacos" not in self._cache:
            nv = self.n_vertices
            L = np.arange(nv, dtype=np.int32)
            for i in range(0, self.n_faces, bloco):
                f = L[self.F[i:i + bloco]]                       # os triângulos do bloco, já com os rótulos de agora
                g = sparse.coo_matrix((np.ones(2 * len(f), np.int8), (np.r_[f[:, 0], f[:, 1]], np.r_[f[:, 1], f[:, 2]])),
                                      shape=(nv, nv)).tocsr()
                del f
                n, rot = csgraph.connected_components(g, directed=False)
                del g
                raiz = np.empty(n, np.int32)
                raiz[rot[::-1]] = np.arange(nv - 1, -1, -1, dtype=np.int32)     # fica o menor índice de cada grupo
                troca = raiz[rot]
                del raiz, rot
                for j in range(0, nv, 4 * _BLOCO):
                    L[j:j + 4 * _BLOCO] = troca[L[j:j + 4 * _BLOCO]]
                del troca
            self._cache["pedacos"] = L
        return self._cache["pedacos"]

    # ---- normais de vértice e amostragem
    def normais_de_vertice(self, suavizar=0):
        """Normal de cada vértice (soma das normais dos triângulos em volta, pesada pela área), alisada `suavizar`
        vezes com os vizinhos. Calculada por acumulação direta, sem montar o grafo dos vértices."""
        ch = ("nv", suavizar)
        if ch not in self._cache:
            nv, nf, F = self.n_vertices, self.n_faces, self.F
            # Somar por vértice custa (triângulos do bloco + vértices da malha): poucos blocos grandes. O bloco
            # acompanha o tamanho da malha, e com ele a memória de passagem (uns 7 bytes por triângulo da malha).
            bloco = max(_BLOCO, nf // 4 + 1)
            n = np.zeros((nv, 3), np.float64)
            grau = np.zeros(nv, np.int32)                        # nº de triângulos em cada vértice
            for i in range(0, nf, bloco):
                fb = F[i:i + bloco]
                cr = np.empty((len(fb), 3), np.float32)          # normal × área
                for j in range(0, len(fb), _BLOCO):
                    f = fb[j:j + _BLOCO]
                    a = self.V[f[:, 0]].astype(np.float64)
                    cr[j:j + _BLOCO] = np.cross(self.V[f[:, 1]] - a, self.V[f[:, 2]] - a) * 0.5
                for k in range(3):
                    grau += np.bincount(fb[:, k], minlength=nv).astype(np.int32)
                    for e in range(3):
                        n[:, e] += np.bincount(fb[:, k], weights=cr[:, e], minlength=nv)
                del cr
            for _ in range(suavizar):
                # n + (soma das normais dos vizinhos). Num triângulo, cada vértice recebe a soma dos outros dois, isto
                # é, a soma dos três menos ele mesmo; e um lado comum a dois triângulos é visto duas vezes (peso 1/2).
                for e in range(3):                               # um eixo de cada vez: as contas não se misturam
                    col = np.ascontiguousarray(n[:, e])
                    ac = np.zeros(nv, np.float64)
                    for i in range(0, nf, bloco):
                        fb = F[i:i + bloco]
                        soma = col[fb[:, 0]]
                        soma += col[fb[:, 1]]
                        soma += col[fb[:, 2]]
                        for k in range(3):
                            ac += np.bincount(fb[:, k], weights=soma, minlength=nv)
                        del soma
                    ac -= grau * col
                    ac *= 0.5
                    n[:, e] += ac
                    del ac, col
            c = np.linalg.norm(n, axis=1)
            n /= np.maximum(c, 1e-30)[:, None]
            self._cache[ch] = n.astype(np.float32)
        return self._cache[ch]

    def aresta_mediana(self):
        """Comprimento típico dos lados dos triângulos (mediana numa amostra; não precisa da tabela de arestas)."""
        if "am" not in self._cache:
            n = self.n_faces
            T = self.cantos(None if n <= 100_000 else np.sort(np.random.default_rng(0).choice(n, 100_000, replace=False)))
            lados = np.concatenate([np.linalg.norm(T[:, 1] - T[:, 0], axis=1), np.linalg.norm(T[:, 2] - T[:, 1], axis=1),
                                    np.linalg.norm(T[:, 0] - T[:, 2], axis=1)])
            self._cache["am"] = float(np.median(lados)) if len(lados) else 1.0
        return self._cache["am"]

    def amostrar(self, passo, semente=0, suavizar=2, maximo=1_500_000):
        """Pontos espalhados por igual na superfície (um a cada ~passo mm), com a normal suavizada.
        Devolve (pontos, normais, triângulo de cada ponto)."""
        rng = np.random.default_rng(semente)
        n = int(min(maximo, max(200, self.area / (passo * passo))))
        acum = np.cumsum(self.A, dtype=np.float64)
        acum /= acum[-1]
        # sorteados em ordem: os triângulos saem em ordem e a leitura dos vértices anda para a frente na memória
        f = np.minimum(acum.searchsorted(np.sort(rng.random(n)), side="right"), self.n_faces - 1)
        del acum
        r1, r2 = rng.random(n), rng.random(n)
        s = np.sqrt(r1)
        b = np.c_[1 - s, s * (1 - r2), s * r2]
        P = (self.cantos(f) * b[:, :, None]).sum(1)
        if suavizar:
            nv = self.normais_de_vertice(suavizar)
            Nn = (nv[self.F[f]].astype(np.float64) * b[:, :, None]).sum(1)
            c = np.linalg.norm(Nn, axis=1)
            ruim = c < 1e-9
            Nn = Nn / np.maximum(c, 1e-30)[:, None]
            if ruim.any():
                Nn[ruim] = self.normais(f[ruim])
        else:
            Nn = self.normais(f)
        return P, Nn, f

    # ---- índice espacial dos triângulos (pelo centro)
    def grade(self):
        if "grade" not in self._cache:
            # uns 30 triângulos por célula ocupada
            cel = float(np.clip(np.sqrt(30.0 * self.area / max(self.n_faces, 1)), 1.0, 30.0))
            self._cache["grade"] = Grade.de_malha(self, cel)
        return self._cache["grade"]

    def soltar_tabelas(self, *nomes):
        """Libera tabelas auxiliares que já serviram (todas, se nenhum nome for dado; a área e a caixa ficam)."""
        for ch in (nomes or [c for c in self._cache if c not in ("area", "caixa", "am")]):
            self._cache.pop(ch, None)

    def sub(self, manter):
        """Malha só com os triângulos marcados; devolve (malha, índice antigo de cada vértice novo)."""
        F = self.F[manter]
        usados = np.zeros(self.n_vertices, bool)
        usados[F.ravel()] = True
        novo = (np.cumsum(usados, dtype=np.int64) - 1).astype(np.int32)
        return Malha(self.V[usados], novo[F], nome=self.nome), np.flatnonzero(usados)


class Grade:
    """Índice espacial de pontos numa grade de células cúbicas: acha depressa os pontos dentro de uma bola.
    Guarda só a ordem dos pontos por célula (4 bytes por ponto) e o começo de cada célula ocupada."""

    def __init__(self, pontos, n, lo, hi, cel, bloco=_BLOCO):
        """pontos(i, j) devolve as coordenadas dos pontos i..j-1; pontos(idx) as dos índices dados."""
        self.pontos = pontos
        self.cel = float(cel)
        self.lo = np.asarray(lo, np.float64)
        self.dim = np.maximum(np.floor((np.asarray(hi, np.float64) - self.lo) / self.cel).astype(np.int64) + 1, 1)
        bits_i = max(1, int(n - 1).bit_length())
        if int(self.dim[0] * self.dim[1] * self.dim[2] - 1).bit_length() + bits_i > 63:
            raise ValueError("Malha grande demais para o índice espacial.")
        emp = np.empty(n, np.int64)                         # célula e índice no mesmo número: uma ordenação só
        for i in range(0, n, bloco):
            j = min(n, i + bloco)
            emp[i:j] = (self._celula(pontos(i, j)) << bits_i) | np.arange(i, j, dtype=np.int64)
        emp.sort()
        self.ordem = (emp & ((1 << bits_i) - 1)).astype(np.int32)
        emp >>= bits_i
        novo = np.empty(n, bool)
        if n:
            novo[0] = True
            np.not_equal(emp[1:], emp[:-1], out=novo[1:])
        self.chave = emp[novo]                              # células ocupadas, em ordem
        self.ini = np.r_[np.flatnonzero(novo), n].astype(np.int64)

    @classmethod
    def de_malha(cls, m, cel):
        lo, hi = m.caixa()

        def pontos(i, j=None):
            return m.centros(slice(i, j) if j is not None else i)
        return cls(pontos, m.n_faces, lo, hi, cel)

    @classmethod
    def de_pontos(cls, P, cel):
        P = np.asarray(P)

        def pontos(i, j=None):
            return P[i:j] if j is not None else P[i]
        if not len(P):
            return cls(pontos, 0, np.zeros(3), np.zeros(3), cel)
        return cls(pontos, len(P), P.min(0), P.max(0), cel)

    def _celula(self, P):
        q = np.floor((P - self.lo) / self.cel).astype(np.int64)
        np.clip(q, 0, self.dim - 1, out=q)
        return (q[:, 0] * self.dim[1] + q[:, 1]) * self.dim[2] + q[:, 2]

    def caixa(self, lo, hi):
        """Índices dos pontos nas células que tocam a caixa [lo, hi]."""
        a = np.clip(np.floor((np.asarray(lo, float) - self.lo) / self.cel).astype(np.int64), 0, self.dim - 1)
        b = np.clip(np.floor((np.asarray(hi, float) - self.lo) / self.cel).astype(np.int64), 0, self.dim - 1)
        ix, iy = np.meshgrid(np.arange(a[0], b[0] + 1), np.arange(a[1], b[1] + 1), indexing="ij")
        base = (ix.ravel() * self.dim[1] + iy.ravel()) * self.dim[2]
        i0 = self.ini[np.searchsorted(self.chave, base + a[2], "left")]
        i1 = self.ini[np.searchsorted(self.chave, base + b[2], "right")]
        n = i1 - i0
        tem = n > 0
        if not tem.any():
            return np.zeros(0, np.int64)
        i0, n = i0[tem], n[tem]
        ini = np.repeat(i0 - np.r_[0, np.cumsum(n)[:-1]], n)
        return self.ordem[ini + np.arange(int(n.sum()))].astype(np.int64)

    def bola(self, c, r):
        """Índices dos pontos a até r de c."""
        c = np.asarray(c, float)
        idx = self.caixa(c - r, c + r)
        if not len(idx):
            return idx
        idx.sort()                                          # em ordem, a leitura dos vértices anda para a frente
        d = self.pontos(idx) - c
        return idx[np.einsum("ij,ij->i", d, d) <= r * r]

    def bolas(self, centros, r):
        """União dos pontos a até r de qualquer um dos centros."""
        centros = np.asarray(centros, float).reshape(-1, 3)
        if not len(centros):
            return np.zeros(0, np.int64)
        partes = [self.bola(c, r) for c in centros]
        return np.unique(np.concatenate(partes)) if partes else np.zeros(0, np.int64)


# ---------------------------------------------------------------------------
# leitura
# ---------------------------------------------------------------------------

_REG = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])       # um triângulo do STL binário: 50 bytes


def _stl_binario(caminho):
    """Nº de triângulos se o arquivo é um STL binário bem formado; None se não é (STL de texto, por exemplo)."""
    tam = os.path.getsize(caminho)
    if tam < 84:
        return None
    with open(caminho, "rb") as fh:
        cab = fh.read(84)
    n = int(np.frombuffer(cab[80:84], "<u4")[0])
    if n > 0 and 84 + 50 * n == tam:
        return n
    if n > 0 and 84 + 50 * n < tam <= 84 + 50 * n + 4096 and not cab.lstrip().lower().startswith(b"solid"):
        return n                                    # alguns programas deixam bytes sobrando no fim
    return None


def contar_triangulos(caminho):
    """Nº de triângulos de um STL binário sem ler o arquivo; None nos outros formatos."""
    try:
        if os.path.splitext(str(caminho))[1].lower() == ".stl":
            return _stl_binario(str(caminho))
    except OSError:
        pass
    return None


def _codigo(P):
    """Um número de 64 bits por ponto (float32 N×3): pontos iguais bit a bit têm o mesmo código."""
    u = P.view(np.uint32).reshape(-1, 3)
    h = u[:, 0].astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
    h ^= (u[:, 1].astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)) >> np.uint64(7)
    h += u[:, 2].astype(np.uint64) * np.uint64(0x165667B19E3779F9)
    h ^= h >> np.uint64(29)
    return h


def _blocos_stl(caminho, n, bloco=_BLOCO):
    """Os vértices do STL, bloco a bloco: (K×3 float32 só dos triângulos sem coordenada inválida)."""
    with open(caminho, "rb") as fh:
        fh.seek(84)
        for i in range(0, n, bloco):
            k = min(bloco, n - i)
            b = np.fromfile(fh, dtype=_REG, count=k)
            if len(b) < k:
                raise ValueError("arquivo STL incompleto")
            P = np.ascontiguousarray(b["v"])
            del b
            bom = np.isfinite(P).all(axis=(1, 2))
            if not bom.all():
                P = P[bom]
            P = P.reshape(-1, 3)
            P += np.float32(0.0)                    # -0.0 vira +0.0: o mesmo ponto com os mesmos bits
            yield P


def _ler_stl(caminho, n, log=None):
    """STL binário lido em duas passadas pelo arquivo, sem nunca ter os triângulos soltos todos na memória.

    1ª passada: um código de 64 bits por ponto; ordenados, os códigos distintos são os vértices.
    2ª passada: cada ponto acha o seu vértice pelo código; os vértices são numerados na ordem em que aparecem (o
    que mantém vizinhos na malha vizinhos na memória) e cada bloco é conferido contra as coordenadas lidas."""
    h = np.empty(3 * n, np.uint64)
    k = 0
    for P in _blocos_stl(caminho, n):
        h[k:k + len(P)] = _codigo(P)
        k += len(P)
    h = h[:k]
    n_bons = k // 3
    h.sort()
    novo = np.empty(k, bool)
    if k:
        novo[0] = True
        np.not_equal(h[1:], h[:-1], out=novo[1:])
    u = h[novo]                                     # códigos distintos, em ordem
    del h, novo
    nv = len(u)
    num = np.full(nv, -1, np.int32)                 # código (pela posição em u) -> número do vértice
    V = np.empty((nv, 3), np.float32)
    F = np.empty((n_bons, 3), np.int32)
    feitos, t = 0, 0
    for P in _blocos_stl(caminho, n):
        pos = np.searchsorted(u, _codigo(P))
        ids = num[pos]
        falta = np.flatnonzero(ids < 0)
        if len(falta):
            cod, prim = np.unique(pos[falta], return_index=True)        # primeira vez de cada vértice novo no bloco
            ordem = np.argsort(prim, kind="stable")
            num[cod[ordem]] = feitos + np.arange(len(cod), dtype=np.int32)
            V[feitos:feitos + len(cod)] = P[falta[prim[ordem]]]
            feitos += len(cod)
            ids = num[pos]
        if not np.array_equal(V[ids], P):
            return None                             # dois pontos diferentes com o mesmo código: quase impossível
        F[t:t + len(P) // 3] = ids.reshape(-1, 3)
        t += len(P) // 3
    return V[:feitos], F


def juntar_vertices(P):
    """Junta vértices repetidos (iguais bit a bit), pelo caminho simples. P: N×3 float32. Devolve (V, índice)."""
    P = np.ascontiguousarray(P, dtype=np.float32)
    P += np.float32(0.0)
    Vu, inv = np.unique(P, axis=0, return_inverse=True)
    return Vu, inv.ravel().astype(np.int32)


def _ler_stl_simples(caminho, n):
    P = np.concatenate(list(_blocos_stl(caminho, n)))
    V, inv = juntar_vertices(P)
    return V, inv.reshape(-1, 3)


def carregar(caminho):
    caminho = str(caminho)
    if not os.path.isfile(caminho):
        raise ValueError(f"Arquivo não encontrado: {caminho}")
    if os.path.splitext(caminho)[1].lower() not in FORMATOS:
        raise ValueError("Formato de arquivo não suportado. Exporte a malha em STL, PLY, OBJ ou OFF "
                         "(arquivos de CAD como STEP ou IGES não são malha).")
    n = contar_triangulos(caminho)
    try:
        if n:
            r = _ler_stl(caminho, n) or _ler_stl_simples(caminho, n)
            V, F = r
        else:
            import trimesh
            m = trimesh.load(caminho, force="mesh", process=True)
            if getattr(m, "faces", None) is None or len(m.faces) == 0:
                raise ValueError("O arquivo não contém triângulos. Exporte a MALHA (STL/PLY/OBJ), não só a nuvem de pontos.")
            V = np.asarray(m.vertices, np.float32)
            F = np.asarray(m.faces)
            del m
    except MemoryError:
        raise
    except ValueError as e:
        if "triângulos" in str(e):
            raise
        raise ValueError(f"Não consegui ler a malha (arquivo corrompido ou incompleto?): {e}")
    except Exception as e:
        raise ValueError(f"Não consegui ler a malha (arquivo corrompido ou incompleto?): {type(e).__name__}: {e}")
    if not np.isfinite(V).all():
        bom = np.isfinite(V).all(axis=1)
        F = F[bom[F].all(axis=1)]
        V = np.where(np.isfinite(V), V, np.float32(0.0))
    malha = Malha(V, F, nome=caminho)
    if malha.n_faces == 0:
        raise ValueError("O arquivo não contém triângulos válidos. Exporte a MALHA (STL/PLY/OBJ), não só a nuvem de pontos.")
    malha, n = sem_soltos(malha)
    malha.soltos = n
    return malha


def sem_soltos(m):
    """Tira triângulos perdidos muito longe da peça. Devolve (malha, nº de triângulos retirados)."""
    V = m.V
    if len(V) < 100:
        return m, 0
    passo = max(1, len(V) // 2_000_000)             # os limites saem de uma amostra: basta
    lo, hi = np.percentile(V[::passo].astype(np.float64), [0.5, 99.5], axis=0)
    folga = 0.5 * (hi - lo) + 1.0
    lo_g, hi_g = m.caixa()
    if (lo_g >= lo - folga).all() and (hi_g <= hi + folga).all():
        return m, 0
    fora = ((V < lo - folga) | (V > hi + folga)).any(axis=1)
    fica = ~fora[m.F].any(axis=1)
    if fica.sum() < 0.5 * len(m.F):
        return m, 0
    nova, _ = m.sub(fica)
    return nova, int((~fica).sum())


# ---------------------------------------------------------------------------
# gravação (com a máscara dos triângulos que ficam: a malha limpa não é montada na memória)
# ---------------------------------------------------------------------------

def gravar_stl(m, caminho, manter=None, cabecalho="Cleanmold - malha limpa (mm)", log=None):
    """STL binário (o formato que o Control X, o Design X e o SolidWorks abrem sem perguntar nada)."""
    n = m.n_faces if manter is None else int(np.count_nonzero(manter))
    cab = cabecalho.encode("ascii", "replace")[:80].ljust(80, b" ")
    tmp = str(caminho) + ".parcial"
    try:
        with open(tmp, "wb") as fh:
            fh.write(cab)
            fh.write(np.uint32(n).tobytes())
            for i in range(0, m.n_faces, _BLOCO):
                f = m.F[i:i + _BLOCO]
                if manter is not None:
                    f = f[manter[i:i + _BLOCO]]
                    if not len(f):
                        continue
                T = m.V[f]
                reg = np.zeros(len(f), dtype=_REG)
                a = T[:, 0].astype(np.float64)
                cr = np.cross(T[:, 1] - a, T[:, 2] - a)
                reg["n"] = cr / np.maximum(np.linalg.norm(cr, axis=1), 1e-300)[:, None]
                reg["v"] = T
                reg.tofile(fh)
                if log and m.n_faces > 4 * _BLOCO:
                    log(f"Gravando a malha… {int(100 * min(i + _BLOCO, m.n_faces) / m.n_faces)}%")
        os.replace(tmp, caminho)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return caminho


def gravar_ply(m, caminho, manter=None, log=None):
    """PLY binário: mantém os vértices compartilhados (arquivo com menos da metade do tamanho do STL, mesma malha)."""
    n = m.n_faces if manter is None else int(np.count_nonzero(manter))
    renum = None
    nv = m.n_vertices
    if manter is not None:
        usados = np.zeros(m.n_vertices, bool)
        for i in range(0, m.n_faces, _BLOCO):
            usados[m.F[i:i + _BLOCO][manter[i:i + _BLOCO]].ravel()] = True
        nv = int(np.count_nonzero(usados))
        if nv < m.n_vertices:
            renum = (np.cumsum(usados, dtype=np.int64) - 1).astype(np.int32)
    cab = ("ply\nformat binary_little_endian 1.0\ncomment Cleanmold - malha limpa (mm)\n"
           f"element vertex {nv}\nproperty float x\nproperty float y\nproperty float z\n"
           f"element face {n}\nproperty list uchar int vertex_indices\nend_header\n").encode("ascii")
    tmp = str(caminho) + ".parcial"
    try:
        with open(tmp, "wb") as fh:
            fh.write(cab)
            for i in range(0, m.n_vertices, 4 * _BLOCO):
                v = m.V[i:i + 4 * _BLOCO]
                if renum is not None:
                    v = v[usados[i:i + 4 * _BLOCO]]
                fh.write(np.ascontiguousarray(v, dtype="<f4").tobytes())
            for i in range(0, m.n_faces, _BLOCO):
                f = m.F[i:i + _BLOCO]
                if manter is not None:
                    f = f[manter[i:i + _BLOCO]]
                    if not len(f):
                        continue
                reg = np.empty(len(f), dtype=[("k", "u1"), ("i", "<i4", 3)])
                reg["k"] = 3
                reg["i"] = f if renum is None else renum[f]
                reg.tofile(fh)
                if log and m.n_faces > 4 * _BLOCO:
                    log(f"Gravando a malha… {int(100 * min(i + _BLOCO, m.n_faces) / m.n_faces)}%")
        os.replace(tmp, caminho)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return caminho
