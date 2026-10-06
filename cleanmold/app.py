"""Fluxo do Cleanmold: abrir a malha, achar os alvos, retirá-los e gravar os arquivos."""
import json
import math
import os
import struct
import time

import numpy as np
from scipy.spatial import cKDTree

from . import __version__, ajuste, alvos, limpeza, malha

ITENS = ("stl", "ply", "pdf", "html", "csv", "step", "macro")


def erro_de_arquivo(e):
    """Motivo de um erro de arquivo, em português."""
    import errno
    cod = getattr(e, "errno", None)
    if isinstance(e, PermissionError) or cod in (errno.EACCES, errno.EPERM):
        return "sem permissão, ou o arquivo está aberto em outro programa"
    if isinstance(e, FileNotFoundError) or cod == errno.ENOENT:
        return "pasta ou arquivo não encontrado"
    if cod == errno.ENOSPC:
        return "disco cheio"
    return getattr(e, "strerror", None) or type(e).__name__


class Sessao:
    """Uma malha aberta e o que já foi feito com ela."""

    def __init__(self, caminho, log=lambda s: None):
        self.caminho = caminho
        self.log = log
        log(f"Lendo a malha {os.path.basename(caminho)}")
        self.m = malha.carregar(caminho)
        log(f"{self.m.n_faces:,} triângulos".replace(",", "."))
        self.det = None
        self.limpa = None            # resultado de limpeza.limpar
        self.opcoes = dict(limpeza.OPCOES)
        self.escolha = []            # alvos marcados para retirar
        self.t_analise = None

    # ---- análise
    def analisar(self):
        t = time.time()
        self.det = alvos.detectar(self.m, log=self.log)
        self.escolha = [i for i, a in enumerate(self.det["alvos"]) if a["seguro"]]
        self.limpa = None
        self.t_analise = time.time() - t
        # memória: as tabelas de arestas da malha inteira só serviram para separar os pedaços
        for ch in ("arestas", "viz", "gf", "bordas"):
            self.m._cache.pop(ch, None)
        return self.det

    def alvo_manual(self, ponto, diametro=None):
        """Acrescenta um alvo indicado à mão: o ponto clicado vira o centro do recorte; o eixo é a normal da
        superfície em volta. Devolve o índice do alvo novo."""
        ponto = np.asarray(ponto, float)
        raio = float(diametro) / 2 if diametro else 9.4
        if not (1.0 <= raio <= 60.0):
            raise ValueError("O diâmetro do recorte precisa ficar entre 2 e 120 mm.")
        if "arvore_faces" not in self.m._cache:
            self.log("Indexando a malha…")
            self.m._cache["arvore_faces"] = cKDTree(self.m.C)
        arv = self.m._cache["arvore_faces"]
        idx = np.asarray(arv.query_ball_point(ponto, raio + 20.0))
        idx = idx[self.det["eh_peca"][idx]] if len(idx) else idx
        if len(idx) < 30:
            raise ValueError("Não há superfície da peça suficiente em volta do ponto clicado.")
        C, N, A = self.m.C[idx], self.m.N[idx], self.m.A[idx]
        d = np.linalg.norm(C - ponto, axis=1)
        # a superfície em que o alvo está apoiado: o plano com mais área em volta do clique que passa logo abaixo
        # dele. (A soma das normais não serve: numa chapa fina a face de baixo anula a de cima.)
        rng = np.random.default_rng(0)
        cand = np.flatnonzero(d > 0.5 * raio)
        if len(cand) < 20:
            raise ValueError("Não há superfície da peça suficiente em volta do ponto clicado.")
        melhor = None
        for i in rng.choice(cand, size=min(160, len(cand)), replace=False):
            alt = float((ponto - C[i]) @ N[i])              # o clique fica do lado de fora, até uns 12 mm acima
            if not (-1.5 < alt < 12.0):
                continue
            perto = (np.abs((C - C[i]) @ N[i]) < 0.6) & (N @ N[i] > 0.9)
            nota = float(A[perto].sum()) / (1.0 + max(alt, 0.0) / 6.0)
            if melhor is None or nota > melhor[0]:
                melhor = (nota, i, perto)
        if melhor is None or A[melhor[2]].sum() < 20.0:
            raise ValueError("Não achei a superfície da peça junto ao ponto clicado. Clique no pé do alvo, perto da peça.")
        pc, pn, _ = ajuste.plano(C[melhor[2]], A[melhor[2]])
        if pn @ N[melhor[1]] < 0:
            pn = -pn
        centro = ponto - ((ponto - pc) @ pn) * pn
        a = dict(centro=centro, eixo=pn, raio=raio, altura_base=6.0, rms=float("nan"), volta=0.0, tipo="manual",
                 nome="Indicado à mão", confianca=1.0, nota_pe=1.0, nota_corpo=1.0, isolado=1.0, altura=60.0,
                 raio_max=max(14.0, raio + 4.0), medido=None, votos=0.0, soltos=[], seguro=True, deformado=False, manual=True)
        self.det["alvos"].append(a)
        self.escolha.append(len(self.det["alvos"]) - 1)
        self.limpa = None
        return len(self.det["alvos"]) - 1

    # ---- limpeza
    def limpar(self, escolha=None, opcoes=None):
        if escolha is not None:
            n = len(self.det["alvos"])
            self.escolha = sorted({int(i) for i in escolha if 0 <= int(i) < n})
        if opcoes:
            for ch in ("margem", "alcance"):
                if opcoes.get(ch) is not None:
                    self.opcoes[ch] = float(opcoes[ch])
            for ch in ("remover_soltos", "preencher"):
                if ch in opcoes:
                    self.opcoes[ch] = bool(opcoes[ch])
        if not (0.0 <= self.opcoes["margem"] <= 10.0):
            raise ValueError("A margem precisa ficar entre 0 e 10 mm.")
        if not (2.0 <= self.opcoes["alcance"] <= 30.0):
            raise ValueError("O alcance precisa ficar entre 2 e 30 mm.")
        t = time.time()
        self.limpa = limpeza.limpar(self.m, self.det, self.escolha, self.opcoes, log=self.log)
        self.limpa["tempo"] = time.time() - t
        ml = self.limpa["malha"]
        self.log(f"Malha limpa: {ml.n_faces:,} triângulos".replace(",", "."))
        return self.limpa

    # ---- o que a interface mostra
    def resumo(self):
        det = self.det
        lo, hi = self.m.caixa()
        alvos_ = []
        rel = self.limpa["relatorio"] if self.limpa else None
        feitos = set(self.limpa["escolhidos"]) if self.limpa else set()
        for i, a in enumerate(det["alvos"]) if det else []:
            r = (rel[i] if rel and i < len(rel) else None) or {}
            alvos_.append(dict(
                i=i, tipo=a["tipo"], nome=a["nome"], confianca=a["confianca"], seguro=bool(a["seguro"]),
                deformado=bool(a.get("deformado")), manual=bool(a.get("manual")),
                centro=[float(x) for x in a["centro"]], eixo=[float(x) for x in a["eixo"]],
                raio=float(a["raio"]), altura=float(a["altura"]), raio_max=float(a["raio_max"]),
                soltos=len(a.get("soltos") or []), marcado=i in self.escolha, retirado=i in feitos,
                referencia=r.get("referencia"), sigma=r.get("sigma"), preenchido=r.get("preenchido"),
                aviso=r.get("aviso"), degrau=r.get("degrau"), area=r.get("area_remendo"),
                arestas=r.get("arestas_vivas")))
        ml = self.limpa["malha"] if self.limpa else None
        return dict(
            arquivo=os.path.basename(self.caminho), triangulos=self.m.n_faces, area=self.m.area,
            caixa=[[float(x) for x in lo], [float(x) for x in hi]], aresta=self.m.aresta_mediana(),
            alvos=alvos_, soltos=len(det["soltos"]) if det else 0,
            soltos_sem_alvo=sum(1 for s in det["soltos"] if s.get("alvo") is None) if det else 0,
            opcoes=dict(self.opcoes), limpo=self.limpa is not None,
            triangulos_limpa=ml.n_faces if ml else None,
            soltos_removidos=self.limpa["soltos_removidos"] if self.limpa else 0,
            tempo_analise=self.t_analise, tempo_limpeza=self.limpa.get("tempo") if self.limpa else None)

    def marcas_antes(self):
        """Para cada triângulo da malha original: 0 = peça, 1 = pedaço solto, 2+i = alvo i."""
        m, det = self.m, self.det
        marca = np.zeros(m.n_faces, np.uint16)
        for s in det["soltos"]:
            marca[s["faces"]] = 1
        if "arvore_faces" not in m._cache:
            self.log("Indexando a malha…")
            m._cache["arvore_faces"] = cKDTree(m.C)
        arv = m._cache["arvore_faces"]
        for i, a in enumerate(det["alvos"]):
            c, e = a["centro"], a["eixo"]
            idx = np.asarray(arv.query_ball_point(c + e * (a["altura"] / 2), a["altura"] / 2 + a["raio_max"] + 22.0))
            if not len(idx):
                continue
            Q = m.C[idx] - c
            h = Q @ e
            rho = np.linalg.norm(Q - np.outer(h, e), axis=1)
            dentro = (h > 2.0) & (h < a["altura"] + 8.0) & (rho < a["raio_max"] + 3.0 + 0.3 * np.maximum(h, 0))
            dentro |= (h > 0.35) & (h <= 2.0 + a.get("altura_base", 6.0)) & (rho < a["raio"] + 0.8)
            marca[idx[dentro]] = 2 + i
            for k in a.get("soltos") or []:
                marca[det["soltos"][k]["faces"]] = 2 + i
        return marca

    def focos(self):
        """Regiões que a tela mostra com todos os triângulos (em volta de cada alvo): centros e raio."""
        if not self.det or not self.det["alvos"]:
            return np.zeros((0, 3)), 0.0
        return np.array([a["centro"] + a["eixo"] * 14.0 for a in self.det["alvos"]]), 36.0


