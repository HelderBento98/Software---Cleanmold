"""Retirada dos alvos. O furo fica aberto, com o contorno limpo.

Para cada alvo: (1) ajusta a superfície da peça em volta do pé; (2) recorta o pé e tudo o que estiver grudado
nele acima dessa superfície (rebarbas e caroços do escaneamento incluídos); (3) apaga o corpo do alvo, que ficou
solto; (4) apara o contorno do corte (triângulos pendurados por um lado só).

Nenhum triângulo é criado nem mexido: o resultado é a lista dos triângulos da malha original que ficam. O que não
é alvo sai do Cleanmold idêntico ao que entrou."""
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from . import ajuste, superficie
from .malha import Malha

OPCOES = dict(
    margem=1.2,          # mm retirados a mais em volta do recorte, para o contorno do furo cair em superfície limpa
    alcance=8.0,         # mm em volta do pé onde rebarbas grudadas ainda são recortadas
    remover_soltos=True, # apagar também os pedaços soltos pequenos que não são de nenhum alvo (lascas do escaneamento)
)
AJUSTE_PONTOS = 5000     # pontos da vizinhança usados para ajustar a superfície de referência
RAIO = 70.0              # mm de malha em volta de cada alvo que entram no recorte local


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


def _normal(modelo, c, a, eps=0.05):
    """Normal de um modelo de superfície perto do ponto c (gradiente numérico da distância)."""
    e1, e2, a = ajuste.base_ortonormal(a)
    g = np.array([modelo.dist((c + eps * v)[None])[0] - modelo.dist((c - eps * v)[None])[0] for v in (e1, e2, a)])
    n = g[0] * e1 + g[1] * e2 + g[2] * a
    k = np.linalg.norm(n)
    return n / k if k > 1e-9 else a


