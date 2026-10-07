"""Retirada dos alvos e fechamento dos furos.

Para cada alvo: (1) ajusta a superfície da peça em volta do pé; (2) recorta o pé e tudo o que estiver grudado
nele acima dessa superfície (rebarbas e caroços do escaneamento incluídos); (3) apaga o corpo do alvo, que ficou
solto; (4) fecha o furo com um remendo assentado na superfície ajustada, emendado no contorno."""
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from . import ajuste, remendo, superficie
from .malha import Malha

OPCOES = dict(
    margem=1.2,          # mm retirados a mais em volta do recorte, para o contorno do furo cair em superfície limpa
    alcance=8.0,         # mm em volta do pé onde rebarbas grudadas ainda são recortadas
    remover_soltos=True, # apagar pedaços soltos pequenos (esferas, dodecaedros e lascas que o escaneamento separou)
    preencher=True,
)


def _componentes(m, manter):
    """Rótulos dos pedaços ligados entre os triângulos marcados (os demais ficam com -1)."""
    idx = np.flatnonzero(manter)
    rot = np.full(m.n_faces, -1, np.int64)
    if not len(idx):
        return rot, 0
    g = m.grafo_faces()[idx][:, idx]
    n, r = csgraph.connected_components(g, directed=False)
    rot[idx] = r
    return rot, n


def _dividir_arestas(F, divisoes):
    """Aplica as divisões de lados do contorno aos triângulos vizinhos: o lado (i→j) ganha o vértice k no meio."""
    if not divisoes:
        return F
    F = [tuple(int(x) for x in f) for f in F]
    dono = {}
    for t, f in enumerate(F):
        for a in range(3):
            dono[(f[a], f[(a + 1) % 3])] = t
    for i, j, k in divisoes:                          # o remendo percorre i→j; o triângulo vizinho tem j→i
        t = dono.pop((j, i), None)
        if t is None:
            continue
        f = F[t]
        a = f.index(j)
        o = f[(a + 2) % 3]
        for q in range(3):
            dono.pop((f[q], f[(q + 1) % 3]), None)
        F[t] = (j, k, o)
        F.append((k, i, o))
        for tt in (t, len(F) - 1):
            g = F[tt]
            for q in range(3):
                dono[(g[q], g[(q + 1) % 3])] = tt
    return np.array(F, dtype=np.int64)


