"""Localização dos alvos de escaneamento na malha.

O que se procura não é a malha exata de um alvo, e sim o padrão dele: um PÉ cilíndrico de raio conhecido
(a base magnética que encosta na peça) em pé sobre a superfície, e acima dele um corpo fino ou isolado
(pescoço, esfera, dodecaedro) cujo perfil de raios ao longo do eixo lembra o de um alvo da biblioteca.
O alvo escaneado pode vir amassado, com caroços ou partido em pedaços soltos: o pé é a parte que quase
sempre sai nítida, e é por ele que o alvo é achado e recortado."""
import json
import os
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from . import ajuste

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alvos")
PASSO_PERFIL = 1.0          # mm por fatia do perfil de raios


# ---------------------------------------------------------------------------
# biblioteca
# ---------------------------------------------------------------------------

class Tipo:
    """Um tipo de alvo: pé (raio e altura) e perfil de raios ao longo do eixo, a partir do plano de apoio."""

    def __init__(self, d):
        self.id = d["id"]
        self.nome = d["nome"]
        self.raio = float(d["raio_base"])
        self.altura_base = float(d["altura_base"])
        self.altura = float(d["altura"])
        self.raio_max = float(d["raio_max"])
        self.h = np.asarray(d["perfil_h"], float)               # centro de cada fatia
        self.rmax = np.asarray(d["perfil_rmax"], float)         # raio externo em cada fatia
        self.pe = float(d.get("zona_pe", self.altura_base + 8.0))   # até onde vai a zona que decide (pé + começo do corpo)
        self.esferas = [tuple(e) for e in d.get("esferas") or []]   # (altura do centro, raio)
        self.h_dodecaedro = d.get("h_dodecaedro")
        self.dados = d


def biblioteca():
    with open(os.path.join(PASTA, "biblioteca.json"), encoding="utf-8") as fh:
        return [Tipo(d) for d in json.load(fh)["tipos"]]


# ---------------------------------------------------------------------------
# votação: eixos de cilindros de raio r
# ---------------------------------------------------------------------------

def _celulas(Q, g, desloc):
    q = np.floor(Q / g + desloc).astype(np.int64)
    q -= q.min(0)
    chave = (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]
    return np.unique(chave, return_inverse=True, return_counts=True)


def votar_cilindros(P, N, raio, passo, g=1.5, fracao=0.3):
    """Cada ponto da superfície vota no ponto que fica `raio` para dentro, ao longo da normal. Na parede de um
    cilindro desse raio os votos caem todos sobre o eixo, vindos de normais espalhadas em roda: é isso que
    separa um pé de alvo de um plano (uma direção só) ou de uma aresta arredondada (um quarto de volta).
    Devolve uma lista de candidatos dict(centro, eixo, votos)."""
    Q = P - raio * N
    esperado = 2 * np.pi * raio * g / (passo * passo)           # votos por célula ao longo do eixo de um cilindro inteiro
    minimo = max(12.0, fracao * esperado)
    cands = []
    for desloc in (0.0, 0.5):
        _, inv, cont = _celulas(Q, g, desloc)
        forte = np.flatnonzero(cont >= minimo)
        if not len(forte):
            continue
        mapa = np.full(len(cont), -1, np.int64)
        mapa[forte] = np.arange(len(forte))
        ii = mapa[inv]
        sel = ii >= 0
        ii, Ns, Qs = ii[sel], N[sel], Q[sel]
        k = len(forte)
        S = np.empty((k, 3, 3))
        c = np.empty((k, 3))
        for a in range(3):
            c[:, a] = np.bincount(ii, weights=Qs[:, a], minlength=k)
            for b in range(a, 3):
                S[:, a, b] = S[:, b, a] = np.bincount(ii, weights=Ns[:, a] * Ns[:, b], minlength=k)
        n = cont[forte].astype(float)
        c /= n[:, None]
        S /= n[:, None, None]
        w, v = np.linalg.eigh(S)
        ok = (w[:, 0] < 0.10) & (w[:, 1] > 0.25)                # normais num plano, bem espalhadas nele
        for i in np.flatnonzero(ok):
            cands.append(dict(centro=c[i], eixo=v[i, :, 0], votos=float(n[i])))
    return cands


