"""Validação da instalação: retira os alvos de peças de teste de forma conhecida, com os alvos reais fundidos nelas,
e confere contra o gabarito. Termina com código 0 se tudo conferir.

    python testes/validar.py

O que é conferido em cada peça: todos os alvos achados, no lugar e do tipo certos; todos retirados; nada de alvo
sobrando acima da peça; o furo de cada alvo do tamanho do pé mais a margem, e nada mais da peça retirado; a malha
que fica é a original, triângulo por triângulo; e o arquivo gravado volta igual. Depois: alvo desmarcado fica
inteiro, alvo indicado à mão, desfazer, a vista 3D e a linha de comando."""
import os, shutil, subprocess, sys, tempfile, time
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))
sys.path.insert(0, AQUI)
for saida in (sys.stdout, sys.stderr):                  # o console do Windows pode não ter µ, Ø, ç
    try:
        saida.reconfigure(errors="replace")
    except Exception:
        pass
import numpy as np
import apoio, pecas
from cleanmold import __version__, alvos, app, malha

# limites (mm)
POSICAO = 3.0            # erro de posição do pé de um alvo
SOBRA = 0.50             # o que pode ficar acima da peça depois da limpeza
FOLGA = 2.0              # quanto o furo pode passar do pé mais a margem (os triângulos não acompanham um círculo)
FOLGA_DIFICIL = 5.0      # idem, num alvo de pé amassado ou com rebarba

falhas = 0


def confere(ok, texto):
    global falhas
    if not ok:
        falhas += 1
    print(("   ok    " if ok else "   ERRO  ") + texto)
    return ok


def _linhas(V):
    """Cada vértice como um bloco de bytes, para comparar conjuntos de vértices bit a bit."""
    V = np.ascontiguousarray(V, dtype=np.float32) + np.float32(0.0)
    return V.view([("", np.void, 12)]).ravel()