def limpar_local(V, F, alvo, aro, opc):
    """Retira um alvo de um recorte local da peça e fecha o furo.

    V, F: recorte local (só triângulos da peça); aro: máscara dos triângulos na orla do recorte, que nunca são
    tocados. Devolve dict(V, F, novos=máscara dos triângulos do remendo, info)."""
    m = Malha(V, F)
    F = m.F
    aro = np.asarray(aro, bool)
    if m.validos is not None:
        aro = aro[m.validos]
    c, a, r = np.asarray(alvo["centro"], float), np.asarray(alvo["eixo"], float), float(alvo["raio"])
    alt_base = float(alvo.get("altura_base", 6.0))
    info = dict(referencia=None, sigma=None, preenchido=False, aviso=None, area_remendo=0.0, removidos=0, degrau=None)

    def cil(P):
        Q = P - c
        z = Q @ a
        return z, np.linalg.norm(Q - np.outer(z, a), axis=1)

    zv, rv = cil(m.V)
    zf, rf = cil(m.C)

    # ---- 1. superfície de referência: pontos da peça em volta do pé, fora dele
    nv = m.normais_de_vertice(1)
    usados = np.zeros(m.n_vertices, bool)
    usados[F.ravel()] = True
    viz = usados & (rv > r + 2.5) & (rv < r + 18.0) & (np.abs(zv) < 12.0) & (nv @ a > 0.5)
    if viz.sum() < 30:
        viz = usados & (rv > r + 1.5) & (rv < r + 25.0) & (np.abs(zv) < 15.0) & (nv @ a > 0.3)
    if viz.sum() < 20:
        info["aviso"] = "pouca superfície em volta do alvo para servir de referência"
        return dict(V=m.V, F=F, novos=np.zeros(len(F), bool), info=info)
    registro = []
    modelo, sigma, fracao = superficie.ajustar(m.V[viz], nv[viz], c, a, registro=registro)
    info.update(referencia=modelo.descricao(), sigma=float(sigma), explicado=float(fracao), candidatos=registro[0] if registro else None)
    tol = float(np.clip(3.5 * sigma, 0.25, 0.8))
    res = modelo.dist(m.V)
    res_f = res[F].max(1)
    # daqui em diante as medidas são em relação à referência, não ao eixo ajustado ao pé (que num pé amassado
    # sai torto): altura = distância à superfície de referência; raio = distância à normal dela no ponto de apoio
    n_ref = _normal(modelo, c, a)
    if n_ref @ a < 0.75:
        n_ref = a
    c_ref = c - modelo.dist(c[None])[0] * n_ref

    def raio_ref(P):
        Q = P - c_ref
        return np.linalg.norm(Q - np.outer(Q @ n_ref, n_ref), axis=1)
    rv, rf = raio_ref(m.V), raio_ref(m.C)
    alt_f = res[F].mean(1)
    baixo_f = res[F].min(1)
    # só o lado da peça onde o alvo está: num eixo ou numa parede fina, o outro lado também fica "em cima" da
    # referência e debaixo do alvo, e não pode ser tocado
    zr_f = (m.C - c_ref) @ n_ref
    deste_lado = zr_f > -(0.6 * rf + 4.0)

    # ---- 2. recorte junto à superfície: o pé e o que estiver grudado nele acima da referência
    h_baixo = alt_base + 1.5
    semente = (rf <= r + 0.6) & (alt_f > 0.3) & (alt_f < h_baixo) & deste_lado
    if not semente.any():
        semente = (rf <= r + 1.5) & (alt_f > -0.5) & (alt_f < h_baixo + 2) & deste_lado
    fora = (res_f > tol) & deste_lado
    regiao = None
    for lim in (r + 20.0, r + float(opc["alcance"])):
        permitido = (fora | semente) & (alt_f < h_baixo) & (baixo_f > -2.5) & (rf <= lim)
        if aro is not None:
            permitido &= ~aro
        rot, _ = _componentes(m, permitido)
        ks = np.unique(rot[semente & permitido])
        ks = ks[ks >= 0]
        regiao = np.isin(rot, ks) & permitido
        info["raio_recorte"] = float(rf[regiao].max()) if regiao.any() else 0.0
        info["recorte_limitado"] = bool(lim < r + 19.0)
        if not regiao.any() or rf[regiao].max() < lim - 1.0:
            break                                       # o recorte acabou sozinho antes do limite: é a rebarba toda
    # o disco debaixo do pé (quando o escaneamento fechou a malha por baixo dele)
    regiao |= (rf <= r + 0.3) & (alt_f > -1.5) & (alt_f < h_baixo) & deste_lado
    # margem: entra na superfície limpa
    vr = np.zeros(m.n_vertices, bool)
    vr[F[regiao].ravel()] = True
    if vr.any() and opc["margem"] > 0:
        d, _ = cKDTree(m.V[vr]).query(m.V, distance_upper_bound=float(opc["margem"]))
        perto = np.isfinite(d)
        extra = perto[F].all(1) & (alt_f < h_baixo) & deste_lado
        if aro is not None:
            extra &= ~aro
        regiao |= extra
    # ---- 3. o corpo do alvo: o que ficou solto do resto da peça
    fica = ~regiao
    rot, n = _componentes(m, fica)
    area = np.bincount(rot[fica], weights=m.A[fica], minlength=n)
    na_orla = np.zeros(n, bool)
    if aro is not None:
        na_orla[np.unique(rot[aro & fica])] = True
    if n:
        na_orla[np.argmax(area)] = True                 # o maior pedaço é sempre a peça
    solto = fica & ~na_orla[np.maximum(rot, 0)]
    corpo = solto.copy()
    grudado = False
    # o que ainda sobrou dentro do contorno do alvo (corpo preso à peça por outro caminho, como uma rebarba até a
    # parede): sai o que está dentro de um cone folgado em volta do eixo, e depois o que isso deixar solto
    raio_env = float(alvo.get("raio_max", r)) + 3.0
    resto = fica & ~solto & (alt_f > h_baixo) & (alt_f < float(alvo.get("altura", 60.0)) + 8.0) & (rf < raio_env + 0.3 * alt_f) & (zr_f > 0)
    if aro is not None:
        resto &= ~aro
    if resto.any():
        corpo |= resto
        fica2 = fica & ~corpo
        rot, n = _componentes(m, fica2)
        na_orla = np.zeros(n, bool)
        if aro is not None:
            na_orla[np.unique(rot[aro & fica2])] = True
        if n:
            na_orla[np.argmax(np.bincount(rot[fica2], weights=m.A[fica2], minlength=n))] = True
        corpo |= fica2 & ~na_orla[np.maximum(rot, 0)]
        grudado = True
    remover = regiao | corpo
    info["removidos"] = int(remover.sum())
    if grudado:
        # o corpo estava preso à peça por outro caminho (uma rebarba até uma parede, por exemplo). Se o corte
        # deixou borda aberta fora do furo do pé, sobrou um toco dessa rebarba na peça.
        v_corpo = np.zeros(m.n_vertices, bool)
        v_corpo[F[corpo & ~regiao].ravel()] = True
        v_reg = np.zeros(m.n_vertices, bool)
        v_reg[F[regiao].ravel()] = True
        v_fica = np.zeros(m.n_vertices, bool)
        v_fica[F[~remover].ravel()] = True
        toco = int((v_corpo & v_fica & ~v_reg).sum())
        if toco > 6:
            info["aviso"] = "o alvo estava grudado em outra parte da peça por uma rebarba; sobrou um toco dela, com a borda aberta"
            info["toco"] = toco
    Fk = F[~remover]
    novos = np.zeros(len(Fk), bool)
    Vn = m.V
    if not opc.get("preencher", True) or not regiao.any():
        return dict(V=Vn, F=Fk, novos=novos, info=info)

    # ---- 4. remendo: laços de borda criados pelo recorte junto à superfície
    tocados = np.zeros(m.n_vertices, bool)
    tocados[F[regiao].ravel()] = True
    mk = Malha(Vn, Fk)
    for _ in range(3):
        orelha = orelhas(mk, tocados)
        if not orelha.any():
            break
        tocados[mk.F[orelha].ravel()] = True
        mk = Malha(Vn, mk.F[~orelha])
        info["removidos"] += int(orelha.sum())
    Fk = mk.F
    novos = np.zeros(len(Fk), bool)
    bordas, _ = mk.bordas()
    cand = [l for l in remendo.lacos(bordas) if tocados[l].any()]
    if not cand:
        info["aviso"] = info["aviso"] or "o recorte não deixou um furo fechado para preencher"
        return dict(V=Vn, F=Fk, novos=novos, info=info)
    usados_k = np.zeros(len(Vn), bool)
    usados_k[Fk.ravel()] = True
    arv_v = cKDTree(Vn[usados_k])
    ids_v = np.flatnonzero(usados_k)
    nvk = mk.normais_de_vertice(1)
    est = dict(V=Vn, extra=[], F=[], divs=[], area=0.0, degraus=[], avisos=[], paredes=0)
    for l in cand:
        if rv[l[l < len(rv)]].max() > r + 30.0 and tocados[l].all():
            continue
        _remendar(est, l, tocados, modelo, n_ref, max(tol, 0.35), arv_v, ids_v, nvk, res, r)
    if est["avisos"]:
        info["aviso"] = "; ".join(([info["aviso"]] if info["aviso"] else []) + sorted(set(est["avisos"])))
    if not est["F"]:
        return dict(V=Vn, F=Fk, novos=novos, info=info)
    Vn = est["V"]
    Fk = _dividir_arestas(Fk, est["divs"])
    Fn = np.vstack([Fk] + est["F"])
    novos = np.zeros(len(Fn), bool)
    novos[len(Fk):] = True
    info["preenchido"] = True
    info["area_remendo"] = float(est["area"])
    info["degrau"] = float(max(est["degraus"])) if est["degraus"] else 0.0
    info["arestas_vivas"] = int(est["paredes"])
    return dict(V=Vn, F=Fn, novos=novos, info=info)