def votar_esferas(P, N, raio, passo, g=2.0, fracao=0.15):
    """Como votar_cilindros, mas para esferas: os votos caem no centro, vindos de normais em todas as direções."""
    Q = P - raio * N
    esperado = 4 * np.pi * raio * raio / (passo * passo)
    minimo = max(20.0, fracao * esperado)
    cands = []
    for desloc in (0.0, 0.5):
        _, inv, cont = _celulas(Q, g, desloc)
        forte = np.flatnonzero(cont >= minimo)
        if not len(forte):
            continue
        mapa = np.full(len(cont), -1, np.int64)
        mapa[forte] = np.arange(len(forte))
        ii = mapa[inv]
        sel = ii >= 0
        ii, Ns, Qs = ii[sel], N[sel], Q[sel]
        k = len(forte)
        S = np.empty((k, 3, 3))
        c = np.empty((k, 3))
        for a in range(3):
            c[:, a] = np.bincount(ii, weights=Qs[:, a], minlength=k)
            for b in range(a, 3):
                S[:, a, b] = S[:, b, a] = np.bincount(ii, weights=Ns[:, a] * Ns[:, b], minlength=k)
        n = cont[forte].astype(float)
        c /= n[:, None]
        S /= n[:, None, None]
        w = np.linalg.eigvalsh(S)
        for i in np.flatnonzero(w[:, 0] > 0.13):
            cands.append(dict(centro=c[i], eixo=np.array([0, 0, 1.0]), votos=float(n[i])))
    return cands


def _agrupar(cands, dist):
    """Junta candidatos vizinhos (o mesmo eixo aparece em várias células). Fica o de mais votos de cada grupo."""
    if not cands:
        return []
    C = np.array([c["centro"] for c in cands])
    pares = cKDTree(C).query_pairs(dist, output_type="ndarray")
    g = sparse.coo_matrix((np.ones(len(pares)), (pares[:, 0], pares[:, 1])), shape=(len(C), len(C)))
    n, rot = csgraph.connected_components(g, directed=False)
    votos = np.array([c["votos"] for c in cands])
    out = []
    for k in range(n):
        idx = np.flatnonzero(rot == k)
        m = idx[np.argmax(votos[idx])]
        e0 = cands[m]["eixo"]
        E = np.array([cands[i]["eixo"] * (1 if cands[i]["eixo"] @ e0 >= 0 else -1) for i in idx])
        w = votos[idx]
        eixo = (E * w[:, None]).sum(0)
        out.append(dict(centro=(C[idx] * w[:, None]).sum(0) / w.sum(), eixo=eixo / np.linalg.norm(eixo), votos=float(w.sum())))
    return out


# ---------------------------------------------------------------------------
# pé: cilindro ajustado, lado da peça e plano de apoio
# ---------------------------------------------------------------------------

def _cilindricas(P, c, a):
    Q = P - c
    z = Q @ a
    R = Q - np.outer(z, a)
    return z, np.linalg.norm(R, axis=1), R