def n_contornos(m):
    """Nº de contornos abertos (laços de arestas livres) de uma malha pequena."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    lados = m.bordas()[0]
    if not len(lados):
        return 0
    v = np.unique(lados)
    loc = np.searchsorted(v, lados)
    return connected_components(coo_matrix((np.ones(len(loc)), (loc[:, 0], loc[:, 1])), shape=(len(v),) * 2), directed=False)[0]


def caso(nome, pasta):
    V, F, info = apoio.ler(nome)
    cam = apoio.gravar_stl(nome, pasta)
    print(f"\n== {nome}: {len(F):,}".replace(",", ".") + f" triângulos, {len(info['alvos'])} alvos")
    t = time.time()
    s = app.Sessao(cam)
    m = s.m
    confere(m.n_faces == len(F) and m.V.dtype == np.float32, f"malha aberta com os {m.n_faces:,} triângulos do arquivo".replace(",", "."))
    s.analisar()
    det = s.det
    seguros = [a for a in det["alvos"] if a["seguro"]]
    confere(len(seguros) == len(info["alvos"]), f"{len(seguros)} alvos achados (gabarito: {len(info['alvos'])})")
    usados = set()
    tipos_certos = 0
    for v in info["alvos"]:
        d = [np.linalg.norm(np.array(v["ponto"]) - a["centro"]) for a in seguros]
        k = int(np.argmin(d)) if d else -1
        ok = k >= 0 and d[k] < POSICAO and k not in usados
        usados.add(k)
        # o que decide o corte é o pé (posição e diâmetro); o nome do tipo é só o rótulo da lista
        pe_ok = ok and abs(seguros[k]["raio"] - v["raio"]) < 0.6
        tipos_certos += int(ok and seguros[k]["tipo"] == v["tipo"])
        confere(ok and pe_ok, f"alvo {v['tipo']} em ({v['ponto'][0]:.0f}; {v['ponto'][1]:.0f}; {v['ponto'][2]:.0f}): "
                + (f"achado a {d[k]:.2f} mm como {seguros[k]['tipo']}, pé de Ø {2 * seguros[k]['raio']:.1f}" if k >= 0 else "não achado"))
    faceis = sum(1 for v in info["alvos"] if not v.get("dificil"))
    confere(tipos_certos >= len(info["alvos"]) - 1 and tipos_certos >= faceis - 1, f"tipo certo em {tipos_certos} de {len(info['alvos'])} alvos")
    antes = (m.V.tobytes(), m.F.tobytes())
    s.limpar()
    r = s.resumo()
    viva = s.limpa["viva"]
    confere((m.V.tobytes(), m.F.tobytes()) == antes, "a malha aberta não foi alterada pela retirada")
    ret = [a for a in r["alvos"] if a["retirado"]]
    confere(len(ret) == len(seguros) and not any(a["aviso"] for a in ret), f"{len(ret)} de {len(seguros)} alvos retirados, sem ressalva")
    forma = pecas.FORMAS[info["forma"]]
    fica = np.unique(m.F[viva])
    sobra = float(forma(m.V[fica].astype(float), **info["params"]).max())
    confere(sobra <= SOBRA, f"maior sobra acima da peça: {sobra:.2f} mm (limite {SOBRA})")
    # o que saiu da superfície da peça: só o disco debaixo de cada pé, com a margem
    saiu = np.flatnonzero(~viva & det["eh_peca"])          # (os pedaços soltos, que saem inteiros, não contam aqui)
    C = m.centros(saiu)
    C = C[np.abs(forma(C, **info["params"])) < 0.2]
    pts = np.array([v["ponto"] for v in info["alvos"]])
    dono = np.linalg.norm(C[:, None, :] - pts[None], axis=2).argmin(axis=1)
    margem = s.opcoes["margem"]
    for k, v in enumerate(info["alvos"]):
        Q = C[dono == k] - pts[k]
        n = np.array(v["normal"])
        rho = np.linalg.norm(Q - np.outer(Q @ n, n), axis=1)
        lim = v["raio"] + margem + (FOLGA_DIFICIL if v.get("dificil") else FOLGA)
        maior = float(rho.max()) if len(rho) else 0.0
        confere(len(rho) > 20 and maior <= lim, f"furo do alvo {k + 1}: até {maior:.2f} mm do centro do pé (pé de raio {v['raio']:.2f}; limite {lim:.2f})")
    ml = malha.Malha(m.V, m.F[viva])
    confere(len(np.unique(ml.pedacos()[fica])) == 1, "a malha limpa é um pedaço só")
    # limpar de novo não pode achar mais nada
    det2 = alvos.detectar(ml)
    confere(not det2["alvos"], f"nenhum alvo na malha limpa ({len(det2['alvos'])} achados)")
    print(f"   {time.time() - t:.0f} s")
    return s, info, r, ml


def arquivos(s, pasta):
    """A malha limpa gravada em STL e em PLY volta com os mesmos triângulos, e todos eles são triângulos da original."""
    out = s.salvar(os.path.join(pasta, "saida"), "validacao", ["stl", "ply"])
    ruins = out.pop("falhas", {})
    n = s.triangulos_limpa()
    orig = _linhas(s.m.V)
    for item in ("stl", "ply"):
        c = out.get(item)
        if not confere(bool(c) and os.path.isfile(c), f"arquivo {item.upper()} gravado" + ("" if c else f" ({ruins.get(item, 'ausente')})")):
            continue
        m2 = malha.carregar(c)
        confere(m2.n_faces == n, f"o {item.upper()} volta com os {n:,} triângulos da malha limpa".replace(",", "."))
        confere(bool(np.isin(_linhas(m2.V), orig).all()), f"todos os vértices do {item.upper()} são vértices da malha original, bit a bit")
    if out.get("stl") and out.get("ply"):
        t_stl, t_ply = os.path.getsize(out["stl"]), os.path.getsize(out["ply"])
        confere(t_ply < 0.5 * t_stl, f"o PLY ocupa {100 * t_ply / t_stl:.0f}% do STL, com a mesma malha")
        r = s.resumo()
        confere(r["tamanho_stl"] == t_stl and abs(r["tamanho_ply"] - t_ply) < 0.05 * t_ply, "tamanhos previstos na tela batem com os arquivos")
    return out


def extras(pasta):
    """Alvo desmarcado, alvo indicado à mão, desfazer, a vista 3D e a linha de comando."""
    print("\n== escolhas e ferramentas")
    t = time.time()
    V, F, info = apoio.ler("chapa")
    cam = os.path.join(pasta, "chapa_com_alvos.stl")
    s = app.Sessao(cam)
    s.analisar()
    # ---- um alvo desmarcado fica inteiro, com os pedaços soltos dele
    al = s.det["alvos"]
    com_soltos = [i for i, a in enumerate(al) if a["soltos"]]
    fora = com_soltos[0] if com_soltos else 0
    marca = s.marcas()
    do_alvo = marca == 2 + fora
    s.limpar([i for i in range(len(al)) if i != fora])
    viva = s.limpa["viva"]
    confere(bool(viva[do_alvo].all()) and do_alvo.sum() > 1000, f"alvo desmarcado: os {int(do_alvo.sum()):,} triângulos dele ficaram".replace(",", "."))
    confere(sum(1 for a in s.resumo()["alvos"] if a["retirado"]) == len(al) - 1, "os outros alvos saíram")
    # ---- desfazer volta à malha com os alvos, sem custo
    s.desfazer()
    confere(s.limpa is None and s.resumo()["triangulos_limpa"] is None, "desfazer: volta a malha com os alvos")
    # ---- indicar à mão: sem a procura, um clique no pé de cada alvo
    s.det = dict(s.det, alvos=[])
    s.escolha = []
    for x in s.det["soltos"]:
        x["alvo"] = None
    for v in info["alvos"]:
        p = np.array(v["ponto"]) + np.array(v["normal"]) * 3.0 + np.array([v["raio"], 0, 0])       # um ponto na parede do pé
        s.alvo_manual(p.tolist(), 2 * v["raio"] + 0.5)
    confere(sum(len(a["soltos"]) for a in s.det["alvos"]) >= 2 and all(x["alvo"] is not None for x in s.det["soltos"] if len(x["faces"]) > 500),
            "indicados à mão: os pedaços soltos de cada alvo passam a ser dele")
    s.limpar(None, dict(remover_soltos=False))
    r = s.resumo()
    s.opcoes["remover_soltos"] = True
    confere(all(a["retirado"] and a["manual"] for a in r["alvos"]) and len(r["alvos"]) == len(info["alvos"]),
            f"{len(r['alvos'])} alvos indicados à mão e retirados")
    fica = np.unique(s.m.F[s.limpa["viva"]])
    sobra = float(pecas.chapa(s.m.V[fica].astype(float)).max())
    confere(sobra <= SOBRA, f"indicados à mão: maior sobra acima da peça {sobra:.2f} mm")
    erro = max(np.linalg.norm(np.array(a["centro"]) - np.array(v["ponto"])) for a, v in zip(r["alvos"], info["alvos"]))
    confere(erro < 1.5, f"indicados à mão: clique na parede do pé, corte centrado no pé (erro de até {erro:.2f} mm)")
    s.esquecer(0)
    donos_certos = all(k in s.det["alvos"][x["alvo"]]["soltos"] for k, x in enumerate(s.det["soltos"]) if x["alvo"] is not None)
    confere(len(s.det["alvos"]) == len(info["alvos"]) - 1 and s.limpa is None and donos_certos, "alvo indicado à mão apagado da lista")
    # ---- a vista 3D: malha reduzida, e o que saiu marcado nela
    s.analisar()
    s.limpar()
    tl = app.telas(s, alvo=60_000, leve=8_000)
    n_cheia, n_leve = len(tl["origem"]), len(tl["origem_leve"])
    confere(tl["leve"] is not None and n_leve < n_cheia < s.m.n_faces, f"vista 3D: {n_cheia:,} triângulos parada e {n_leve:,} girando".replace(",", "."))
    viva = s.limpa["viva"]
    # em volta dos alvos a tela mostra todos os triângulos: o que saiu aparece inteiro
    perto = np.zeros(s.m.n_faces, bool)
    g = s.m.grade()
    for a in s.det["alvos"]:
        perto[g.bola(np.asarray(a["centro"]), float(a["raio"]) + 5.0)] = True
    na_tela = np.zeros(s.m.n_faces, bool)
    na_tela[tl["origem"]] = True
    confere(bool(na_tela[perto].all()), "vista 3D: em volta do pé de cada alvo, todos os triângulos da malha")
    pac = app.retirada_para_tela(s, tl)
    confere(len(pac) > 1000 and int((~viva[tl["origem"]]).sum()) > 1000, "vista 3D: os triângulos retirados e o contorno dos furos")
    # ---- linha de comando
    saida = os.path.join(pasta, "cli")
    p = subprocess.run([sys.executable, "-m", "cleanmold", cam, "--saida", saida, "--ply"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=os.path.join(AQUI, ".."))
    ok = p.returncode == 0 and os.path.isfile(os.path.join(saida, "chapa_com_alvos_limpa.stl")) and os.path.isfile(os.path.join(saida, "chapa_com_alvos_limpa.ply"))
    confere(ok, "linha de comando: malha limpa gravada em STL e PLY" + ("" if ok else f" ({(p.stderr or p.stdout).strip()[-200:]})"))
    print(f"   {time.time() - t:.0f} s")


def leitura(pasta):
    """A leitura do STL, que junta os vértices repetidos em duas passadas pelo arquivo, contra a leitura simples."""
    print("\n== leitura do arquivo")
    cam = os.path.join(pasta, "eixo_com_alvos.stl")
    n = malha.contar_triangulos(cam)
    V1, F1 = malha._ler_stl(cam, n)
    V2, F2 = malha._ler_stl_simples(cam, n)
    confere(len(V1) == len(V2) and np.array_equal(V1[F1], V2[F2]), f"os dois caminhos de leitura dão os mesmos {n:,} triângulos e {len(V1):,} vértices".replace(",", "."))
    # blocos pequenos: vértices que aparecem em blocos diferentes continuam sendo um só
    bloco = malha._BLOCO
    try:
        malha._BLOCO = 7001
        V3, F3 = malha._ler_stl(cam, n)
    finally:
        malha._BLOCO = bloco
    confere(np.array_equal(V1, V3) and np.array_equal(F1, F3), "o resultado não depende do tamanho do bloco de leitura")
    # índice espacial contra a conta direta
    m = malha.Malha(V1, F1)
    g = m.grade()
    C = m.centros()
    rng = np.random.default_rng(0)
    ok = True
    for _ in range(20):
        c = C[rng.integers(len(C))] + rng.normal(0, 2, 3)
        raio = float(rng.uniform(1, 25))
        ok &= np.array_equal(np.sort(g.bola(c, raio)), np.flatnonzero(np.linalg.norm(C - c, axis=1) <= raio))
    confere(bool(ok), "índice espacial: mesmos triângulos que a conta direta, em 20 bolas")
    # pedaços: aos poucos e de uma vez dão o mesmo
    a = m.pedacos()
    m._cache.pop("pedacos")
    b = m.pedacos(bloco=5000)
    confere(np.array_equal(a, b), f"pedaços da malha: {len(np.unique(a[np.unique(m.F)]))}, iguais com blocos pequenos")


def main():
    print(f"Cleanmold {__version__} - validação")
    pasta = tempfile.mkdtemp(prefix="cleanmold_validar_")
    try:
        # ---- chapa: plano, e um alvo com o pé passando da aresta
        s, info, r, ml = caso("chapa", pasta)
        confere(all((a["referencia"] or "").startswith("plano") for a in r["alvos"] if a["retirado"]), "superfície de referência dos cortes: plano")
        confere(n_contornos(ml) == len(info["alvos"]), f"{n_contornos(ml)} furos na malha limpa, um por alvo (a peça era fechada)")

        # ---- eixo: cilindros e a face da ponta
        s, info, r, ml = caso("eixo", pasta)
        refs = [a["referencia"] or "" for a in r["alvos"] if a["retirado"]]
        confere(sum(1 for x in refs if x.startswith("cilindro")) == 3 and sum(1 for x in refs if x.startswith("plano")) == 1,
                "superfície de referência dos cortes: 3 em cilindro e 1 em plano")
        for a in r["alvos"]:
            if (a["referencia"] or "").startswith("cilindro"):
                d = float(a["referencia"].split("Ø")[1].split("mm")[0].replace(",", "."))
                confere(min(abs(d - 36.0), abs(d - 50.0)) < 0.15, f"cilindro de referência Ø {d:.2f} mm (peça: 36 ou 50)")
        confere(n_contornos(ml) == len(info["alvos"]), f"{n_contornos(ml)} furos na malha limpa, um por alvo (a peça era fechada)")
        arquivos(s, pasta)

        # ---- calota aberta: superfície curva, alvo na borda da malha, pé amassado, pedaços soltos
        s, info, r, ml = caso("casca", pasta)
        confere(sum(1 for a in r["alvos"] if a["nota"] and "borda" in a["nota"]) == 2, "dois alvos na borda da malha: o furo dá na borda")
        confere(r["soltos_removidos"] >= 2, f"{r['soltos_removidos']} pedaços soltos apagados")

        leitura(pasta)
        extras(pasta)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    print()
    if falhas:
        print(f"{falhas} conferência(s) falharam.")
        sys.exit(1)
    print("Tudo certo.")


if __name__ == "__main__":
    main()