def orelhas(mk, tocados):
    """Triângulos presos ao resto por um lado só, com os outros dois no contorno do corte. Uma orelha dessas,
    dobrada para dentro do furo, faz o remendo sair colado nela pelo avesso; sai antes de fechar."""
    fe, _, cont = mk.arestas()
    livres = (cont[fe] == 1).sum(axis=1)
    return (livres >= 2) & (tocados[mk.F].sum(axis=1) >= 2)


def _normal(modelo, c, a, eps=0.05):
    """Normal de um modelo de superfície perto do ponto c (gradiente numérico da distância)."""
    e1, e2, a = ajuste.base_ortonormal(a)
    g = np.array([modelo.dist((c + eps * v)[None])[0] - modelo.dist((c - eps * v)[None])[0] for v in (e1, e2, a)])
    n = g[0] * e1 + g[1] * e2 + g[2] * a
    k = np.linalg.norm(n)
    return n / k if k > 1e-9 else a


def _sobre(modelos, X, voltas=8):
    """Leva os pontos X para cima de todos os modelos ao mesmo tempo (projeções alternadas): a linha da aresta."""
    X = np.array(X, float)
    for _ in range(voltas):
        for mod in modelos:
            d = mod.dist(X)
            g = np.zeros_like(X)
            for k in range(3):
                e = np.zeros(3)
                e[k] = 0.02
                g[:, k] = (mod.dist(X + e) - mod.dist(X - e)) / 0.04
            g /= np.maximum(np.linalg.norm(g, axis=1), 1e-9)[:, None]
            X = X - d[:, None] * g
    return X