def cortar_local(V, F, alvo, aro, opc):
    """Marca, num recorte local da peça, os triângulos de um alvo.

    V, F: recorte local (só triângulos da peça); aro: máscara dos triângulos na orla do recorte, que nunca são
    tocados. Devolve (remover: máscara sobre F, info)."""
    n_dados = len(F)
    m = Malha(np.asarray(V, np.float64), F)
    F = m.F
    aro = np.asarray(aro, bool)
    de_volta = None
    if m.validos is not None:                           # triângulo degenerado descartado na montagem
        de_volta = np.flatnonzero(m.validos)
        aro = aro[m.validos]
    c, a, r = np.asarray(alvo["centro"], float), np.asarray(alvo["eixo"], float), float(alvo["raio"])
    alt_base = float(alvo.get("altura_base", 6.0))
    info = dict(referencia=None, sigma=None, retirado=False, aviso=None, nota=None, removidos=0, contorno=None, diametro=None)

    def saida(remover):
        if de_volta is None:
            return remover, info
        fora = np.zeros(n_dados, bool)
        fora[de_volta[remover]] = True
        return fora, info

    def cil(P):
        Q = P - c
        z = Q @ a
        return z, np.linalg.norm(Q - np.outer(z, a), axis=1)

    zv, rv = cil(m.V)

    # ---- 1. superfície de referência: pontos da peça em volta do pé, fora dele
    nv = m.normais_de_vertice(1).astype(np.float64)
    usados = np.zeros(m.n_vertices, bool)
    usados[F.ravel()] = True
    viz = usados & (rv > r + 2.5) & (rv < r + 18.0) & (np.abs(zv) < 12.0) & (nv @ a > 0.5)
    if viz.sum() < 30:
        viz = usados & (rv > r + 1.5) & (rv < r + 25.0) & (np.abs(zv) < 15.0) & (nv @ a > 0.3)
    if viz.sum() < 20:
        info["aviso"] = "pouca superfície em volta do alvo para servir de referência: ficou como estava"
        return saida(np.zeros(len(F), bool))
    quais = np.flatnonzero(viz)
    if len(quais) > AJUSTE_PONTOS:                       # o ajuste não melhora com mais pontos que isso; só demora
        quais = np.sort(np.random.default_rng(0).choice(quais, AJUSTE_PONTOS, replace=False))
    modelo, sigma, fracao = superficie.ajustar(m.V[quais], nv[quais], c, a)
    info.update(referencia=modelo.descricao(), sigma=float(sigma), explicado=float(fracao))
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
    C = m.C
    rf = raio_ref(C)
    alt_f = res[F].mean(1)
    baixo_f = res[F].min(1)
    # só o lado da peça onde o alvo está: num eixo ou numa parede fina, o outro lado também fica "em cima" da
    # referência e debaixo do alvo, e não pode ser tocado
    zr_f = (C - c_ref) @ n_ref
    deste_lado = zr_f > -(0.6 * rf + 4.0)

    # ---- 2. recorte junto à superfície: o pé e o que estiver grudado nele acima da referência
    h_baixo = alt_base + 1.5
    semente = (rf <= r + 0.6) & (alt_f > 0.3) & (alt_f < h_baixo) & deste_lado
    if not semente.any():
        semente = (rf <= r + 1.5) & (alt_f > -0.5) & (alt_f < h_baixo + 2) & deste_lado
    fora = (res_f > tol) & deste_lado
    regiao = None
    for lim in (r + 20.0, r + float(opc["alcance"])):
        permitido = (fora | semente) & (alt_f < h_baixo) & (baixo_f > -2.5) & (rf <= lim) & ~aro
        rot, _ = _componentes(m, permitido)
        ks = np.unique(rot[semente & permitido])
        ks = ks[ks >= 0]
        regiao = np.isin(rot, ks) & permitido
        info["raio_recorte"] = float(rf[regiao].max()) if regiao.any() else 0.0
        info["recorte_limitado"] = bool(lim < r + 19.0)
        if not regiao.any() or rf[regiao].max() < lim - 1.0:
            break                                       # o recorte acabou sozinho antes do limite: é a rebarba toda
    # o disco debaixo do pé (quando o escaneamento fechou a malha por baixo dele)
    regiao |= (rf <= r + 0.3) & (alt_f > -1.5) & (alt_f < h_baixo) & deste_lado & ~aro
    # margem: entra na superfície limpa
    vr = np.zeros(m.n_vertices, bool)
    vr[F[regiao].ravel()] = True
    if vr.any() and opc["margem"] > 0:
        d, _ = cKDTree(m.V[vr]).query(m.V, distance_upper_bound=float(opc["margem"]))
        perto = np.isfinite(d)
        regiao |= perto[F].all(1) & (alt_f < h_baixo) & deste_lado & ~aro
    # ---- 3. o corpo do alvo: o que ficou solto do resto da peça
    fica = ~regiao
    rot, n = _componentes(m, fica)
    area = np.bincount(rot[fica], weights=m.A[fica], minlength=n)
    na_orla = np.zeros(n, bool)
    na_orla[np.unique(rot[aro & fica])] = True
    if n:
        na_orla[np.argmax(area)] = True                 # o maior pedaço é sempre a peça
    raio_env = float(alvo.get("raio_max", r)) + 3.0
    alt_env = float(alvo.get("altura", 60.0))

    def do_alvo(rot, n, quais):
        """Dos pedaços que ficaram soltos, os que estão no espaço do alvo. Uma lasca da própria malha presa só por um
        vértice, a centímetros dali, também está "solta" neste recorte, e não é do alvo."""
        peso = m.A[quais]
        area = np.maximum(np.bincount(rot[quais], weights=peso, minlength=n), 1e-12)
        alt = np.bincount(rot[quais], weights=peso * alt_f[quais], minlength=n) / area
        raio = np.bincount(rot[quais], weights=peso * rf[quais], minlength=n) / area
        return (alt > -1.0) & (alt < alt_env + 12.0) & (raio < raio_env + 0.3 * np.maximum(alt, 0.0) + 6.0)

    solto = fica & (~na_orla & do_alvo(rot, n, fica))[np.maximum(rot, 0)]
    corpo = solto.copy()
    grudado = False
    # o que ainda sobrou dentro do contorno do alvo (corpo preso à peça por outro caminho, como uma rebarba até a
    # parede): sai o que está dentro de um cone folgado em volta do eixo, e depois o que isso deixar solto
    resto = (fica & ~solto & (alt_f > h_baixo) & (alt_f < alt_env + 8.0)
             & (rf < raio_env + 0.3 * alt_f) & (zr_f > 0) & ~aro)
    if resto.any():
        # Só conta o que está ligado ao corte do pé. Outra parte da peça que passa por dentro desse cone (a palheta
        # vizinha, uma parede em frente) não tem ligação com o alvo e não pode ser tocada.
        v_reg = np.zeros(m.n_vertices, bool)
        v_reg[F[regiao].ravel()] = True
        rot, _ = _componentes(m, resto)
        ks = np.unique(rot[resto & v_reg[F].any(axis=1)])
        resto &= np.isin(rot, ks[ks >= 0])
    if resto.any():
        corpo |= resto
        fica2 = fica & ~corpo
        rot, n = _componentes(m, fica2)
        na_orla = np.zeros(n, bool)
        na_orla[np.unique(rot[aro & fica2])] = True
        if n:
            na_orla[np.argmax(np.bincount(rot[fica2], weights=m.A[fica2], minlength=n))] = True
        corpo |= fica2 & (~na_orla & do_alvo(rot, n, fica2))[np.maximum(rot, 0)]
        grudado = True
    remover = regiao | corpo
    if not remover.any():
        info["aviso"] = "não achei o pé do alvo acima da superfície da peça: nada foi retirado"
        return saida(remover)
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
            info["aviso"] = "o alvo estava grudado em outra parte da peça por uma rebarba; sobrou um toco dela"
            info["toco"] = toco

    # ---- 4. contorno do furo: apara os triângulos pendurados e mede
    tocados = np.zeros(m.n_vertices, bool)
    tocados[F[remover].ravel()] = True
    for _ in range(4):
        orelha = _orelhas(F, remover, tocados, m.n_vertices)
        if not orelha.any():
            break
        remover |= orelha & ~aro
        tocados[F[orelha].ravel()] = True
    info["retirado"] = True
    info["removidos"] = int(remover.sum())
    info.update(_contorno(m, remover))
    if info["pontas"]:
        info["nota"] = "o furo dá numa borda que já estava aberta na malha"
    return saida(remover)