# ---------------------------------------------------------------------------
# malha para a tela
# ---------------------------------------------------------------------------

def _empacotar(cab, blocos):
    off = 0
    partes = []
    for nome, arr in blocos:
        b = np.ascontiguousarray(arr).tobytes()
        cab["blocos"][nome] = [off, int(arr.size)]
        partes.append(b)
        off += len(b)
        if off % 4:
            pad = 4 - off % 4
            partes.append(b"\0" * pad)
            off += pad
    j = json.dumps(cab).encode("utf-8")
    j += b" " * ((4 - (len(j) + 4) % 4) % 4)
    return struct.pack("<I", len(j)) + j + b"".join(partes)


def malha_para_tela(m, marca=None, focos=None, raio_foco=0.0, alvo=600_000):
    """Reduz a malha para a tela por agrupamento de vértices, mantendo todos os triângulos perto dos alvos.
    Cada grupo é representado por um vértice real da malha. `marca`: valor por triângulo, levado aos vértices
    (o maior valor entre os triângulos de cada vértice). Devolve bytes (cabeçalho JSON + blocos V, I, M)."""
    V, F = m.V, m.F
    n_orig = len(F)
    mv = None
    if marca is not None:
        mv = np.zeros(len(V), np.uint16)
        for k in range(3):
            np.maximum.at(mv, F[:, k], marca)
    if len(F) > alvo:
        cel = math.sqrt(2.0 * m.area / alvo)
        fino = np.zeros(len(V), bool)
        if focos is not None and len(focos):
            arv = cKDTree(focos)
            d, _ = arv.query(V, distance_upper_bound=raio_foco)
            fino = np.isfinite(d)
        if mv is not None:
            fino |= mv > 0
        q = np.floor((V - V.min(0)) / cel).astype(np.int64)
        chave = (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]
        base = int(chave.max()) + 1
        ids = np.flatnonzero(fino)
        chave[ids] = base + np.arange(len(ids))                 # vértice mantido = grupo só dele
        _, inv, cont = np.unique(chave, return_inverse=True, return_counts=True)
        inv = inv.ravel()
        centro = np.stack([np.bincount(inv, weights=V[:, k]) / cont for k in range(3)], axis=1)
        d2 = ((V - centro[inv]) ** 2).sum(1)
        ordem = np.lexsort((d2, inv))
        prim = ordem[np.flatnonzero(np.r_[True, inv[ordem][1:] != inv[ordem][:-1]])]
        Vn = V[prim]
        Fn = inv[F]
        ok = (Fn[:, 0] != Fn[:, 1]) & (Fn[:, 1] != Fn[:, 2]) & (Fn[:, 0] != Fn[:, 2])
        # triângulo que virou do avesso ao juntar vértices apareceria como uma lasca escura: fica de fora
        T = Vn[Fn[ok]]
        nn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        ok[np.flatnonzero(ok)[np.einsum("ij,ij->i", nn, m.N[ok]) <= 0]] = False
        Fn = Fn[ok]
        if mv is not None:
            mvn = np.zeros(len(Vn), np.uint16)
            np.maximum.at(mvn, inv, mv)
            mv = mvn
        V, F = Vn, Fn
    else:
        usados = np.zeros(len(V), bool)
        usados[F.ravel()] = True
        if not usados.all():
            novo = np.cumsum(usados) - 1
            V, F = V[usados], novo[F]
            if mv is not None:
                mv = mv[usados]
    lo, hi = V.min(0), V.max(0)
    cab = dict(blocos={}, triangulos=int(len(F)), originais=int(n_orig), caixa=[lo.tolist(), hi.tolist()])
    blocos = [("V", V.astype(np.float32)), ("I", F.astype(np.uint32))]
    if mv is not None:
        blocos.append(("M", mv.astype(np.uint16)))
    return _empacotar(cab, blocos)
