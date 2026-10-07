"""Fluxo do Cleanmold: abrir a malha, achar os alvos, retirá-los e gravar a malha limpa.

A sessão guarda UMA malha, a que foi aberta, e ela nunca é alterada. Retirar os alvos produz só uma máscara: quais
triângulos ficam. A malha limpa é escrita direto no arquivo a partir da malha original e dessa máscara."""
import json
import math
import os
import struct
import sys
import time

import numpy as np

from . import ajuste, alvos, limpeza, malha

ITENS = ("stl", "ply")
NOMES = dict(stl="_limpa.stl", ply="_limpa.ply")
BYTES_POR_TRIANGULO = 55                  # pico de memória para abrir e procurar, por triângulo (medido: 47)
BYTES_FIXOS = 950_000_000                 # parte do pico que não depende do tamanho da malha (pontos de amostra)


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


def memoria():
    """(total, disponível) de memória RAM em bytes; (None, None) se não der para saber."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class Estado(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            e = Estado()
            e.dwLength = ctypes.sizeof(Estado)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e)):
                return int(e.ullTotalPhys), int(e.ullAvailPhys)
            return None, None
        d = {}
        with open("/proc/meminfo") as fh:
            for l in fh:
                k, v = l.split(":")
                d[k] = int(v.split()[0]) * 1024
        return d.get("MemTotal"), d.get("MemAvailable", d.get("MemFree"))
    except Exception:
        return None, None


def avaliar_arquivo(caminho):
    """Quanto a malha vai pedir do computador, antes de abrir. Devolve dict(triangulos (None se não der para saber
    sem ler), estimado, tamanho, precisa, livre, total, apertado)."""
    tam = os.path.getsize(caminho)
    n = malha.contar_triangulos(caminho)
    estimado = n if n else int(tam / (50 if caminho.lower().endswith(".stl") else 22))
    total, livre = memoria()
    # os outros formatos passam por uma leitura genérica, que pede bem mais memória que a do STL binário
    precisa = int(estimado * (BYTES_POR_TRIANGULO if n else 4 * BYTES_POR_TRIANGULO) + min(BYTES_FIXOS, 220 * estimado))
    d = dict(triangulos=n, estimado=estimado, tamanho=tam, precisa=precisa, livre=livre, total=total, apertado=False)
    if livre:
        d["apertado"] = precisa > 0.85 * livre
    return d


class Sessao:
    """Uma malha aberta, os alvos achados nela e o resultado da retirada."""

    def __init__(self, caminho, log=lambda s: None):
        self.caminho = caminho
        self.log = log
        log(f"Lendo a malha {os.path.basename(caminho)}")
        self.m = malha.carregar(caminho)
        log(f"{self.m.n_faces:,} triângulos".replace(",", "."))
        self.tamanho = os.path.getsize(caminho)
        self.det = None
        self.limpa = None            # resultado de limpeza.limpar: dict(viva, relatorio, …)
        self.opcoes = dict(limpeza.OPCOES)
        self.escolha = []            # alvos marcados para retirar
        self.t_analise = None
        self.versao_alvos = 0        # muda quando a lista de alvos muda (a tela repinta os alvos)
        self.versao_limpa = 0        # muda a cada retirada (ou quando ela é desfeita)

    # ------------------------------------------------------------------ análise
    def analisar(self):
        t = time.time()
        manuais = [a for a in (self.det["alvos"] if self.det else []) if a.get("manual")]
        self.det = alvos.detectar(self.m, log=self.log)
        for a in manuais:
            self.det["alvos"].append(a)
            self._dar_soltos(len(self.det["alvos"]) - 1)
        self.escolha = [i for i, a in enumerate(self.det["alvos"]) if a["seguro"]]
        self.limpa = None
        self.t_analise = time.time() - t
        self.versao_alvos += 1
        self.versao_limpa += 1
        # as normais de vértice e os rótulos dos pedaços só serviram para a procura
        self.m.soltar_tabelas(("nv", 2), "pedacos")
        if "grade" not in self.m._cache:
            self.log("Indexando a malha…")
        self.m.grade()
        return self.det

    def alvo_manual(self, ponto, diametro=None):
        """Acrescenta um alvo indicado à mão: o ponto clicado vira o centro do recorte; o eixo é a normal da
        superfície em volta. Devolve o índice do alvo novo."""
        ponto = np.asarray(ponto, float)
        raio = float(diametro) / 2 if diametro else 9.4
        if not (1.0 <= raio <= 60.0):
            raise ValueError("O diâmetro do recorte precisa ficar entre 2 e 120 mm.")
        idx = self.m.grade().bola(ponto, raio + 20.0)
        idx = idx[self.det["eh_peca"][idx]] if len(idx) else idx
        if len(idx) < 30:
            raise ValueError("Não há superfície da peça suficiente em volta do ponto clicado.")
        C, N, A = self.m.centros(idx), self.m.normais(idx), self.m.A[idx].astype(float)
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
        # O clique cai em qualquer lugar do pé (quase sempre na parede dele). O centro do corte é o centro da parede
        # do pé: os triângulos em pé sobre o plano, logo acima dele, em volta do clique.
        idx = self.m.grade().bola(centro, 2.3 * raio + 2.0)
        if len(idx):
            Cp, Np, Ap = self.m.centros(idx), self.m.normais(idx), self.m.A[idx].astype(float)
            alt = (Cp - pc) @ pn
            parede = (alt > 0.5) & (alt < 6.0) & (np.abs(Np @ pn) < 0.5)
            c = centro
            for alcance in (2.2 * raio, 1.35 * raio, 1.2 * raio):
                Q = Cp - c
                lat = Q - np.outer(Q @ pn, pn)
                usa = parede & (np.linalg.norm(lat, axis=1) < alcance)
                if Ap[usa].sum() < 0.25 * 2 * np.pi * raio * 3.0:          # menos de um quarto da parede do pé: fica o clique
                    c = None
                    break
                c = c + np.average(lat[usa], axis=0, weights=Ap[usa])
            if c is not None and np.linalg.norm(c - centro) < raio + 2.0:
                centro = c
        a = dict(centro=centro, eixo=pn, raio=raio, altura_base=6.0, rms=float("nan"), volta=0.0, tipo="manual",
                 nome="Indicado à mão", confianca=1.0, nota_pe=1.0, nota_corpo=1.0, isolado=1.0, altura=60.0,
                 raio_max=max(14.0, raio + 4.0), medido=None, votos=0.0, soltos=[], seguro=True, deformado=False, manual=True)
        self.det["alvos"].append(a)
        self.escolha.append(len(self.det["alvos"]) - 1)
        self._dar_soltos(len(self.det["alvos"]) - 1)
        self._lista_mudou()
        return len(self.det["alvos"]) - 1

    def _dar_soltos(self, i):
        """Os pedaços soltos sem dono que estão no espaço do alvo i (indicado à mão) passam a ser dele."""
        a = self.det["alvos"][i]
        a["soltos"] = []
        for k, s in enumerate(self.det["soltos"]):
            if s.get("alvo") is None:
                d = s["centro"] - a["centro"]
                h = float(d @ a["eixo"])
                if -8.0 < h < 80.0 and np.linalg.norm(d - h * a["eixo"]) < 34.0:
                    s["alvo"] = i
                    a["soltos"].append(k)

    def esquecer(self, i):
        """Tira da lista um alvo indicado à mão."""
        alvos_ = self.det["alvos"]
        if not (0 <= i < len(alvos_)) or not alvos_[i].get("manual"):
            raise ValueError("Só dá para apagar da lista um alvo indicado à mão.")
        self.det["alvos"] = [a for k, a in enumerate(alvos_) if k != i]
        self.escolha = [k if k < i else k - 1 for k in self.escolha if k != i]
        for s in self.det["soltos"]:                       # os pedaços soltos dele voltam a não ter dono
            dono = s.get("alvo")
            if dono is not None:
                s["alvo"] = None if dono == i else (dono - 1 if dono > i else dono)
        self._lista_mudou()

    def _lista_mudou(self):
        self.limpa = None
        self.versao_alvos += 1
        self.versao_limpa += 1

    # ------------------------------------------------------------------ retirada dos alvos
    def limpar(self, escolha=None, opcoes=None):
        if escolha is not None:
            n = len(self.det["alvos"])
            self.escolha = sorted({int(i) for i in escolha if 0 <= int(i) < n})
        if opcoes:
            for ch in ("margem", "alcance"):
                if opcoes.get(ch) is not None:
                    self.opcoes[ch] = float(opcoes[ch])
            if "remover_soltos" in opcoes:
                self.opcoes["remover_soltos"] = bool(opcoes["remover_soltos"])
        if not (0.0 <= self.opcoes["margem"] <= 10.0):
            raise ValueError("A margem precisa ficar entre 0 e 10 mm.")
        if not (2.0 <= self.opcoes["alcance"] <= 30.0):
            raise ValueError("O alcance precisa ficar entre 2 e 30 mm.")
        t = time.time()
        self.limpa = limpeza.limpar(self.m, self.det, self.escolha, self.opcoes, log=self.log)
        self.limpa["tempo"] = time.time() - t
        self.versao_limpa += 1
        self.log(f"Malha limpa: {self.triangulos_limpa():,} triângulos".replace(",", "."))
        return self.limpa

    def desfazer(self):
        """Volta à malha com os alvos (a retirada é só uma máscara: desfazer não custa nada)."""
        if self.limpa is None:
            raise ValueError("Os alvos ainda não foram retirados.")
        self.limpa = None
        self.versao_limpa += 1

    def triangulos_limpa(self):
        return None if self.limpa is None else self.m.n_faces - self.limpa["removidos"]

    # ------------------------------------------------------------------ gravação
    def salvar(self, pasta, base, itens, log=lambda t: None):
        """Grava a malha limpa. Devolve {item: caminho, ..., 'falhas': {item: motivo}}."""
        if self.limpa is None:
            raise ValueError("Retire os alvos antes de salvar a malha limpa.")
        out, falhas = {}, {}
        os.makedirs(pasta, exist_ok=True)
        viva = self.limpa["viva"]
        for k in itens:
            destino = os.path.join(pasta, base + NOMES[k])
            try:
                if os.path.exists(destino) and os.path.samefile(destino, self.caminho):
                    raise ValueError("o arquivo de saída seria a própria malha aberta")
                log(f"Gravando a malha limpa ({k.upper()})…")
                grava = malha.gravar_stl if k == "stl" else malha.gravar_ply
                out[k] = grava(self.m, destino, manter=viva, log=log)
            except OSError as e:
                falhas[k] = erro_de_arquivo(e)
            except Exception as e:
                falhas[k] = str(e) or type(e).__name__
        out["falhas"] = falhas
        return out

    # ------------------------------------------------------------------ o que a interface mostra
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
                soltos=len(a.get("soltos") or []), marcado=i in self.escolha, retirado=i in feitos and bool(r.get("retirado")),
                tentado=i in feitos, referencia=r.get("referencia"), aviso=r.get("aviso"), nota=r.get("nota"), removidos=r.get("removidos"),
                diametro=r.get("diametro")))
        n_limpa = self.triangulos_limpa()
        nv = self.m.n_vertices
        return dict(
            arquivo=os.path.basename(self.caminho), triangulos=self.m.n_faces, tamanho=self.tamanho, area=self.m.area,
            caixa=[[float(x) for x in lo], [float(x) for x in hi]], aresta=self.m.aresta_mediana(),
            frente=None if self.m.frente() is None else [float(x) for x in self.m.frente()],
            alvos=alvos_, soltos=len(det["soltos"]) if det else 0,
            soltos_sem_alvo=sum(1 for s in det["soltos"] if s.get("alvo") is None) if det else 0,
            opcoes=dict(self.opcoes), limpo=self.limpa is not None, triangulos_limpa=n_limpa,
            soltos_removidos=self.limpa["soltos_removidos"] if self.limpa else 0,
            tempo_analise=self.t_analise, tempo_limpeza=self.limpa.get("tempo") if self.limpa else None,
            tamanho_stl=84 + 50 * n_limpa if n_limpa is not None else None,
            # no PLY cada vértice é gravado uma vez: 12 bytes por vértice e 13 por triângulo
            tamanho_ply=int(13 * n_limpa + 12 * nv * (n_limpa / max(1, self.m.n_faces))) if n_limpa is not None else None,
            versoes=dict(alvos=self.versao_alvos, limpa=self.versao_limpa))

    def marcas(self):
        """Para cada triângulo da malha: 0 = peça, 1 = pedaço solto sem dono, 2+i = alvo i (com os pedaços dele)."""
        m, det = self.m, self.det
        marca = np.zeros(m.n_faces, np.uint16)
        if det is None:
            return marca
        for s in det["soltos"]:
            marca[s["faces"]] = 1
        g = m.grade()
        for i, a in enumerate(det["alvos"]):
            c, e = a["centro"], a["eixo"]
            idx = g.bola(c + e * (a["altura"] / 2), a["altura"] / 2 + a["raio_max"] + 22.0)
            if len(idx):
                Q = m.centros(idx) - c
                h = Q @ e
                rho = np.linalg.norm(Q - np.outer(h, e), axis=1)
                pe = (h > 0.35) & (h <= 2.0 + a.get("altura_base", 6.0)) & (rho < a["raio"] + 0.8)
                dentro = pe | ((h > 2.0) & (h < a["altura"] + 8.0) & (rho < a["raio_max"] + 3.0 + 0.3 * np.maximum(h, 0)))
                # do que cai dentro do espaço do alvo, só o que está ligado ao pé: a palheta vizinha que passa por
                # ali não é do alvo, não vai sair e não pode aparecer pintada
                k = np.flatnonzero(dentro)
                if pe.any() and len(k):
                    liga = limpeza.ligados(m.F[idx[k]], pe[k])
                    dentro[k[~liga]] = False
                marca[idx[dentro]] = 2 + i
            for k in a.get("soltos") or []:
                marca[det["soltos"][k]["faces"]] = 2 + i
        return marca

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


_BLOCO = 1_000_000


def reduzir_para_tela(V, F, area, mv=None, fino=None, medio=None, cel_medio=1.0, alvo=1_200_000):
    """Reduz uma malha para a tela por agrupamento de vértices: os vértices de cada célula de uma grade viram um só,
    no centro deles. Três tratamentos: os vértices marcados em `fino` ficam como estão (em volta do pé de cada alvo a
    tela mostra todos os triângulos, e o furo aparece exato); os marcados em `medio` (o corpo dos alvos) são juntados
    em células pequenas, de `cel_medio` mm; o resto, em células do tamanho que faz a peça caber em `alvo` triângulos.
    `mv`: marca por vértice, levada ao grupo (a maior).
    Devolve (V float32, F int32, mv, origem: de que triângulo de F veio cada triângulo da tela)."""
    nv, nf = len(V), len(F)
    if nf <= alvo:
        return np.ascontiguousarray(V, np.float32), F, mv, np.arange(nf, dtype=np.int32)
    cel = math.sqrt(2.0 * area / alvo)
    ids = np.flatnonzero(fino) if fino is not None else np.zeros(0, np.int64)
    idm = np.flatnonzero(medio & ~fino) if (medio is not None and fino is not None) else (np.flatnonzero(medio) if medio is not None else np.zeros(0, np.int64))
    lo = V.min(0).astype(np.float64)
    especial = np.zeros(nv, bool)
    especial[ids] = True
    especial[idm] = True

    def celulas(P, c):
        q = np.floor((P - lo) / c).astype(np.int64)
        return (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]

    inv = None
    for volta in range(5):
        chave = np.empty(nv, np.int64)
        for i in range(0, nv, 4 * _BLOCO):
            chave[i:i + 4 * _BLOCO] = celulas(V[i:i + 4 * _BLOCO], cel)
        if len(idm):
            chave[idm] = (1 << 61) | celulas(V[idm], min(cel_medio, cel))
        chave[ids] = (1 << 62) + np.arange(len(ids), dtype=np.int64)     # vértice mantido = grupo só dele
        u, inv = np.unique(chave, return_inverse=True)
        del chave
        inv = inv.astype(np.int32).ravel()
        ng = len(u)
        del u
        # Quantos triângulos sobram com esta célula, fora os dos alvos? (Malha com triângulos de tamanhos muito
        # diferentes junta menos do que a conta pela área prevê: a célula cresce até caber.)
        sobra, dos_alvos = 0, 0
        for i in range(0, nf, _BLOCO):
            f = F[i:i + _BLOCO]
            g = inv[f]
            fica = (g[:, 0] != g[:, 1]) & (g[:, 1] != g[:, 2]) & (g[:, 0] != g[:, 2])
            esp = especial[f].all(axis=1)
            sobra += int(np.count_nonzero(fica & ~esp))
            dos_alvos += int(np.count_nonzero(fica & esp))
        # os triângulos dos alvos não diminuem com a célula: a peça fica com o que sobra da conta, e no mínimo metade
        cabe = max(1.25 * alvo - dos_alvos, 0.6 * alvo)
        if sobra <= cabe or volta == 4:
            break
        cel *= min(2.0, math.sqrt(sobra / (cabe / 1.25)))
    cont = np.bincount(inv, minlength=ng)
    Vn = np.empty((ng, 3), np.float32)
    for e in range(3):
        Vn[:, e] = np.bincount(inv, weights=V[:, e], minlength=ng) / np.maximum(cont, 1)
    Fn, origem = [], []
    for i in range(0, nf, _BLOCO):
        f = F[i:i + _BLOCO]
        g = inv[f]
        k = np.flatnonzero((g[:, 0] != g[:, 1]) & (g[:, 1] != g[:, 2]) & (g[:, 0] != g[:, 2]))
        if not len(k):
            continue
        g = g[k]
        # triângulo que virou do avesso ao juntar vértices apareceria como uma lasca escura: fica de fora
        T0 = V[f[k]].astype(np.float64)
        T1 = Vn[g].astype(np.float64)
        n0 = np.cross(T0[:, 1] - T0[:, 0], T0[:, 2] - T0[:, 0])
        n1 = np.cross(T1[:, 1] - T1[:, 0], T1[:, 2] - T1[:, 0])
        bom = np.einsum("ij,ij->i", n0, n1) > 0
        Fn.append(g[bom])
        origem.append((k[bom] + i).astype(np.int32))
    Fn = np.concatenate(Fn) if Fn else np.zeros((0, 3), np.int32)
    origem = np.concatenate(origem) if origem else np.zeros(0, np.int32)
    if mv is not None:
        mvn = np.zeros(ng, np.uint16)
        com = np.flatnonzero(mv)
        np.maximum.at(mvn, inv[com], mv[com])
        mv = mvn
    return Vn, Fn, mv, origem


def telas(s, alvo=1_200_000, leve=150_000):
    """As duas malhas da tela (a cheia, parada; a leve, enquanto a vista gira), com as marcas dos alvos.
    Devolve dict(cheia=bytes, leve=bytes ou None, origem, origem_leve)."""
    m = s.m
    marca = s.marcas()
    com = np.flatnonzero(marca)
    mv = np.zeros(m.n_vertices, np.uint16)
    for k in range(3):
        np.maximum.at(mv, m.F[com, k], marca[com])
    del marca
    # em volta do pé (onde fica o furo), todos os triângulos; no corpo do alvo e um pouco além, células pequenas
    medio = mv > 0
    fino = np.zeros(m.n_vertices, bool)
    g = m.grade()
    for a in (s.det["alvos"] if s.det else []):
        c, e = np.asarray(a["centro"], float), np.asarray(a["eixo"], float)
        medio[m.F[g.bola(c + e * 12.0, 26.0)].ravel()] = True
        fino[m.F[g.bola(c, float(a["raio"]) + 10.0)].ravel()] = True
    V, F, mvc, origem = reduzir_para_tela(m.V, m.F, m.area, mv, fino, medio, max(1.0, 1.5 * m.aresta_mediana()), alvo)
    cheia = _pacote(V, F, mvc, m.n_faces)
    pac_leve, origem_leve = None, None
    if len(F) > 2 * leve:
        Vl, Fl, mvl, o2 = reduzir_para_tela(V, F, m.area, mvc, None, None, 1.0, leve)
        pac_leve, origem_leve = _pacote(Vl, Fl, mvl, m.n_faces), origem[o2]
    return dict(cheia=cheia, leve=pac_leve, origem=origem, origem_leve=origem_leve)


def _pacote(V, F, mv, n_orig):
    lo, hi = (V.min(0), V.max(0)) if len(V) else (np.zeros(3), np.zeros(3))
    cab = dict(blocos={}, triangulos=int(len(F)), originais=int(n_orig), caixa=[lo.tolist(), hi.tolist()])
    return _empacotar(cab, [("V", np.ascontiguousarray(V, np.float32)), ("I", np.ascontiguousarray(F, np.uint32)),
                            ("M", mv.astype(np.uint16))])


def retirada_para_tela(s, t):
    """O resultado da retirada para a tela: por triângulo da tela, 1 se ele saiu (R para a malha cheia, S para a
    leve), e os lados do contorno dos furos (L: pares de pontos)."""
    viva = s.limpa["viva"]
    blocos = [("R", (~viva[t["origem"]]).astype(np.uint8))]
    if t["origem_leve"] is not None:
        blocos.append(("S", (~viva[t["origem_leve"]]).astype(np.uint8)))
    L = limpeza.contorno_do_corte(s.m, viva)
    blocos.append(("L", L.reshape(-1)))
    return _empacotar(dict(blocos={}, lados=int(len(L))), blocos)