def _corda(est, p, q, passo, modelos):
    """Cria vértices novos em linha de p a q, assentados nos modelos. Devolve os índices (sem p e q)."""
    V = est["V"]
    n = int(np.ceil(np.linalg.norm(V[q] - V[p]) / passo)) - 1
    if n <= 0:
        return []
    t = (np.arange(1, n + 1) / (n + 1))[:, None]
    X = _sobre(modelos, V[p] * (1 - t) + V[q] * t)
    ids = list(range(len(V), len(V) + n))
    est["V"] = np.vstack([V, X])
    return ids


def _trechos(marca):
    """Trechos seguidos de True numa sequência circular: lista de (início, comprimento)."""
    n = len(marca)
    if marca.all():
        return [(0, n)]
    if not marca.any():
        return []
    ini = int(np.flatnonzero(~marca)[0])
    rodado = np.roll(marca, -ini)
    out = []
    k = 0
    while k < n:
        if rodado[k]:
            j = k
            while j < n and rodado[j]:
                j += 1
            out.append(((k + ini) % n, j - k))
            k = j
        else:
            k += 1
    return out


def _quase_simples(pol):
    """O contorno não se cruza, a menos de dentes do recorte que um alisamento leve desfaz (o mesmo alisamento
    que o fechamento do furo aplica antes de triangular)."""
    for _ in range(3):
        if remendo._simples(pol):
            return True
        pol = 0.5 * pol + 0.25 * (np.roll(pol, 1, axis=0) + np.roll(pol, -1, axis=0))
    return remendo._simples(pol)


def _fechar(est, laco, modelo, n_mod):
    V = est["V"]
    cl = V[laco].mean(0)
    f1, f2, n_mod = ajuste.base_ortonormal(n_mod)
    try:
        rem = remendo.fechar(V, np.asarray(laco), modelo, cl, n_mod, f1, f2)
    except ValueError as e:
        est["avisos"].append(f"um furo não pôde ser fechado ({e})")
        return False
    est["V"] = np.vstack([V, rem["V_novos"]])
    est["F"].append(rem["F"])
    est["divs"] += rem["divisoes"]
    est["area"] += rem["area"]
    est["degraus"].append(rem["degrau"])
    return True