def ajustar_pe(arv, P, N, cand, raio, tol=0.12):
    """Refina um candidato: cilindro por mínimos quadrados, extensão ao longo do eixo, volta coberta, de que
    lado está a peça e a que altura fica a superfície de apoio. Devolve dict ou None se não for um pé."""
    c, a = np.asarray(cand["centro"], float), np.asarray(cand["eixo"], float)
    r = raio
    idx = np.asarray(arv.query_ball_point(c, raio + 9.0))
    if len(idx) < 30:
        return None
    Pl, Nl = P[idx], N[idx]
    apoio = None
    for volta in range(3):
        z, rho, R = _cilindricas(Pl, c, a)
        radial = np.einsum("ij,ij->i", Nl, R) / np.maximum(rho, 1e-9)
        apoio = (np.abs(rho - r) < (1.6 if volta == 0 else 0.9)) & (np.abs(Nl @ a) < 0.45) & (radial > 0.6) & (np.abs(z) < 7.0)
        if apoio.sum() < 25:
            return None
        try:
            c, a, r, rms = ajuste.cilindro(Pl[apoio], a, c, r)
        except Exception:
            return None
        if abs(r - raio) > tol * raio + 0.4:
            return None
        zc = np.median(((Pl[apoio] - c) @ a))
        c = c + zc * a
    z, rho, R = _cilindricas(Pl, c, a)
    radial = np.einsum("ij,ij->i", Nl, R) / np.maximum(rho, 1e-9)
    apoio = (np.abs(rho - r) < 0.7) & (np.abs(Nl @ a) < 0.45) & (radial > 0.6) & (np.abs(z) < 7.0)
    if apoio.sum() < 25:
        return None
    za = z[apoio]
    z0, z1 = np.percentile(za, [3, 97])
    e1, e2, _ = ajuste.base_ortonormal(a)
    ang = np.arctan2(R[apoio] @ e2, R[apoio] @ e1)
    volta_coberta = len(np.unique(np.floor((ang + np.pi) / (2 * np.pi) * 36).astype(int) % 36)) / 36.0
    # peça: superfície logo fora do pé, virada para o lado do alvo. (Num dado com base, as faces de baixo do
    # dodecaedro também ficam em volta do pé, mas viradas para o outro lado: não contam como peça.)
    anel = (rho > r + 1.2) & (rho < r + 5.0) & (z > z0 - 5.0) & (z < z1 + 5.0)
    if anel.sum() < 15:
        return None
    meio = (z0 + z1) / 2
    na = Nl @ a
    abaixo = int(np.sum(anel & (z < meio) & (na > 0.6)))
    acima = int(np.sum(anel & (z >= meio) & (na < -0.6)))
    if acima > abaixo:                                         # a peça fica do lado de z positivo: inverte o eixo
        a = -a
        z, z0, z1, na = -z, -z1, -z0, -na
        meio = -meio
        abaixo, acima = acima, abaixo
    perto = anel & (rho < r + 4.0) & (z < meio) & (na > 0.6)
    if perto.sum() < 8:
        return None
    # altura do apoio no centro do pé: superfície de 2º grau ajustada ao anel (num eixo ou num furo a peça
    # é curva, e a média do anel ficaria abaixo ou acima do ponto de contato)
    e1, e2, _ = ajuste.base_ortonormal(a)
    u, v, w = R[perto] @ e1, R[perto] @ e2, z[perto]
    A = np.c_[np.ones(len(u)), u, v, u * u, u * v, v * v] if perto.sum() >= 30 else np.ones((len(u), 1))
    pesos = np.ones(len(u))
    k = np.zeros(A.shape[1])
    k[0] = np.median(w)
    for _ in range(6):
        k, *_ = np.linalg.lstsq(A * pesos[:, None], w * pesos, rcond=None)
        res = w - A @ k
        sc = 1.4826 * np.median(np.abs(res)) + 0.02
        pesos = 1.0 / (1.0 + (res / (2.5 * sc)) ** 2)
    zb = float(k[0])
    if not (np.percentile(w, 5) - 6.0 < zb < np.percentile(w, 95) + 6.0):
        zb = float(np.median(w))
    return dict(centro=c + zb * a, eixo=a, raio=float(r), rms=float(rms), altura=float(z1 - zb), z0=float(z0 - zb),
                apoio=int(apoio.sum()), volta=float(volta_coberta), pureza=float(abaixo) / max(1, anel.sum()),
                votos=cand["votos"])


def perfil(arv, P, pe, altura=70.0, raio=24.0, passo=PASSO_PERFIL):
    """Raio externo da malha em cada fatia de altura acima do plano de apoio (h, rmax, nº de pontos)."""
    c, a = pe["centro"], pe["eixo"]
    meio = c + a * (altura / 2)
    idx = np.asarray(arv.query_ball_point(meio, np.hypot(altura / 2 + 2, raio)))
    h = np.arange(passo / 2, altura, passo)
    if not len(idx):
        return h, np.full(len(h), np.nan), np.zeros(len(h), int)
    z, rho, _ = _cilindricas(P[idx], c, a)
    ok = (rho < raio) & (z > 0) & (z < altura)
    k = (z[ok] / passo).astype(int)
    rm = np.full(len(h), np.nan)
    n = np.bincount(k, minlength=len(h))[:len(h)]
    ordem = np.argsort(k, kind="stable")
    ks, rs = k[ordem], rho[ok][ordem]
    lim = np.searchsorted(ks, np.arange(len(h) + 1))
    for i in range(len(h)):
        if lim[i + 1] - lim[i] >= 4:
            rm[i] = np.percentile(rs[lim[i]:lim[i + 1]], 92)
    return h, rm, n


# ---------------------------------------------------------------------------
# o perfil medido lembra o de um tipo da biblioteca?
# ---------------------------------------------------------------------------

TOL_PERFIL = 1.6            # mm de diferença de raio aceitos em cada fatia (alvo amassado, caroço, ruído)
FOSSO = 4.0                 # largura da faixa em volta do alvo que deve estar vazia


