"""Malha de triângulos: leitura, gravação, vizinhança, bordas e amostragem.

Tudo em milímetros. A malha é um par (V, F): vértices N×3 e triângulos M×3 (índices de V)."""
import os
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

FORMATOS = (".stl", ".ply", ".obj", ".off")
_BLOCO = 1_000_000


class Malha:
    def __init__(self, V, F, nome=""):
        self.V = np.ascontiguousarray(V, dtype=np.float64)
        F = np.asarray(F).reshape(-1, 3)
        if len(self.V) >= 2**31 - 1:
            raise ValueError("Malha grande demais (mais de 2 bilhões de vértices).")
        F = np.ascontiguousarray(F, dtype=np.int32)
        m = len(F)
        A = np.empty(m, np.float64)
        N = np.empty((m, 3), np.float32)
        C = np.empty((m, 3), np.float32)
        ok = np.empty(m, bool)
        # em blocos: a malha inteira de uma vez pediria vários vetores temporários do tamanho dela
        for i in range(0, m, _BLOCO):
            f = F[i:i + _BLOCO]
            a, b, c = self.V[f[:, 0]], self.V[f[:, 1]], self.V[f[:, 2]]
            cr = np.cross(b - a, c - a)
            a2 = np.linalg.norm(cr, axis=1)
            ok[i:i + _BLOCO] = (a2 > 1e-14) & (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
            A[i:i + _BLOCO] = a2 / 2
            N[i:i + _BLOCO] = cr / np.maximum(a2, 1e-300)[:, None]
            C[i:i + _BLOCO] = (a + b + c) / 3.0
        if not ok.all():
            F, A, N, C = F[ok], A[ok], N[ok], C[ok]
        self.F = np.ascontiguousarray(F)
        self.A = A                           # área de cada triângulo
        self.N = N                           # normal de cada triângulo
        self.C = C                           # centro de cada triângulo
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
        return float(self.A.sum())

    def caixa(self):
        return self.V.min(0), self.V.max(0)

    def volume(self):
        """Volume com sinal (positivo quando as normais apontam para fora de uma malha fechada)."""
        v = 0.0
        for i in range(0, self.n_faces, _BLOCO):
            f = self.F[i:i + _BLOCO]
            v += float(np.einsum("ij,ij->i", self.V[f[:, 0]], np.cross(self.V[f[:, 1]], self.V[f[:, 2]])).sum())
        return v / 6.0

    # ---- arestas
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

    def grafo_vertices(self, com_comprimento=False):
        ch = "gv" + ("L" if com_comprimento else "")
        if ch not in self._cache:
            _, e, _ = self.arestas()
            n = self.n_vertices
            w = np.linalg.norm(self.V[e[:, 0]] - self.V[e[:, 1]], axis=1) if com_comprimento else np.ones(len(e), np.float32)
            g = sparse.coo_matrix((w, (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
            self._cache[ch] = g + g.T
        return self._cache[ch]

    def componentes(self):
        """Rótulo do pedaço ligado de cada triângulo (ligação por aresta) e o nº de pedaços."""
        if "comp" not in self._cache:
            n, rot = csgraph.connected_components(self.grafo_faces(), directed=False)
            self._cache["comp"] = (rot, n)
        return self._cache["comp"]

    def normais_de_vertice(self, suavizar=0):
        ch = ("nv", suavizar)
        if ch not in self._cache:
            n = np.zeros_like(self.V)
            pond = self.N * self.A[:, None]
            for k in range(3):
                np.add.at(n, self.F[:, k], pond)
            if suavizar:
                g = self.grafo_vertices()
                for _ in range(suavizar):
                    n = n + g @ n
            c = np.linalg.norm(n, axis=1)
            self._cache[ch] = n / np.maximum(c, 1e-30)[:, None]
        return self._cache[ch]

    def aresta_mediana(self):
        """Comprimento típico dos lados dos triângulos (mediana numa amostra; não precisa da tabela de arestas)."""
        if "am" not in self._cache:
            n = self.n_faces
            f = self.F if n <= 100_000 else self.F[np.random.default_rng(0).choice(n, 100_000, replace=False)]
            a, b, c = self.V[f[:, 0]], self.V[f[:, 1]], self.V[f[:, 2]]
            lados = np.concatenate([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)])
            self._cache["am"] = float(np.median(lados)) if len(lados) else 1.0
        return self._cache["am"]

    # ---- índice espacial dos triângulos (pelo centro)
    def grade(self):
        if "grade" not in self._cache:
            # uns 30 triângulos por célula ocupada
            cel = float(np.clip(np.sqrt(30.0 * self.area / max(self.n_faces, 1)), 1.0, 30.0))
            self._cache["grade"] = Grade(self.C, cel)
        return self._cache["grade"]

    # ---- operações que devolvem malha nova
    @classmethod
    def _montada(cls, V, F, A, N, C, nome=""):
        m = cls.__new__(cls)
        m.V, m.F, m.A, m.N, m.C = V, F, A, N, C
        m.validos = None
        m.nome = nome
        m._cache = {}
        return m

    def editar(self, manter=None, V_novos=None, F_novos=None):
        """Malha nova sem os triângulos desmarcados em `manter` e com os triângulos `F_novos` (que podem usar os
        vértices antigos e, a partir do índice n_vertices, os `V_novos`). As tabelas dos triângulos que ficam são
        aproveitadas. Devolve (malha, origem): para cada triângulo da malha nova, o índice do antigo; ou, se ele
        veio de F_novos, -1 - k (k = linha de F_novos)."""
        n_f = self.n_faces
        fica = np.ones(n_f, bool) if manter is None else np.asarray(manter, bool)
        V = self.V if V_novos is None or not len(V_novos) else np.vstack([self.V, np.asarray(V_novos, np.float64)])
        Fk = self.F[fica]
        partes_A, partes_N, partes_C = [self.A[fica]], [self.N[fica]], [self.C[fica]]
        origem = [np.flatnonzero(fica)]
        if F_novos is not None and len(F_novos):
            extra = Malha(V, np.asarray(F_novos).reshape(-1, 3))
            Fk = np.vstack([Fk, extra.F])
            partes_A.append(extra.A)
            partes_N.append(extra.N)
            partes_C.append(extra.C)
            linhas = np.arange(len(F_novos), dtype=np.int64)
            if extra.validos is not None:
                linhas = linhas[extra.validos]
            origem.append(-1 - linhas)
        usados = np.zeros(len(V), bool)
        usados[Fk.ravel()] = True
        if not usados.all():
            renum = (np.cumsum(usados) - 1).astype(np.int32)
            V, Fk = V[usados], renum[Fk]
        nova = Malha._montada(np.ascontiguousarray(V), np.ascontiguousarray(Fk, dtype=np.int32), np.concatenate(partes_A),
                              np.concatenate(partes_N), np.concatenate(partes_C), nome=self.nome)
        return nova, np.concatenate(origem)

    def mover(self, ids, posicoes):
        """Malha nova com os vértices `ids` nas `posicoes` dadas (mesmos triângulos)."""
        V = self.V.copy()
        V[ids] = posicoes
        mexeu = np.zeros(self.n_vertices, bool)
        mexeu[ids] = True
        f = np.flatnonzero(mexeu[self.F].any(axis=1))
        A, N, C = self.A.copy(), self.N.copy(), self.C.copy()
        a, b, c = V[self.F[f, 0]], V[self.F[f, 1]], V[self.F[f, 2]]
        cr = np.cross(b - a, c - a)
        a2 = np.linalg.norm(cr, axis=1)
        A[f] = a2 / 2
        N[f] = cr / np.maximum(a2, 1e-300)[:, None]
        C[f] = (a + b + c) / 3.0
        return Malha._montada(V, self.F, A, N, C, nome=self.nome)

    def enxuta(self):
        """Solta as tabelas auxiliares (arestas, índices): a malha guardada para desfazer ocupa só o essencial."""
        self._cache = {}
        return self

    def sub(self, manter):
        """Malha só com os triângulos marcados; devolve (malha, índice antigo de cada vértice novo)."""
        F = self.F[manter]
        usados = np.zeros(self.n_vertices, bool)
        usados[F.ravel()] = True
        novo = np.cumsum(usados) - 1
        return Malha(self.V[usados], novo[F], nome=self.nome), np.flatnonzero(usados)

    def copia(self):
        return Malha(self.V.copy(), self.F.copy(), nome=self.nome)

    def amostrar(self, passo, semente=0, suavizar=2, maximo=1_500_000):
        """Pontos espalhados por igual na superfície (um a cada ~passo mm), com a normal suavizada.
        Devolve (pontos, normais, triângulo de cada ponto)."""
        rng = np.random.default_rng(semente)
        n = int(min(maximo, max(200, self.area / (passo * passo))))
        prob = self.A / self.A.sum()
        f = rng.choice(self.n_faces, size=n, p=prob)
        r1, r2 = rng.random(n), rng.random(n)
        s = np.sqrt(r1)
        b = np.c_[1 - s, s * (1 - r2), s * r2]
        T = self.V[self.F[f]]
        P = (T * b[:, :, None]).sum(1)
        if suavizar:
            nv = self.normais_de_vertice(suavizar)
            Nn = (nv[self.F[f]] * b[:, :, None]).sum(1)
            c = np.linalg.norm(Nn, axis=1)
            ruim = c < 1e-9
            Nn = Nn / np.maximum(c, 1e-30)[:, None]
            Nn[ruim] = self.N[f[ruim]]
        else:
            Nn = self.N[f].astype(np.float64)
        return P, Nn, f


class Grade:
    """Índice espacial de pontos numa grade de células cúbicas: acha depressa os pontos dentro de uma bola.
    Ocupa bem menos memória que uma árvore k-d e é montado em uma ordenação."""

    def __init__(self, P, cel):
        self.P = P
        self.cel = float(cel)
        self.lo = P.min(0).astype(np.float64) if len(P) else np.zeros(3)
        q = np.floor((P - self.lo) / self.cel).astype(np.int64)
        self.dim = (q.max(0) + 1) if len(P) else np.ones(3, np.int64)
        chave = (q[:, 0] * self.dim[1] + q[:, 1]) * self.dim[2] + q[:, 2]
        ordem = np.argsort(chave, kind="stable")
        self.chave = chave[ordem]
        self.ordem = ordem.astype(np.int32)

    def caixa(self, lo, hi):
        """Índices dos pontos nas células que tocam a caixa [lo, hi]."""
        a = np.clip(np.floor((np.asarray(lo, float) - self.lo) / self.cel).astype(np.int64), 0, self.dim - 1)
        b = np.clip(np.floor((np.asarray(hi, float) - self.lo) / self.cel).astype(np.int64), 0, self.dim - 1)
        ix, iy = np.meshgrid(np.arange(a[0], b[0] + 1), np.arange(a[1], b[1] + 1), indexing="ij")
        base = (ix.ravel() * self.dim[1] + iy.ravel()) * self.dim[2]
        i0 = np.searchsorted(self.chave, base + a[2], "left")
        i1 = np.searchsorted(self.chave, base + b[2], "right")
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
        d = self.P[idx] - c
        return idx[np.einsum("ij,ij->i", d, d) <= r * r]

    def bolas(self, centros, r):
        """União dos pontos a até r de qualquer um dos centros."""
        centros = np.asarray(centros, float).reshape(-1, 3)
        if not len(centros):
            return np.zeros(0, np.int64)
        partes = [self.bola(c, r) for c in centros]
        return np.unique(np.concatenate(partes)) if partes else np.zeros(0, np.int64)


# ---------------------------------------------------------------------------
# leitura e gravação
# ---------------------------------------------------------------------------

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


def juntar_vertices(P):
    """Junta vértices repetidos (iguais bit a bit). P: N×3 float32. Devolve (V float64, índice do vértice de cada ponto).
    Os vértices ficam na ordem em que aparecem, o que mantém vizinhos na malha vizinhos na memória."""
    P = np.ascontiguousarray(P, dtype=np.float32)
    P += np.float32(0.0)                            # -0.0 vira +0.0: o mesmo ponto com os mesmos bits
    n = len(P)
    u = P.view(np.uint32).reshape(n, 3)
    h = u[:, 0].astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
    h ^= (u[:, 1].astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)) >> np.uint64(7)
    h += u[:, 2].astype(np.uint64) * np.uint64(0x165667B19E3779F9)
    h ^= h >> np.uint64(29)
    ordem = np.argsort(h, kind="stable")            # estável: dentro de cada grupo, o primeiro é o de menor índice
    hs = h[ordem]
    del h
    novo = np.empty(n, bool)
    novo[0] = True
    np.not_equal(hs[1:], hs[:-1], out=novo[1:])
    del hs
    grupo = np.cumsum(novo, dtype=np.int64) - 1     # grupo de cada ponto, na ordem do sorteio
    prim = ordem[novo]                              # primeiro ponto de cada grupo
    # renumera os grupos pela ordem de aparição
    rank = np.empty(len(prim), np.int32)
    rank[np.argsort(prim, kind="stable")] = np.arange(len(prim), dtype=np.int32)
    inv = np.empty(n, np.int32)
    inv[ordem] = rank[grupo]
    del grupo, ordem
    V32 = np.empty((len(prim), 3), np.float32)
    V32[rank] = P[prim]
    # confere (duas coordenadas diferentes com o mesmo código são quase impossíveis, mas custa pouco conferir)
    for i in range(0, n, 4 * _BLOCO):
        if not np.array_equal(V32[inv[i:i + 4 * _BLOCO]], P[i:i + 4 * _BLOCO]):
            Vu, inv = np.unique(P, axis=0, return_inverse=True)
            return Vu.astype(np.float64), inv.ravel().astype(np.int32)
    return V32.astype(np.float64), inv


def _ler_stl(caminho, n):
    """STL binário lido direto, em blocos, sem passar por tabelas intermediárias do tamanho do arquivo."""
    reg = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    P = np.empty((n, 3, 3), np.float32)
    with open(caminho, "rb") as fh:
        fh.seek(84)
        for i in range(0, n, _BLOCO):
            k = min(_BLOCO, n - i)
            b = np.fromfile(fh, dtype=reg, count=k)
            if len(b) < k:
                raise ValueError("arquivo STL incompleto")
            P[i:i + k] = b["v"]
    P = P.reshape(-1, 3)
    bom = np.isfinite(P).all(axis=1).reshape(n, 3).all(axis=1)
    if not bom.all():
        P = P.reshape(n, 3, 3)[bom].reshape(-1, 3)
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
            V, F = _ler_stl(caminho, n)
        else:
            import trimesh
            m = trimesh.load(caminho, force="mesh", process=True)
            if getattr(m, "faces", None) is None or len(m.faces) == 0:
                raise ValueError("O arquivo não contém triângulos. Exporte a MALHA (STL/PLY/OBJ), não só a nuvem de pontos.")
            V = np.asarray(m.vertices, float)
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
        V = np.where(np.isfinite(V), V, 0.0)
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
    lo, hi = np.percentile(V, [0.5, 99.5], axis=0)
    folga = 0.5 * (hi - lo) + 1.0
    fora = ((V < lo - folga) | (V > hi + folga)).any(axis=1)
    if not fora.any():
        return m, 0
    fica = ~fora[m.F].any(axis=1)
    if fica.sum() < 0.5 * len(m.F):
        return m, 0
    nova, _ = m.sub(fica)
    return nova, int((~fica).sum())


def gravar_stl(m, caminho, cabecalho="Cleanmold - malha limpa (mm)"):
    """STL binário (o formato que o Control X, o Design X e o SolidWorks abrem sem perguntar nada)."""
    n = m.n_faces
    cab = cabecalho.encode("ascii", "replace")[:80].ljust(80, b" ")
    tmp = str(caminho) + ".parcial"
    tipo = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    with open(tmp, "wb") as fh:
        fh.write(cab)
        fh.write(np.uint32(n).tobytes())
        for i in range(0, n, _BLOCO):
            f = m.F[i:i + _BLOCO]
            reg = np.zeros(len(f), dtype=tipo)
            reg["n"] = m.N[i:i + _BLOCO]
            reg["v"] = m.V[f]
            reg.tofile(fh)
    os.replace(tmp, caminho)
    return caminho


def gravar_ply(m, caminho):
    """PLY binário: mantém os vértices compartilhados (arquivo menor que o STL e sem costura para refazer)."""
    cab = ("ply\nformat binary_little_endian 1.0\ncomment Cleanmold - malha limpa (mm)\n"
           f"element vertex {m.n_vertices}\nproperty float x\nproperty float y\nproperty float z\n"
           f"element face {m.n_faces}\nproperty list uchar int vertex_indices\nend_header\n").encode("ascii")
    reg = np.zeros(m.n_faces, dtype=[("k", "u1"), ("i", "<i4", 3)])
    reg["k"] = 3
    reg["i"] = m.F
    tmp = str(caminho) + ".parcial"
    with open(tmp, "wb") as fh:
        fh.write(cab)
        fh.write(m.V.astype("<f4").tobytes())
        fh.write(reg.tobytes())
    os.replace(tmp, caminho)
    return caminho