def _remendar(est, laco, tocados, modelo, n_ref, tol, arv_v, ids_v, nvk, res, r, achar=None):
    """Fecha um laço de borda. Trata três situações: furo simples; furo que desce por uma parede ao lado
    (refaz a aresta viva entre a superfície de cima e a parede); recorte que encostou na borda da malha."""
    V = est["V"]
    laco = np.asarray(laco)
    n = len(laco)
    lados = np.linalg.norm(V[laco] - V[np.roll(laco, -1)], axis=1)
    passo = float(np.clip(np.median(lados), 0.2, 3.0))
    velho = laco < len(tocados)
    toc = np.zeros(n, bool)
    toc[velho] = tocados[laco[velho]]
    # ---- recorte que encostou na borda da malha: fecha cada entalhe com uma corda reta
    if not toc.all():
        comp_antigo = float(lados[~toc & ~np.roll(toc, -1)].sum())
        if comp_antigo > 45.0:
            feito = False
            for ini, k in _trechos(toc):
                if k < 3:
                    continue
                e1, e2, _ = ajuste.base_ortonormal(n_ref)
                achou = None
                for apara in range(0, 16):                    # pontas do arco que voltam sobre a borda antiga fazem a corda cruzar
                    for ap in range(0, apara + 1):
                        aq = apara - ap
                        if ap + aq > k - 3:
                            continue
                        p, q = laco[(ini - 1 + ap) % n], laco[(ini + k - aq) % n]
                        arco = [laco[(ini + j) % n] for j in range(ap, k - aq)]
                        if np.linalg.norm(V[p] - V[q]) > 2 * (r + 26.0):
                            continue
                        Q = V[[p] + arco + [q]]
                        if _quase_simples(np.c_[Q @ e1, Q @ e2]):
                            achou = (p, q, arco)
                            break
                    if achou:
                        break
                if not achou:
                    continue
                p, q, arco = achou
                corda = _corda(est, q, p, passo, [modelo])
                V = est["V"]
                sub = np.array([p] + arco + [q] + corda)
                feito |= _fechar(est, sub, modelo, n_ref)
            if feito:
                est["avisos"].append("alvo na borda da malha: a borda foi refeita em linha reta nesse trecho")
            else:
                est["avisos"].append("o recorte encostou na borda da malha; o trecho ficou aberto")
            return
    est["paredes"] += _com_paredes(est, [int(x) for x in laco], modelo, n_ref, tol, arv_v, ids_v, nvk, len(tocados), achar=achar)