def comparar(arv, P, pe, tipo):
    """Compara a malha em volta de um pé com o perfil de um tipo de alvo.
    Devolve dict(pe=nota da zona do pé 0..1, corpo=nota do resto, isolado=0..1, medido=raios por fatia)."""
    c, a = pe["centro"], pe["eixo"]
    alt = tipo.altura
    alcance = tipo.raio_max + 2.5 + FOSSO
    idx = np.asarray(arv.query_ball_point(c + a * (alt / 2), np.hypot(alt / 2 + 1, alcance)))
    n = len(tipo.h)
    medido = np.full(n, np.nan)
    if not len(idx):
        return dict(pe=0.0, corpo=0.0, isolado=0.0, medido=medido)
    z, rho, _ = _cilindricas(P[idx], c, a)
    k = np.floor(z / PASSO_PERFIL).astype(int)
    ok = (k >= 0) & (k < n)
    k, rho = k[ok], rho[ok]
    env = np.where(np.isfinite(tipo.rmax), tipo.rmax, 0.0) + 2.5
    dentro = rho <= env[k]
    fosso = (rho > env[k]) & (rho <= env[k] + FOSSO)
    nd = np.bincount(k[dentro], minlength=n)
    nf = np.bincount(k[fosso], minlength=n)
    ordem = np.argsort(k[dentro], kind="stable")
    ks, rs = k[dentro][ordem], rho[dentro][ordem]
    lim = np.searchsorted(ks, np.arange(n + 1))
    for i in range(n):
        if lim[i + 1] - lim[i] >= 4:
            medido[i] = np.percentile(rs[lim[i]:lim[i + 1]], 92)
    tem = np.isfinite(tipo.rmax)
    bate = tem & np.isfinite(medido) & (np.abs(medido - np.where(tem, tipo.rmax, 0)) <= TOL_PERFIL)
    zona = tem & (tipo.h > 1.5) & (tipo.h <= tipo.pe)
    resto = tem & (tipo.h > tipo.pe)
    nota_pe = float(bate[zona].mean()) if zona.any() else 0.0
    nota_corpo = float(bate[resto].mean()) if resto.any() else 1.0
    zi = (tipo.h > 2.0) & (tipo.h <= tipo.pe)
    isolado = 1.0 - float(nf[zi].sum()) / max(1.0, float(nd[zi].sum()))
    return dict(pe=nota_pe, corpo=nota_corpo, isolado=max(0.0, isolado), medido=medido)


# ---------------------------------------------------------------------------
# detecção
# ---------------------------------------------------------------------------

def sondar(arv_p, Pp, Np, e, h, tipo, rng, tentativas=120):
    """A partir de uma pista do alvo (centro e da esfera ou do dodecaedro, que fica a ~h do apoio), acha o plano
    da peça logo abaixo e o caroço que sobrou do pé. Devolve dict(centro, eixo, altura, caroco) ou None."""
    idx = np.asarray(arv_p.query_ball_point(e, h + 18.0))
    if len(idx) < 60:
        return None
    Q, Nq = Pp[idx], Np[idx]
    v = e - Q
    d = np.linalg.norm(v, axis=1)
    casca = (d > max(6.0, h - 9.0)) & (d < h + 18.0)
    olha = casca & (np.einsum("ij,ij->i", v, Nq) > 0.6 * d)        # superfície virada para a pista
    cand = np.flatnonzero(olha)
    if len(cand) < 30:
        return None
    Qc = Q[casca]
    melhor = None
    for i in rng.choice(cand, size=min(tentativas, len(cand)), replace=False):
        n = Nq[i]
        de = float((e - Q[i]) @ n)
        if abs(de - h) > 9.0:
            continue
        dentro = np.abs((Qc - Q[i]) @ n) < 0.6
        # só conta a superfície perto do prumo da pista
        r2 = Qc - e
        lat = np.linalg.norm(r2 - np.outer(r2 @ n, n), axis=1) < 26.0
        pontos = int((dentro & lat).sum())
        if melhor is None or pontos > melhor[0]:
            melhor = (pontos, i, dentro & lat)
    if melhor is None or melhor[0] < 40:
        return None
    pc, pn, _ = ajuste.plano(Qc[melhor[2]])
    if pn @ (e - pc) < 0:
        pn = -pn
    alt = float((e - pc) @ pn)
    if abs(alt - h) > 10.0:
        return None
    c0 = e - alt * pn
    # caroço: pontos da peça um pouco acima do plano, perto do prumo
    w = Q - c0
    z = w @ pn
    lat = w - np.outer(z, pn)
    rho = np.linalg.norm(lat, axis=1)
    cz = (z > 0.8) & (z < tipo.altura_base + 2.5) & (rho < 18.0)
    caroco = int(cz.sum()) >= 25
    if caroco:
        c0 = c0 + np.median(lat[cz], axis=0)
    return dict(centro=c0, eixo=pn, altura=tipo.altura_base, raio=tipo.raio, caroco=caroco)


