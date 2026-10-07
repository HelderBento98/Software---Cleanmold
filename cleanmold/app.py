"""Fluxo do Cleanmold: abrir a malha, otimizar, achar os alvos, retirá-los, reparar e gravar os arquivos.

A sessão guarda duas malhas: a de ANTES (como foi aberta, com os alvos; as ferramentas mexem nela enquanto os alvos
não foram retirados) e a de DEPOIS (o resultado da retirada dos alvos; daí em diante as ferramentas mexem nela).
Cada operação troca a malha por uma nova e guarda a anterior para desfazer."""
import json
import math
import os
import struct
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

from . import __version__, ajuste, alvos, limpeza, malha, otimizar, reparo

ITENS = ("stl", "ply", "pdf", "html", "csv", "step", "macro")
DESFAZER_NIVEIS = 6
DESFAZER_TRIANGULOS = 30_000_000          # soma dos triângulos das malhas guardadas para desfazer
BYTES_POR_TRIANGULO = 340                 # pico de memória da análise, por triângulo (medido)
BYTES_CARGA = 130                         # pico de memória só para abrir, por triângulo
SUGERIR_OTIMIZAR = 4_000_000              # a partir daqui a abertura pergunta se é para otimizar


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
    sem ler), tamanho, precisa, livre, total, grande, apertado, nao_cabe)."""
    tam = os.path.getsize(caminho)
    n = malha.contar_triangulos(caminho)
    estimado = n if n else int(tam / (50 if caminho.lower().endswith(".stl") else 22))
    total, livre = memoria()
    precisa = estimado * BYTES_POR_TRIANGULO
    d = dict(triangulos=n, estimado=estimado, tamanho=tam, precisa=precisa, livre=livre, total=total,
             grande=estimado >= SUGERIR_OTIMIZAR, apertado=False, nao_cabe=False, otimizar=otimizar.disponivel())
    if livre:
        d["apertado"] = precisa > 0.65 * livre                       # abrir inteira deve travar o computador
        d["nao_cabe"] = estimado * BYTES_CARGA > 0.85 * livre        # nem para otimizar na abertura
    return d


class Sessao:
    """Uma malha aberta e o que já foi feito com ela."""

    def __init__(self, caminho, log=lambda s: None, otimizar_tol=None):
        self.caminho = caminho
        self.log = log
        log(f"Lendo a malha {os.path.basename(caminho)}")
        self.m = malha.carregar(caminho)
        log(f"{self.m.n_faces:,} triângulos".replace(",", "."))
        self.original = dict(triangulos=self.m.n_faces, tamanho=os.path.getsize(caminho))
        self.det = None
        self.limpa = None            # resultado de limpeza.limpar (dict com malha, remendo, relatorio…)
        self.rem_m = None            # triângulos de remendo na malha de antes (reparos feitos antes de retirar os alvos)
        self.opcoes = dict(limpeza.OPCOES)
        self.escolha = []            # alvos marcados para retirar
        self.t_analise = None
        self.selecao = None          # dict(fase, mascara) da seleção do pincel
        self.historico = []          # estados anteriores, para desfazer
        self.otimizacao = None       # resultado da última otimização
        self.edicoes = []            # o que foi feito à mão, para o relatório
        self.diag = {}               # fase -> diagnóstico
        self.solido = None
        self.solido_erro = None
        self.versao = dict(antes=1, depois=0)      # muda quando a malha da fase muda
        if otimizar_tol:
            nova, info = otimizar.reduzir(self.m, otimizar_tol, log=log)
            self.m = nova
            self.otimizacao = dict(info, fase="antes", na_abertura=True)
            self.edicoes.append(dict(tipo="otimizar", texto=_texto_otimizacao(info)))

    # ------------------------------------------------------------------ malhas e fases
    def fase_de_edicao(self):
        return "depois" if self.limpa is not None else "antes"

    def malha_de(self, fase):
        if fase == "depois":
            if self.limpa is None:
                raise ValueError("A malha ainda não foi limpa.")
            return self.limpa["malha"]
        return self.m

    def atual(self):
        return self.malha_de(self.fase_de_edicao())

    def _fase(self, fase):
        """Confere se a fase pedida é a que as ferramentas editam agora."""
        certa = self.fase_de_edicao()
        if fase not in (None, certa):
            if certa == "depois":
                raise ValueError("Os alvos já foram retirados: use as ferramentas na vista Depois (ou desfaça a retirada).")
            raise ValueError("A malha ainda não foi limpa.")
        return certa

    # ------------------------------------------------------------------ desfazer
    def _guardar(self, descricao):
        self.historico.append(dict(
            descricao=descricao, m=self.m, det=None if self.det is None else dict(self.det, alvos=list(self.det["alvos"])),
            limpa=None if self.limpa is None else dict(self.limpa), rem_m=self.rem_m, escolha=list(self.escolha),
            otimizacao=self.otimizacao, edicoes=list(self.edicoes), solido=self.solido, solido_erro=self.solido_erro,
            opcoes=dict(self.opcoes)))
        # limite: níveis e memória
        while len(self.historico) > DESFAZER_NIVEIS:
            self.historico.pop(0)
        while len(self.historico) > 1 and self._triangulos_guardados() > DESFAZER_TRIANGULOS:
            self.historico.pop(0)

    def _triangulos_guardados(self):
        vistos, n = {id(self.m)}, 0
        if self.limpa is not None:
            vistos.add(id(self.limpa["malha"]))
        for h in self.historico:
            for mm in (h["m"], h["limpa"]["malha"] if h["limpa"] else None):
                if mm is not None and id(mm) not in vistos:
                    vistos.add(id(mm))
                    n += mm.n_faces
        return n

    def pode_desfazer(self):
        return self.historico[-1]["descricao"] if self.historico else None

    def desfazer(self):
        if not self.historico:
            raise ValueError("Não há nada para desfazer.")
        h = self.historico.pop()
        mudou_antes = h["m"] is not self.m
        mudou_depois = (h["limpa"] is None) != (self.limpa is None) or (h["limpa"] is not None and h["limpa"]["malha"] is not self.limpa["malha"])
        self.m, self.det, self.limpa, self.rem_m = h["m"], h["det"], h["limpa"], h["rem_m"]
        self.escolha, self.otimizacao, self.edicoes = h["escolha"], h["otimizacao"], h["edicoes"]
        self.solido, self.solido_erro, self.opcoes = h["solido"], h["solido_erro"], h["opcoes"]
        self.selecao = None
        self.diag = {}
        if mudou_antes:
            self.versao["antes"] += 1
        if mudou_depois or self.limpa is None:
            self.versao["depois"] += 1
        return h["descricao"]

    # ------------------------------------------------------------------ análise
    def analisar(self):
        t = time.time()
        manuais = [a for a in (self.det["alvos"] if self.det else []) if a.get("manual")]
        self.det = alvos.detectar(self.m, log=self.log)
        self.det["alvos"] += manuais
        self.escolha = [i for i, a in enumerate(self.det["alvos"]) if a["seguro"]]
        self.limpa = None
        self.selecao = None
        self.t_analise = time.time() - t
        self.versao["antes"] += 1
        self.versao["depois"] += 1
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
        if "grade" not in self.m._cache:
            self.log("Indexando a malha…")
        idx = self.m.grade().bola(ponto, raio + 20.0)
        idx = idx[self.det["eh_peca"][idx]] if len(idx) else idx
        if len(idx) < 30:
            raise ValueError("Não há superfície da peça suficiente em volta do ponto clicado.")
        C, N, A = self.m.C[idx].astype(float), self.m.N[idx].astype(float), self.m.A[idx]
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
        self.versao["antes"] += 1
        self.versao["depois"] += 1
        return len(self.det["alvos"]) - 1

    # ------------------------------------------------------------------ retirada dos alvos
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
        self._guardar("a retirada dos alvos")
        t = time.time()
        self.limpa = limpeza.limpar(self.m, self.det, self.escolha, self.opcoes, log=self.log)
        self.limpa["tempo"] = time.time() - t
        ml = self.limpa["malha"]
        # remendos feitos à mão antes da retirada continuam marcados na malha limpa (casados pelo centro do triângulo)
        if self.rem_m is not None and self.rem_m.any():
            g = ml.grade()
            marc = np.flatnonzero(self.rem_m)
            for i in range(0, len(marc), 2000):
                for f in marc[i:i + 2000]:
                    idx = g.bola(self.m.C[f], 1e-4)
                    self.limpa["remendo"][idx] = True
        self.selecao = None
        self.diag.pop("depois", None)
        self.solido = None
        self.solido_erro = None
        self.versao["depois"] += 1
        self.log(f"Malha limpa: {ml.n_faces:,} triângulos".replace(",", "."))
        return self.limpa

    # ------------------------------------------------------------------ edição: aplicar uma malha nova
    def _aplicar(self, fase, nova, origem=None, novos=None, redetectar=False):
        """Troca a malha da fase por `nova`. `origem`: de que triângulo antigo veio cada um (-1 e menores = novo);
        None = a malha mudou por inteiro. `novos`: máscara dos triângulos de remendo."""
        if fase == "antes":
            velha = self.m
            n_velha = velha.n_faces
            self.m = nova
            rem = np.zeros(nova.n_faces, bool)
            if origem is not None:
                veio = origem >= 0
                if self.rem_m is not None:
                    rem[veio] = self.rem_m[origem[veio]]
                if novos is not None:
                    rem |= novos
                if self.det is not None:
                    eh = np.ones(nova.n_faces, bool)
                    eh[veio] = self.det["eh_peca"][origem[veio]]
                    pos = np.full(n_velha, -1, np.int64)
                    pos[origem[veio]] = np.flatnonzero(veio)
                    soltos = []
                    for s in self.det["soltos"]:
                        f = pos[s["faces"]]
                        soltos.append(dict(s, faces=f[f >= 0]))
                    self.det = dict(self.det, eh_peca=eh, soltos=soltos, alvos=list(self.det["alvos"]))
            else:
                if self.rem_m is not None and self.rem_m.any():
                    rem = otimizar.transferir_marca(velha, self.rem_m, nova)
                if self.det is not None:
                    redetectar = True
            self.rem_m = rem if rem.any() else None
            self.versao["antes"] += 1
            if redetectar and self.det is not None:
                self.log("Procurando os alvos na malha nova…")
                marcados = {i for i in self.escolha}
                antigos = self.det["alvos"]
                manuais = [a for a in antigos if a.get("manual")]
                self.det = alvos.detectar(self.m, log=lambda s: None)
                self.det["alvos"] += manuais
                # quem estava desmarcado continua desmarcado (casado pela posição do pé)
                desm = [a["centro"] for i, a in enumerate(antigos) if i not in marcados and a["seguro"]]
                self.escolha = []
                for i, a in enumerate(self.det["alvos"]):
                    perto = any(np.linalg.norm(np.asarray(c) - a["centro"]) < 4.0 for c in desm)
                    if a["seguro"] and not perto:
                        self.escolha.append(i)
                for ch in ("arestas", "viz", "gf", "bordas"):
                    self.m._cache.pop(ch, None)
        else:
            velha = self.limpa["malha"]
            lim = dict(self.limpa)
            rem = np.zeros(nova.n_faces, bool)
            if origem is not None:
                veio = origem >= 0
                rem[veio] = lim["remendo"][origem[veio]]
                if novos is not None:
                    rem |= novos
            else:
                rem = otimizar.transferir_marca(velha, lim["remendo"], nova)
            lim["malha"], lim["remendo"] = nova, rem
            self.limpa = lim
            self.versao["depois"] += 1
        velha.enxuta()
        self.selecao = None
        self.diag.pop(fase, None)
        self.solido = None
        self.solido_erro = None

    # ------------------------------------------------------------------ otimizar
    def otimizar(self, tolerancia, fase=None):
        fase = self._fase(fase)
        m = self.malha_de(fase)
        nova, info = otimizar.reduzir(m, tolerancia, log=self.log)
        if nova.n_faces >= 0.97 * m.n_faces:
            self.log("A malha já está enxuta para essa tolerância.")
            return dict(info, sem_ganho=True)
        self._guardar("a otimização")
        self._aplicar(fase, nova, None, None)
        self.otimizacao = dict(info, fase=fase)
        self.edicoes.append(dict(tipo="otimizar", texto=_texto_otimizacao(info)))
        return self.otimizacao

    # ------------------------------------------------------------------ seleção
    def pintar(self, fase, pinceladas):
        fase = self._fase(fase)
        m = self.malha_de(fase)
        atual = self.selecao["mascara"] if self.selecao and self.selecao["fase"] == fase and len(self.selecao["mascara"]) == m.n_faces else None
        mascara = reparo.pintar(m, atual, pinceladas)
        self.selecao = dict(fase=fase, mascara=mascara) if mascara.any() else None
        return self.selecao

    def mudar_selecao(self, acao):
        if not self.selecao:
            return None
        fase = self.selecao["fase"]
        m = self.malha_de(fase)
        if acao == "limpar":
            self.selecao = None
        elif acao in ("crescer", "encolher"):
            mk = reparo.crescer(m, self.selecao["mascara"], 1 if acao == "crescer" else -1)
            self.selecao = dict(fase=fase, mascara=mk) if mk.any() else None
        return self.selecao

    def info_selecao(self):
        if not self.selecao:
            return None
        m = self.malha_de(self.selecao["fase"])
        mk = self.selecao["mascara"]
        return dict(fase=self.selecao["fase"], triangulos=int(mk.sum()), area=float(m.A[mk].sum()))

    def _selecionados(self, fase):
        fase = self._fase(fase)
        if not self.selecao or self.selecao["fase"] != fase:
            raise ValueError("Nada selecionado. Pinte com o pincel a região.")
        return fase, self.malha_de(fase), self.selecao["mascara"]

    def apagar_selecao(self, fase=None, preencher=True):
        fase, m, mk = self._selecionados(fase)
        r = reparo.apagar(m, mk, preencher=preencher, soltos=True)
        self._guardar("a retirada da região pintada" if preencher else "o apagamento da região pintada")
        # alvo da lista cujo pé foi embora junto com a região pintada sai da lista (não há mais o que retirar ali)
        foram = []
        if fase == "antes" and self.det is not None and self.det["alvos"]:
            ficou = np.zeros(m.n_faces, bool)
            ficou[r["origem"][r["origem"] >= 0]] = True
            g = m.grade()
            for k, a in enumerate(self.det["alvos"]):
                idx = g.bola(np.asarray(a["centro"]) + np.asarray(a["eixo"]) * 3.0, float(a["raio"]) + 1.0)
                if len(idx) >= 10 and (~ficou[idx]).mean() > 0.5:
                    foram.append(k)
        self._aplicar(fase, r["malha"], r["origem"], r["novos"])
        if foram:
            novo_indice, alvos_ = {}, []
            for k, a in enumerate(self.det["alvos"]):
                if k not in foram:
                    novo_indice[k] = len(alvos_)
                    alvos_.append(a)
            self.det = dict(self.det, alvos=alvos_)
            self.escolha = [novo_indice[k] for k in self.escolha if k in novo_indice]
        i = r["info"]
        i["alvos_da_lista"] = len(foram)
        txt = f"Região pintada {'retirada e fechada' if preencher else 'apagada'}: {i['apagados'] + i['pendurados']} triângulos"
        if preencher and i["furos"]:
            txt += f", {i['fechados']} de {i['furos']} furos fechados" + (f" sobre {', '.join(sorted(set(i['referencias'])))}" if i["referencias"] else "")
        self.edicoes.append(dict(tipo="apagar", texto=txt, avisos=i["avisos"]))
        return i

    def alisar_selecao(self, fase=None, forca=2):
        fase, m, mk = self._selecionados(fase)
        r = reparo.alisar(m, mk, forca)
        self._guardar("o alisamento")
        self._aplicar(fase, r["malha"], np.arange(m.n_faces, dtype=np.int64), None)
        self.edicoes.append(dict(tipo="alisar", texto=f"Região alisada (intensidade {int(forca)}): {r['info']['vertices']} vértices, "
                                                      f"deslocamento máximo {r['info']['deslocamento_max']:.2f} mm".replace(".", ",")))
        return r["info"]

    # ------------------------------------------------------------------ furos
    def furos(self, fase=None):
        fase = self._fase(fase)
        return reparo.furos(self.malha_de(fase))

    def _resumo_furos(self, infos, quantos):
        ok = sum(1 for i in infos if i["preenchido"])
        avisos = sorted({i["aviso"] for i in infos if i.get("aviso")})
        refs = sorted({i["referencia"] for i in infos if i.get("referencia") and i["preenchido"]})
        return dict(pedidos=quantos, fechados=ok, abertos=quantos - ok, avisos=avisos, referencias=refs,
                    area=float(sum(i.get("area") or 0.0 for i in infos)),
                    degrau=max([i["degrau"] for i in infos if i.get("degrau") is not None], default=None))

    def preencher_furos(self, fase=None, ids=None, ate=None):
        """Fecha os furos de índices `ids` (na lista de furos()) ou todos os de diâmetro até `ate` mm."""
        fase = self._fase(fase)
        m = self.malha_de(fase)
        lac = reparo.furos(m)
        if ids is not None:
            escolhidos = [lac[i] for i in ids if 0 <= i < len(lac)]
        else:
            escolhidos = [f for f in lac if f["diametro"] <= float(ate)]
        if not escolhidos:
            raise ValueError("Nenhum furo para fechar com esse critério.")
        r = reparo.preencher_furos(m, [f["v"] for f in escolhidos], log=self.log)
        res = self._resumo_furos(r["infos"], len(escolhidos))
        if not res["fechados"]:
            raise ValueError("Não consegui fechar: " + ("; ".join(res["avisos"]) or "o contorno não permite") + ".")
        self._guardar("o fechamento de furos")
        self._aplicar(fase, r["malha"], r["origem"], r["novos"])
        self.edicoes.append(dict(tipo="furos", texto=f"{res['fechados']} furo(s) fechado(s)" + (f" sobre {', '.join(res['referencias'])}" if res["referencias"] else ""),
                                 avisos=res["avisos"]))
        return res

    def preencher_selecao(self, fase=None):
        """Fecha os vazios contornados pela seleção: furos inteiros, ou o trecho pintado de uma borda aberta."""
        fase, m, mk = self._selecionados(fase)
        sel_v = np.zeros(m.n_vertices, bool)
        sel_v[m.F[mk].ravel()] = True
        lac = [f for f in reparo.furos(m) if sel_v[f["v"]].sum() >= 3]
        if not lac:
            raise ValueError("A região pintada não encosta em nenhuma borda aberta. Pinte em volta do vazio, por cima da beirada dele.")
        # Um furo com a beirada pintada (mesmo só em parte) é fechado inteiro. Só o contorno grande, que é a borda da
        # peça num escaneamento de um lado só, é fechado apenas no trecho pintado.
        lo, hi = m.caixa()
        diag = float(np.linalg.norm(hi - lo))
        inteiros = [f for f in lac if f["diametro"] <= 0.3 * diag or sel_v[f["v"]].all()]
        trechos = [f for f in lac if not (f["diametro"] <= 0.3 * diag or sel_v[f["v"]].all())]
        infos = []
        nova, origem, novos = m, np.arange(m.n_faces, dtype=np.int64), np.zeros(m.n_faces, bool)
        if inteiros:
            r = reparo.preencher_furos(nova, [f["v"] for f in inteiros], log=self.log)
            infos += r["infos"]
            nova, origem, novos = r["malha"], r["origem"], r["novos"]
        if trechos:
            sv = np.zeros(nova.n_vertices, bool)
            sv[:len(sel_v)] = sel_v
            try:
                r = reparo.preencher_furos(nova, [f["v"] for f in trechos], sel_v=sv, log=self.log)
                infos += r["infos"]
                origem = reparo._compor(origem, r["origem"])
                novos = (novos[np.maximum(r["origem"], 0)] & (r["origem"] >= 0)) | r["novos"]
                nova = r["malha"]
            except IndexError:                                  # a numeração mudou no primeiro passo: o trecho fica para depois
                infos.append(dict(preenchido=False, aviso="o trecho da borda da peça ficou para uma segunda vez: pinte de novo", area=0.0, degrau=None))
        r = dict(malha=nova, origem=origem, novos=novos, infos=infos)
        res = self._resumo_furos(r["infos"], len(lac))
        if not res["fechados"]:
            raise ValueError("Não consegui fechar o vazio pintado: " + ("; ".join(res["avisos"]) or "o contorno não permite") + ".")
        self._guardar("o preenchimento do vazio pintado")
        self._aplicar(fase, r["malha"], r["origem"], r["novos"])
        self.edicoes.append(dict(tipo="furos", texto=f"Vazio pintado preenchido ({res['fechados']} contorno(s))"
                                 + (f" sobre {', '.join(res['referencias'])}" if res["referencias"] else ""), avisos=res["avisos"]))
        return res

    # ------------------------------------------------------------------ diagnóstico e reparo
    def diagnosticar(self, fase=None):
        fase = self._fase(fase)
        m = self.malha_de(fase)
        self.log("Examinando a malha…")
        d = reparo.diagnostico(m)
        if m.n_faces > 2_000_000:
            for ch in ("arestas", "viz", "gf"):
                m._cache.pop(ch, None)
        self.diag[fase] = d
        return d

    def reparar(self, fase=None, soltos=True, nao_variedade=True, orientar=True, furos_ate=None):
        fase = self._fase(fase)
        m = self.malha_de(fase)
        r = reparo.reparar(m, nao_variedade=nao_variedade, soltos=soltos, orientar=orientar, furos_ate=furos_ate, log=self.log)
        i = r["info"]
        if r["malha"] is m:
            self.diag.pop(fase, None)
            return dict(i, nada=True)
        self._guardar("o reparo automático")
        self._aplicar(fase, r["malha"], r["origem"], r["novos"])
        partes = []
        if i["nao_variedade"]:
            partes.append(f"{i['nao_variedade']} aresta(s) com três ou mais triângulos")
        if i["soltos"]:
            partes.append(f"{i['soltos']} pedaço(s) solto(s) apagado(s)")
        if i["virados"]:
            partes.append(f"{i['virados']} triângulo(s) desvirado(s)")
        if i["furos_fechados"]:
            partes.append(f"{i['furos_fechados']} furo(s) pequeno(s) fechado(s)")
        self.edicoes.append(dict(tipo="reparo", texto="Reparo automático: " + ("; ".join(partes) or "nada a corrigir")))
        return i

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
                soltos=len(a.get("soltos") or []), marcado=i in self.escolha, retirado=i in feitos,
                referencia=r.get("referencia"), sigma=r.get("sigma"), preenchido=r.get("preenchido"),
                aviso=r.get("aviso"), degrau=r.get("degrau"), area=r.get("area_remendo"),
                arestas=r.get("arestas_vivas")))
        ml = self.limpa["malha"] if self.limpa else None
        fase = self.fase_de_edicao()
        at = self.atual()
        return dict(
            arquivo=os.path.basename(self.caminho), triangulos=self.m.n_faces, area=self.m.area,
            caixa=[[float(x) for x in lo], [float(x) for x in hi]], aresta=self.m.aresta_mediana(),
            alvos=alvos_, soltos=len([s for s in det["soltos"] if len(s["faces"])]) if det else 0,
            soltos_sem_alvo=sum(1 for s in det["soltos"] if s.get("alvo") is None and len(s["faces"])) if det else 0,
            opcoes=dict(self.opcoes), limpo=self.limpa is not None,
            triangulos_limpa=ml.n_faces if ml else None,
            soltos_removidos=self.limpa["soltos_removidos"] if self.limpa else 0,
            tempo_analise=self.t_analise, tempo_limpeza=self.limpa.get("tempo") if self.limpa else None,
            # edição
            fase_edicao=fase, triangulos_atual=at.n_faces, tamanho_stl=84 + 50 * at.n_faces,
            original=dict(self.original), otimizacao=self.otimizacao, desfazer=self.pode_desfazer(),
            selecao=self.info_selecao(), edicoes=list(self.edicoes), diag=self.diag.get(fase),
            versoes=dict(self.versao), otimizar_disponivel=otimizar.disponivel(),
            editada=bool(self.edicoes))

    def marcas_antes(self):
        """Para cada triângulo da malha de antes: 0 = peça, 1 = pedaço solto, 2+i = alvo i, 65535 = remendo."""
        m, det = self.m, self.det
        marca = np.zeros(m.n_faces, np.uint16)
        if det is not None:
            for s in det["soltos"]:
                marca[s["faces"]] = 1
            if det["alvos"] and "grade" not in m._cache:
                self.log("Indexando a malha…")
            for i, a in enumerate(det["alvos"]):
                c, e = a["centro"], a["eixo"]
                idx = m.grade().bola(c + e * (a["altura"] / 2), a["altura"] / 2 + a["raio_max"] + 22.0)
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
        if self.rem_m is not None:
            marca[self.rem_m] = 65535
        return marca

    def marcas(self, fase):
        if fase == "antes":
            return self.marcas_antes()
        return self.limpa["remendo"].astype(np.uint16)

    def focos(self):
        """Regiões que a tela mostra com todos os triângulos (em volta de cada alvo): centros e raio."""
        if not self.det or not self.det["alvos"]:
            return np.zeros((0, 3)), 0.0
        return np.array([a["centro"] + a["eixo"] * 12.0 for a in self.det["alvos"]]), 26.0


def _texto_otimizacao(info):
    t = f"Malha otimizada: {info['antes']:,} → {info['depois']:,} triângulos".replace(",", ".")
    t += f" (tolerância {info['tolerancia']:.2f} mm".replace(".", ",")
    if info.get("desvio"):
        t += f"; desvio medido: médio {info['desvio']['medio']:.3f} mm, máximo {info['desvio']['maximo']:.3f} mm".replace(".", ",")
    return t + ")"


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


def malha_para_tela(m, marca=None, focos=None, raio_foco=0.0, alvo=1_200_000, fino_marcado=True):
    """Reduz a malha para a tela por agrupamento de vértices, mantendo todos os triângulos perto dos alvos.
    Cada grupo é representado por um vértice real da malha. `marca`: valor por triângulo, levado aos vértices
    (o maior valor entre os triângulos de cada vértice).
    Devolve (bytes [cabeçalho JSON + blocos V, I, M], mapa: vértice da malha -> vértice da tela, ou -1)."""
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
        if mv is not None and fino_marcado:
            fino |= mv > 0
        ids = np.flatnonzero(fino)
        lo_v = V.min(0)
        for _ in range(4):
            q = np.floor((V - lo_v) / cel).astype(np.int64)
            chave = (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]
            base = int(chave.max()) + 1
            chave[ids] = base + np.arange(len(ids))             # vértice mantido = grupo só dele
            _, inv, cont = np.unique(chave, return_inverse=True, return_counts=True)
            inv = inv.ravel()
            Fn = inv[F]
            ok = (Fn[:, 0] != Fn[:, 1]) & (Fn[:, 1] != Fn[:, 2]) & (Fn[:, 0] != Fn[:, 2])
            # malha já otimizada tem triângulos grandes onde é lisa e miúdos nos detalhes: a célula calculada pela
            # área junta menos do que devia; aumenta até caber no alvo
            sobra = float(ok.sum()) / alvo
            if sobra <= 1.25:
                break
            cel *= min(2.0, math.sqrt(sobra))
        centro = np.stack([np.bincount(inv, weights=V[:, k]) / cont for k in range(3)], axis=1)
        d2 = ((V - centro[inv]) ** 2).sum(1)
        ordem = np.lexsort((d2, inv))
        prim = ordem[np.flatnonzero(np.r_[True, inv[ordem][1:] != inv[ordem][:-1]])]
        Vn = V[prim]
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
        mapa = inv.astype(np.int32)
    else:
        usados = np.zeros(len(V), bool)
        usados[F.ravel()] = True
        mapa = np.arange(len(V), dtype=np.int32)
        if not usados.all():
            novo = np.cumsum(usados) - 1
            mapa = np.where(usados, novo, -1).astype(np.int32)
            V, F = V[usados], novo[F]
            if mv is not None:
                mv = mv[usados]
    lo, hi = V.min(0), V.max(0)
    cab = dict(blocos={}, triangulos=int(len(F)), originais=int(n_orig), caixa=[lo.tolist(), hi.tolist()])
    blocos = [("V", V.astype(np.float32)), ("I", F.astype(np.uint32))]
    if mv is not None:
        blocos.append(("M", mv.astype(np.uint16)))
    return _empacotar(cab, blocos), mapa


def selecao_para_tela(m, mascara, mapas):
    """Vértices da tela (um bloco por mapa) que pertencem a triângulos selecionados."""
    blocos = []
    v = np.unique(m.F[mascara]) if mascara is not None and mascara.any() else np.zeros(0, np.int64)
    for nome, mapa in mapas:
        ids = np.unique(mapa[v]) if len(v) else np.zeros(0, np.int64)
        blocos.append((nome, ids[ids >= 0].astype(np.uint32)))
    return blocos


def furos_para_tela(m, lac, limite=400):
    """Contornos dos furos para a tela: pontos (float32) e o início de cada contorno. E a lista com as medidas."""
    lo, hi = m.caixa()
    diag = float(np.linalg.norm(hi - lo))
    pts, ini, lista = [], [0], []
    for i, f in enumerate(lac):
        v = f["v"]
        if len(v) > limite:
            v = v[np.linspace(0, len(v) - 1, limite).astype(np.int64)]
        pts.append(m.V[v].astype(np.float32))
        ini.append(ini[-1] + len(v))
        lista.append(dict(i=i, vertices=int(len(f["v"])), perimetro=f["perimetro"], diametro=f["diametro"],
                          centro=[float(x) for x in f["centro"]], normal=[float(x) for x in f["normal"]],
                          borda=bool(f["diametro"] > 0.3 * diag)))
    P = np.vstack(pts) if pts else np.zeros((0, 3), np.float32)
    return _empacotar(dict(blocos={}, furos=lista), [("P", P), ("O", np.array(ini, np.uint32))])