def _parede_do_trecho(est, arco, modelo, sinal, tol, n_mod, arv_v, ids_v, nvk, n_orig):
    """Plano da parede em que um trecho do contorno (fora da superfície `modelo`) está assentado, ou None.
    Tenta primeiro com a vizinhança do trecho inteiro; se o trecho passa por mais de uma face (desce a parede e
    segue pelo fundo, por exemplo), ajusta só pelas pontas, que são a parede que encosta na superfície."""
    V = est["V"]

    def vizinhos(pts):
        viz = set()
        for lst in arv_v.query_ball_point(V[pts], 4.5):
            viz.update(lst)
        viz = ids_v[np.fromiter(viz, dtype=np.int64)] if viz else np.zeros(0, np.int64)
        viz = viz[viz < n_orig]
        return viz[sinal * modelo.dist(V[viz]) > tol] if len(viz) else viz

    def ajustar(viz):
        if len(viz) < 25:
            return None
        pc, pn, sig, _ = ajuste.plano_robusto(V[viz])
        nm = nvk[viz].mean(0)
        if pn @ nm < 0:
            pn = -pn
        return pc, pn, sig

    k = len(arco)
    r = ajustar(vizinhos(arco))
    if r is not None:
        pc, pn, sig = r
        parede = superficie.Plano(pc, pn)
        dentro = np.mean(np.abs(parede.dist(V[arco])) < 0.5)
        if sig <= 0.3 and dentro >= 0.75 and abs(pn @ n_mod) <= 0.9:
            return parede, pn
    # pelas pontas
    q = max(3, min(k // 4, 12))
    if k < 2 * q + 2:
        return None
    r = ajustar(vizinhos(arco[:q] + arco[-q:]))
    if r is None:
        return None
    pc, pn, sig = r
    parede = superficie.Plano(pc, pn)
    d = np.abs(parede.dist(V[arco]))
    pontas = np.mean(np.r_[d[:q], d[-q:]] < 0.5)
    if sig > 0.3 or pontas < 0.8 or abs(pn @ n_mod) > 0.9:
        return None
    return parede, pn


def _com_paredes(est, laco, modelo, n_mod, tol, arv_v, ids_v, nvk, n_orig, nivel=0, achar=None):
    """Fecha um laço sobre `modelo`. Os trechos que saem dele e assentam numa parede plana são fechados à parte,
    com a aresta viva entre as duas superfícies refeita; a parede é tratada do mesmo jeito (um furo que desce a
    parede e continua pelo fundo tem duas arestas). Devolve o nº de paredes fechadas."""
    V = est["V"]
    n = len(laco)
    lados = np.linalg.norm(V[laco] - V[np.roll(laco, -1)], axis=1)
    passo = float(np.clip(np.median(lados), 0.2, 3.0))
    d0 = modelo.dist(V[laco])
    classe = np.where(np.abs(d0) <= tol, 0, np.where(d0 < 0, -1, 1))
    principal = list(laco)
    subs = []
    for ini, k in sorted(_trechos(classe != 0), key=lambda t: -t[1]):
        if k < 4 or k > 0.8 * n:
            continue
        arco = [int(laco[(ini + j) % n]) for j in range(k)]
        p, q = int(laco[(ini - 1) % n]), int(laco[(ini + k) % n])
        sinal = np.sign(np.median(d0[[(ini + j) % n for j in range(k)]]))
        achado = (achar(arco, modelo, n_mod) if achar is not None else
                  _parede_do_trecho(est, arco, modelo, sinal, tol, n_mod, arv_v, ids_v, nvk, n_orig))
        if achado is None:
            continue
        parede, pn = achado
        if p not in principal or q not in principal:
            continue
        corda = _corda(est, p, q, passo, [modelo, parede])     # de p para q, sobre a aresta
        V = est["V"]
        ip, iq = principal.index(p), principal.index(q)
        if ip < iq:
            principal = principal[:ip + 1] + corda + principal[iq:]
        else:
            principal = principal[iq:ip + 1] + corda
        subs.append(([p] + arco + [q] + corda[::-1], parede, pn))
    if len(principal) >= 3:
        _fechar(est, np.array(principal), modelo, n_mod)
    feitas = 0
    for sub, parede, pn in subs:
        if nivel < 2:
            nF = len(est["F"])
            feitas += _com_paredes(est, sub, parede, pn, min(tol, 0.5), arv_v, ids_v, nvk, n_orig, nivel + 1, achar=achar)
            feitas += int(len(est["F"]) > nF)
        elif _fechar(est, np.array(sub), parede, pn):
            feitas += 1
    return feitas


def limpar(m, det, escolhidos=None, opcoes=None, log=lambda s: None):
    """Retira da malha os alvos escolhidos (índices em det['alvos']; None = todos os seguros) e os pedaços soltos.
    Devolve dict(malha, remendo=máscara dos triângulos novos, relatorio=[info por alvo], soltos_removidos)."""
    opc = dict(OPCOES)
    opc.update(opcoes or {})
    alvos = det["alvos"]
    if escolhidos is None:
        escolhidos = [i for i, a in enumerate(alvos) if a.get("seguro", True)]
    V = m.V
    F = m.F
    viva = np.ones(len(F), bool)
    n_soltos = 0
    if opc["remover_soltos"]:
        for s in det["soltos"]:
            viva[s["faces"]] = False
            n_soltos += 1
    eh_peca = det["eh_peca"]
    if "grade" not in m._cache:
        log("Indexando a malha…")
    arv = m.grade()
    novos_V, novos_F = [], []
    n_v = len(V)
    relatorio = {}
    # alvos vizinhos são tratados no mesmo recorte local, um depois do outro
    centros = np.array([alvos[i]["centro"] + alvos[i]["eixo"] * 25.0 for i in escolhidos]) if escolhidos else np.zeros((0, 3))
    RAIO = 70.0
    grupos = []
    if len(escolhidos):
        pares = cKDTree(centros).query_pairs(2 * RAIO - 20.0, output_type="ndarray")
        g = sparse.coo_matrix((np.ones(len(pares)), (pares[:, 0], pares[:, 1])), shape=(len(escolhidos),) * 2)
        ng, rot = csgraph.connected_components(g, directed=False)
        grupos = [np.flatnonzero(rot == k) for k in range(ng)]
    feitos = 0
    for grupo in grupos:
        idx = arv.bolas(centros[grupo], RAIO)
        idx = idx[viva[idx] & eh_peca[idx]]
        if not len(idx):
            for k in grupo:
                relatorio[escolhidos[k]] = dict(aviso="sem malha da peça em volta do alvo", preenchido=False)
            continue
        # recorte local com índices próprios
        Fl = F[idx]
        vu = np.unique(Fl)
        mapa = np.full(n_v, -1, np.int64)
        mapa[vu] = np.arange(len(vu))
        Vl, Fl = V[vu], mapa[Fl]
        dmin = np.min(np.linalg.norm(m.C[idx][:, None, :] - centros[grupo][None], axis=2), axis=1)
        aro = dmin > RAIO - 4.0
        eh_novo = np.zeros(len(Fl), bool)
        n_orig = len(vu)
        for k in grupo:
            i = escolhidos[k]
            r = limpar_local(Vl, Fl, alvos[i], aro, opc)
            # a orla e as marcas de "novo" acompanham os triângulos que sobraram (casados pelos três vértices)
            Vl, Fl2 = r["V"], np.asarray(r["F"], dtype=np.int64)
            nv_ = int(max(Fl.max(), Fl2.max())) + 1
            ch1 = (Fl[:, 0] * nv_ + Fl[:, 1]) * nv_ + Fl[:, 2]
            ch2 = (Fl2[:, 0] * nv_ + Fl2[:, 1]) * nv_ + Fl2[:, 2]
            ordem = np.argsort(ch1, kind="stable")
            pos = np.clip(np.searchsorted(ch1[ordem], ch2), 0, len(ch1) - 1)
            achou = ch1[ordem][pos] == ch2
            de = ordem[pos]
            aro2 = np.where(achou, aro[de], False)
            novo2 = r["novos"] | np.where(achou, eh_novo[de], False)
            Fl, aro, eh_novo = Fl2, aro2, novo2
            relatorio[i] = r["info"]
            feitos += 1
            if feitos % 5 == 0 or feitos == len(escolhidos):
                log(f"Retirando alvos… {int(100 * feitos / len(escolhidos))}%")
        viva[idx] = False
        # volta para os índices globais: vértices antigos pelo mapa, novos ao fim
        g_de_l = np.concatenate([vu, n_v + sum(len(x) for x in novos_V) + np.arange(len(Vl) - n_orig)])
        novos_V.append(Vl[n_orig:])
        novos_F.append((g_de_l[Fl], eh_novo))
    Vt = np.vstack([V] + novos_V) if novos_V else V
    Ft = [F[viva]]
    marca = [np.zeros(int(viva.sum()), bool)]
    for f, nv_ in novos_F:
        Ft.append(f)
        marca.append(nv_)
    Ft = np.vstack(Ft)
    marca = np.concatenate(marca)
    usados = np.zeros(len(Vt), bool)
    usados[Ft.ravel()] = True
    renum = np.cumsum(usados) - 1
    limpa = Malha(Vt[usados], renum[Ft], nome=m.nome)
    if limpa.validos is not None:                        # triângulo degenerado descartado na montagem
        marca = marca[limpa.validos]
    return dict(malha=limpa, remendo=marca, relatorio=[relatorio.get(i) for i in range(len(alvos))],
                soltos_removidos=n_soltos, escolhidos=list(escolhidos))