def passo_de_amostra(m, maximo=5_000_000):
    """Distância entre pontos de amostra: perto do tamanho do triângulo, mas nunca tão fina que estoure a memória."""
    p = min(1.0, max(0.5, m.aresta_mediana()))
    return max(p, float(np.sqrt(m.area / maximo)))


def separar_pedacos(m, fracao=0.05):
    """Triângulos da peça (pedaços grandes) e pedaços soltos pequenos. Devolve (é_peça por triângulo, lista de soltos).
    Cada solto: dict(faces=índices, centro, raio, area)."""
    rot, n = m.componentes()
    area = np.bincount(rot, weights=m.A, minlength=n)
    grande = area >= fracao * area.max()
    eh_peca = grande[rot]
    soltos = []
    if n > 1:
        ordem = np.argsort(rot, kind="stable")
        lim = np.searchsorted(rot[ordem], np.arange(n + 1))
        for k in np.flatnonzero(~grande):
            f = ordem[lim[k]:lim[k + 1]]
            C = m.C[f]
            c = C.mean(0)
            soltos.append(dict(faces=f, centro=c, raio=float(np.linalg.norm(C - c, axis=1).max()), area=float(area[k])))
    return eh_peca, soltos


def detectar(m, log=lambda s: None, tipos=None, nota_minima=0.5):
    """Procura os alvos na malha. Devolve dict(alvos=[...], soltos=[...], eh_peca, passo).

    Cada alvo: dict(centro, eixo, raio, altura_base, tipo, nome, confianca (0..1), nota_pe, nota_corpo, isolado,
    altura, raio_max, soltos=[índices em `soltos`])."""
    tipos = tipos or biblioteca()
    eh_peca, soltos = separar_pedacos(m)
    passo = passo_de_amostra(m)
    P, N, f = m.amostrar(passo, suavizar=2, maximo=6_000_000)
    passo = float(np.sqrt(m.area / len(P)))
    log(f"{len(P):,} pontos de amostra".replace(",", "."))
    arv = cKDTree(P)
    na_peca = eh_peca[f]
    Pp, Np = P[na_peca], N[na_peca]
    achados = []
    raios = sorted({round(t.raio, 1) for t in tipos}, reverse=True)
    for kr, rr in enumerate(raios):
        do_raio = [t for t in tipos if round(t.raio, 1) == rr]
        raio = float(np.mean([t.raio for t in do_raio]))
        log(f"Procurando pés de Ø{2 * raio:.1f} mm… {int(100 * kr / len(raios))}%")
        grupos = _agrupar(votar_cilindros(Pp, Np, raio, passo), 5.0)
        for g in grupos:
            pe = ajustar_pe(arv, P, N, g, raio)
            if pe is None or pe["volta"] < 0.4 or pe["rms"] > 0.45:
                continue
            melhor = None
            for t in do_raio:
                if abs(pe["altura"] - t.altura_base) > 2.5:
                    continue
                c = comparar(arv, P, pe, t)
                nota = 0.55 * c["pe"] + 0.25 * c["isolado"] + 0.20 * min(1.0, pe["volta"] / 0.8)
                total = nota + 0.3 * c["corpo"]
                if melhor is None or total > melhor[0]:
                    melhor = (total, nota, t, c)
            if melhor is None:
                continue
            _, nota, t, c = melhor
            alt_env = max(x.altura for x in do_raio)
            raio_env = max(x.raio_max for x in do_raio)
            achados.append(dict(centro=pe["centro"], eixo=pe["eixo"], raio=pe["raio"], altura_base=pe["altura"], rms=pe["rms"],
                                volta=pe["volta"], tipo=t.id, nome=t.nome, confianca=float(nota), nota_pe=c["pe"],
                                nota_corpo=c["corpo"], isolado=c["isolado"], altura=alt_env, raio_max=raio_env,
                                medido=c["medido"], votos=pe["votos"]))
    # o mesmo alvo pode aparecer por dois caminhos (o equador da esfera também parece um pé): fica o mais convincente
    achados.sort(key=lambda a: -(a["confianca"] + 0.2 * a["nota_corpo"]))
    alvos_ = []

    def repetido(a):
        for b in alvos_:
            for p, q in ((a, b), (b, a)):
                d = p["centro"] - q["centro"]
                h = d @ q["eixo"]
                rho = np.linalg.norm(d - h * q["eixo"])
                if -6.0 < h < q["altura"] + 8.0 and rho < q["raio_max"] + 6.0:
                    return True
        return False

    def explicado(e, folga=9.0):
        """O ponto e (centro de esfera ou de dodecaedro) já pertence a um alvo aceito?"""
        for b in alvos_:
            d = e - b["centro"]
            h = d @ b["eixo"]
            if -5.0 < h < 75.0 and np.linalg.norm(d - h * b["eixo"]) < folga + 0.25 * max(h, 0.0):
                return True
        return False

    for a in achados:
        if a["confianca"] >= nota_minima * 0.75 and not repetido(a):
            alvos_.append(a)

    # ---- segundo caminho: o pé saiu amassado (um caroço em vez de um cilindro), mas a esfera ou o dodecaedro
    # do alvo estão lá. Parte-se deles, acha-se a superfície da peça logo abaixo e o caroço em cima dela.
    log("Conferindo esferas e dodecaedros sem pé…")
    arv_p = cKDTree(Pp)
    rng = np.random.default_rng(1)
    pistas = []
    for rr in sorted({round(e[1], 1) for t in tipos for e in t.esferas}):
        com = [(t, e) for t in tipos for e in t.esferas if round(e[1], 1) == rr]
        for g in _agrupar(votar_esferas(P, N, com[0][1][1], passo), 5.0):
            idx = np.asarray(arv.query_ball_point(g["centro"], rr + 2.5))
            if len(idx) < 40:
                continue
            d = np.linalg.norm(P[idx] - g["centro"], axis=1)
            perto = np.abs(d - rr) < 1.5
            if perto.sum() < 40:
                continue
            ec, er, erms = ajuste.esfera(P[idx][perto])
            if abs(er - rr) > 0.15 * rr or erms > 0.5:
                continue
            for t, e in com:
                pistas.append((ec, float(e[0]), t, "esfera"))
    for s_ in soltos:
        if 900.0 < s_["area"] < 3000.0 and 10.0 < s_["raio"] < 22.0:
            for t in tipos:
                if t.h_dodecaedro:
                    pistas.append((s_["centro"], float(t.h_dodecaedro), t, "dodecaedro"))
    extras = []
    for e, h, t, origem in pistas:
        if explicado(e):
            continue
        pe = sondar(arv_p, Pp, Np, e, h, t, rng)
        if pe is None:
            continue
        c = comparar(arv, P, pe, t)
        nota = (0.42 if pe["caroco"] else 0.2) + 0.3 * c["pe"] + 0.2 * c["corpo"] + 0.08 * c["isolado"]
        extras.append(dict(centro=pe["centro"], eixo=pe["eixo"], raio=t.raio, altura_base=t.altura_base, rms=float("nan"),
                           volta=0.0, tipo=t.id, nome=t.nome, confianca=float(min(nota, 0.89)), nota_pe=c["pe"],
                           nota_corpo=c["corpo"], isolado=c["isolado"], altura=t.altura, raio_max=t.raio_max,
                           medido=c["medido"], votos=0.0, deformado=True, origem=origem))
    extras.sort(key=lambda a: -(a["confianca"]))
    for a in extras:
        if not repetido(a) and not explicado(a["centro"] + a["eixo"] * 20.0, 6.0):
            alvos_.append(a)
    # pedaços soltos que pertencem a cada alvo (esfera e dodecaedro que o escaneamento separou do pé)
    for a in alvos_:
        a["soltos"] = []
        a["seguro"] = bool(a["confianca"] >= nota_minima)
        a.setdefault("deformado", False)
    for i, s in enumerate(soltos):
        s["alvo"] = None
        melhor = None
        for j, a in enumerate(alvos_):
            d = s["centro"] - a["centro"]
            h = d @ a["eixo"]
            rho = np.linalg.norm(d - h * a["eixo"])
            if -8.0 < h < 80.0 and rho < 34.0:
                if melhor is None or rho < melhor[0]:
                    melhor = (rho, j)
        if melhor is not None:
            s["alvo"] = melhor[1]
            alvos_[melhor[1]]["soltos"].append(i)
    log(f"{len(alvos_)} alvos encontrados; {len(soltos)} pedaços soltos")
    return dict(alvos=alvos_, soltos=soltos, eh_peca=eh_peca, passo=passo)