def _lados(F, mascara, nv):
    """Chave (sem sentido) de cada lado dos triângulos marcados: K×3."""
    f = F[mascara].astype(np.int64)
    i, j = f, np.roll(f, -1, axis=1)
    return np.minimum(i, j) * nv + np.maximum(i, j)


def _orelhas(F, remover, tocados, nv):
    """Triângulos que ficaram presos ao resto por um lado só, com os outros dois no contorno do corte: dentes que
    só atrapalham quem for fechar o furo depois."""
    cand = ~remover & (tocados[F].sum(axis=1) >= 2)
    if not cand.any():
        return cand
    perto = ~remover & tocados[F].any(axis=1)             # os vizinhos possíveis de um candidato
    ch = _lados(F, perto, nv)
    u, cont = np.unique(ch, return_counts=True)
    livres = (cont[np.searchsorted(u, _lados(F, cand, nv))] == 1).sum(axis=1)
    out = np.zeros(len(F), bool)
    out[np.flatnonzero(cand)[livres >= 2]] = True
    return out


def _contorno(m, remover):
    """Medidas do contorno que o corte deixou: comprimento, diâmetro equivalente e quanto dele já era borda aberta."""
    F, nv = m.F, m.n_vertices
    tocados = np.zeros(nv, bool)
    tocados[F[remover].ravel()] = True
    perto = ~remover & tocados[F].any(axis=1)
    if not perto.any():
        return dict(contorno=0.0, diametro=0.0, borda=0.0, pontas=0)
    ch = _lados(F, perto, nv).ravel()
    u, cont = np.unique(ch, return_counts=True)
    livre = u[cont == 1]                                   # lados livres dos triângulos que ficaram junto ao corte
    i, j = livre // nv, livre % nv
    no_corte = tocados[i] & tocados[j]
    # um lado livre entre dois vértices do corte é contorno novo se o triângulo do outro lado saiu; se já era
    # livre antes do corte, é borda antiga da malha
    antes = _lados(F, remover | perto, nv).ravel()
    ua, ca = np.unique(antes, return_counts=True)
    ja_livre = ca[np.searchsorted(ua, livre)] == 1
    comp = np.linalg.norm(m.V[i] - m.V[j], axis=1)
    novo = no_corte & ~ja_livre
    velho = ja_livre & (tocados[i] | tocados[j])
    per = float(comp[novo].sum())
    diam = 0.0
    if novo.any():
        meio = 0.5 * (m.V[i[novo]] + m.V[j[novo]])
        centro = np.average(meio, axis=0, weights=comp[novo])
        diam = 2.0 * float(np.average(np.linalg.norm(meio - centro, axis=1), weights=comp[novo]))
    # um contorno fechado passa duas vezes por cada vértice; ponta solta = o furo dá numa borda que já existia
    pontas = int((np.bincount(np.r_[i[novo], j[novo]], minlength=1) == 1).sum())
    return dict(contorno=per, diametro=diam, borda=float(comp[velho].sum()), pontas=pontas)


