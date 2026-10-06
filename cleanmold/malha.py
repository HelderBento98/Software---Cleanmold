"""Malha de triângulos: leitura, gravação, vizinhança, bordas e amostragem.

Tudo em milímetros. A malha é um par (V, F): vértices N×3 e triângulos M×3 (índices de V)."""
import os
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

FORMATOS = (".stl", ".ply", ".obj", ".off")


class Malha:
    def __init__(self, V, F, nome=""):
        self.V = np.ascontiguousarray(V, dtype=np.float64)
        F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
        T = self.V[F]
        cr = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        a2 = np.linalg.norm(cr, axis=1)
        ok = (a2 > 1e-14) & (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
        if not ok.all():
            F, T, cr, a2 = F[ok], T[ok], cr[ok], a2[ok]
        self.F = np.ascontiguousarray(F)
        self.A = a2 / 2                      # área de cada triângulo
        self.N = cr / a2[:, None]            # normal de cada triângulo
        self.C = T.mean(axis=1)              # centro de cada triângulo
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
        T = self.V[self.F]
        return float(np.einsum("ij,ij->i", T[:, 0], np.cross(T[:, 1], T[:, 2])).sum() / 6.0)

    # ---- arestas
    def arestas(self):
        """(meia_aresta -> id da aresta, pares de vértices por aresta, nº de triângulos por aresta)."""
        if "arestas" not in self._cache:
            F = self.F
            e = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
            e = np.sort(e, axis=1)
            chave = e[:, 0] * (self.n_vertices + 1) + e[:, 1]
            u, prim, inv, cont = np.unique(chave, return_index=True, return_inverse=True, return_counts=True)
            self._cache["arestas"] = (inv.reshape(3, -1).T.copy(), e[prim], cont)
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
            aresta = fe.T.ravel()                                # mesma ordem de np.vstack acima
            face = np.tile(np.arange(m), 3)
            ordem = np.argsort(aresta, kind="stable")
            a, f = aresta[ordem], face[ordem]
            dois = cont[a] == 2
            a, f = a[dois], f[dois]
            self._cache["viz"] = (f.reshape(-1, 2), a[::2])
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
        if "am" not in self._cache:
            _, e, _ = self.arestas()
            sel = e if len(e) < 200000 else e[np.random.default_rng(0).choice(len(e), 200000, replace=False)]
            self._cache["am"] = float(np.median(np.linalg.norm(self.V[sel[:, 0]] - self.V[sel[:, 1]], axis=1)))
        return self._cache["am"]

    # ---- operações que devolvem malha nova
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
            Nn = self.N[f].copy()
        return P, Nn, f


# ---------------------------------------------------------------------------
# leitura e gravação
# ---------------------------------------------------------------------------

def carregar(caminho):
    caminho = str(caminho)
    if not os.path.isfile(caminho):
        raise ValueError(f"Arquivo não encontrado: {caminho}")
    if os.path.splitext(caminho)[1].lower() not in FORMATOS:
        raise ValueError("Formato de arquivo não suportado. Exporte a malha em STL, PLY, OBJ ou OFF "
                         "(arquivos de CAD como STEP ou IGES não são malha).")
    import trimesh
    try:
        m = trimesh.load(caminho, force="mesh", process=True)
    except Exception as e:
        raise ValueError(f"Não consegui ler a malha (arquivo corrompido ou incompleto?): {type(e).__name__}: {e}")
    if getattr(m, "faces", None) is None or len(m.faces) == 0:
        raise ValueError("O arquivo não contém triângulos. Exporte a MALHA (STL/PLY/OBJ), não só a nuvem de pontos.")
    V = np.asarray(m.vertices, float)
    F = np.asarray(m.faces)
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


def gravar_stl(m, caminho):
    """STL binário (o formato que o Control X, o Design X e o SolidWorks abrem sem perguntar nada)."""
    n = m.n_faces
    reg = np.zeros(n, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    reg["n"] = m.N
    reg["v"] = m.V[m.F]
    cab = b"Cleanmold - malha limpa (mm)".ljust(80, b" ")
    tmp = str(caminho) + ".parcial"
    with open(tmp, "wb") as fh:
        fh.write(cab)
        fh.write(np.uint32(n).tobytes())
        fh.write(reg.tobytes())
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