def limpar(m, det, escolhidos=None, opcoes=None, log=lambda s: None):
    """Retira da malha os alvos escolhidos (índices em det['alvos']; None = todos os seguros) e os pedaços soltos.
    Devolve dict(viva=máscara dos triângulos que ficam, relatorio=[info por alvo], soltos_removidos, escolhidos)."""
    opc = dict(OPCOES)
    opc.update({k: v for k, v in (opcoes or {}).items() if v is not None})
    alvos = det["alvos"]
    if escolhidos is None:
        escolhidos = [i for i, a in enumerate(alvos) if a.get("seguro", True)]
    escolhidos = list(escolhidos)
    marcado = set(escolhidos)
    V, F = m.V, m.F
    viva = np.ones(len(F), bool)
    n_soltos = 0
    for s in det["soltos"]:
        dono = s.get("alvo")
        # pedaço de um alvo marcado sai com ele; o de um alvo desmarcado fica; os sem dono saem se a opção pedir
        if (dono is not None and dono in marcado) or (dono is None and opc["remover_soltos"]):
            viva[s["faces"]] = False
            n_soltos += 1
    eh_peca = det["eh_peca"]
    if "grade" not in m._cache:
        log("Indexando a malha…")
    arv = m.grade()
    relatorio = {}
    # alvos vizinhos são tratados no mesmo recorte local, um depois do outro
    centros = np.array([alvos[i]["centro"] + alvos[i]["eixo"] * 25.0 for i in escolhidos]) if escolhidos else np.zeros((0, 3))
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
                relatorio[escolhidos[k]] = dict(aviso="sem malha da peça em volta do alvo", retirado=False)
            continue
        # recorte local com índices próprios
        Fg = F[idx]
        vu = np.unique(Fg)
        Fl = np.searchsorted(vu, Fg).astype(np.int32)
        Vl = V[vu].astype(np.float64)
        Cl = Vl[Fl].mean(axis=1)
        dmin = np.min(np.linalg.norm(Cl[:, None, :] - centros[grupo][None], axis=2), axis=1) if len(grupo) <= 8 else \
            cKDTree(centros[grupo]).query(Cl)[0]
        aro = dmin > RAIO - 4.0
        vivo = np.ones(len(Fl), bool)
        for k in grupo:
            i = escolhidos[k]
            fora, info = cortar_local(Vl, Fl[vivo], alvos[i], aro[vivo], opc)
            vivo[np.flatnonzero(vivo)[fora]] = False
            relatorio[i] = info
            feitos += 1
            if feitos % 5 == 0 or feitos == len(escolhidos):
                log(f"Retirando alvos… {int(100 * feitos / len(escolhidos))}%")
        viva[idx[~vivo]] = False
    return dict(viva=viva, relatorio=[relatorio.get(i) for i in range(len(alvos))], soltos_removidos=n_soltos,
                escolhidos=escolhidos, removidos=int(len(viva) - np.count_nonzero(viva)))


def ligados(F, semente):
    """Dos triângulos F (K×3), os que estão ligados por algum vértice, direta ou indiretamente, aos da semente."""
    v, loc = np.unique(F, return_inverse=True)
    loc = loc.reshape(-1, 3)
    n = len(v)
    g = sparse.coo_matrix((np.ones(2 * len(loc), np.int8), (np.r_[loc[:, 0], loc[:, 1]], np.r_[loc[:, 1], loc[:, 2]])), shape=(n, n))
    _, rot = csgraph.connected_components(g, directed=False)
    rot = rot[loc[:, 0]]
    return np.isin(rot, np.unique(rot[semente]))


def contorno_do_corte(m, viva, limite=400_000):
    """Os lados entre um triângulo retirado e um que ficou: o contorno dos furos, para a tela. Devolve K×2×3."""
    F, nv = m.F, m.n_vertices
    saiu = np.flatnonzero(~viva)
    if not len(saiu):
        return np.zeros((0, 2, 3), np.float32)
    vr = np.zeros(nv, bool)
    vr[F[saiu].ravel()] = True
    junto = []                                              # triângulos que ficaram, com dois vértices no corte
    for i in range(0, len(F), 1_000_000):
        f = F[i:i + 1_000_000]
        k = np.flatnonzero((vr[f].sum(axis=1) >= 2) & viva[i:i + 1_000_000])
        if len(k):
            junto.append(k + i)
    if not junto:
        return np.zeros((0, 2, 3), np.float32)
    junto = np.concatenate(junto)
    de_fora = np.unique(_lados(F, saiu, nv).ravel())
    ch = np.unique(_lados(F, junto, nv).ravel())
    comum = ch[np.isin(ch, de_fora, assume_unique=True)]
    if len(comum) > limite:
        comum = comum[np.linspace(0, len(comum) - 1, limite).astype(np.int64)]
    return np.stack([V32(m, comum // nv), V32(m, comum % nv)], axis=1)


def V32(m, ids):
    return np.ascontiguousarray(m.V[ids], dtype=np.float32)
