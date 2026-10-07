"""Validação da instalação: limpa peças de teste de forma conhecida, com os alvos reais fundidos nelas, e confere
contra o gabarito. Termina com código 0 se tudo conferir.

    python testes/validar.py

O que é conferido em cada peça: todos os alvos achados, no lugar e do tipo certos; todos retirados e fechados;
erro do remendo contra a forma exata da peça; nada de alvo sobrando; e, no eixo, o sólido de revolução (cotas,
volume do STEP, macro do SolidWorks). Depois, as ferramentas de malha: otimizar (desvio medido dentro da
tolerância, e os alvos achados e retirados na malha otimizada), pincel, furos, alisar, reparo automático e desfazer."""
import os, shutil, sys, tempfile, time
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
from cleanmold import __version__, alvos, app, cad, limpeza, malha, otimizar, reparo, saidas, solido

# limites (mm)
POSICAO = 3.0            # erro de posição do pé de um alvo
ERRO_MEDIO = 0.05        # erro médio do remendo contra a forma exata
ERRO_MAX = 0.40          # erro máximo do remendo
SOBRA = 0.50             # o que pode ficar acima da peça depois da limpeza

falhas = 0


def confere(ok, texto):
    global falhas
    if not ok:
        falhas += 1
    print(("   ok    " if ok else "   ERRO  ") + texto)
    return ok


def caso(nome, pasta, otimizar_tol=None):
    V, F, info = apoio.ler(nome)
    cam = apoio.gravar_stl(nome, pasta)
    print(f"\n== {nome}{' (otimizada ao abrir)' if otimizar_tol else ''}: {len(F):,}".replace(",", ".") + f" triângulos, {len(info['alvos'])} alvos")
    t = time.time()
    s = app.Sessao(cam, otimizar_tol=otimizar_tol)
    if otimizar_tol:
        o = s.otimizacao
        confere(o["depois"] < 0.75 * o["antes"], f"otimização: {o['antes']:,} -> {o['depois']:,} triângulos".replace(",", "."))
        d = o.get("desvio")
        confere(d is not None and d["maximo"] <= 1.5 * otimizar_tol and d["p99"] <= otimizar_tol,
                (f"desvio medido: médio {d['medio']:.3f}, 99% abaixo de {d['p99']:.3f}, máximo {d['maximo']:.3f} mm (tolerância {otimizar_tol})"
                 if d else "o desvio não pôde ser medido"))
        confere(o["bordas_iguais"], "a borda da malha e o contorno dos furos não mudaram")
    s.analisar()
    det = s.det
    seguros = [a for a in det["alvos"] if a["seguro"]]
    confere(len(seguros) == len(info["alvos"]), f"{len(seguros)} alvos achados (gabarito: {len(info['alvos'])})")
    usados = set()
    for v in info["alvos"]:
        d = [np.linalg.norm(np.array(v["ponto"]) - a["centro"]) for a in seguros]
        k = int(np.argmin(d)) if d else -1
        ok = k >= 0 and d[k] < POSICAO and k not in usados
        usados.add(k)
        tipo_ok = ok and (seguros[k]["tipo"] == v["tipo"] or v.get("dificil"))
        confere(ok and tipo_ok, f"alvo {v['tipo']} em ({v['ponto'][0]:.0f}; {v['ponto'][1]:.0f}; {v['ponto'][2]:.0f}): "
                + (f"achado a {d[k]:.2f} mm como {seguros[k]['tipo']}" if k >= 0 else "não achado"))
    s.limpar()
    r = s.resumo()
    ml = s.limpa["malha"]
    ret = [a for a in r["alvos"] if a["retirado"]]
    confere(len(ret) == len(seguros) and all(a["preenchido"] for a in ret), f"{sum(1 for a in ret if a['preenchido'])} de {len(ret)} furos fechados")
    forma = pecas.FORMAS[info["forma"]]
    vr = np.unique(ml.F[s.limpa["remendo"]])
    e = np.abs(forma(ml.V[vr], **info["params"])) if len(vr) else np.array([9.0])
    confere(e.mean() <= ERRO_MEDIO and e.max() <= ERRO_MAX, f"erro do remendo: médio {e.mean():.3f} mm, máximo {e.max():.3f} mm (limites {ERRO_MEDIO} e {ERRO_MAX})")
    sobra = float(forma(ml.V, **info["params"]).max())
    confere(sobra <= SOBRA, f"maior sobra acima da peça: {sobra:.2f} mm (limite {SOBRA})")
    confere(ml.componentes()[1] == 1, "a malha limpa é um pedaço só")
    # limpar de novo não pode achar mais nada
    det2 = alvos.detectar(ml)
    confere(not det2["alvos"], f"nenhum alvo na malha limpa ({len(det2['alvos'])} achados)")
    print(f"   {time.time() - t:.0f} s")
    return s, info, r


def ferramentas(pasta):
    """Pincel, furos, alisar, reparo automático e desfazer, pela mesma sessão que a interface usa."""
    # ---- pincel: cada alvo do eixo retirado com um toque no pé, sem passar pela procura
    V, F, info = apoio.ler("eixo")
    forma = pecas.FORMAS[info["forma"]]
    cam = apoio.gravar_stl("eixo", pasta)
    print("\n== ferramentas de malha (eixo, calota e chapa)")
    t = time.time()
    s = app.Sessao(cam)
    s.analisar()
    n0 = s.m.n_faces
    erros, fechados = [], 0
    for a in info["alvos"]:
        q = np.array(a["ponto"]) + 3.0 * np.array(a["normal"])
        s.pintar("antes", [[q[0], q[1], q[2], 12.5, 1]])
        i = s.apagar_selecao("antes", preencher=True)
        fechados += int(i["furos"] >= 1 and i["fechados"] == i["furos"])
        vr = np.unique(s.m.F[s.rem_m]) if s.rem_m is not None else np.zeros(0, int)
        erros.append(np.abs(forma(s.m.V[vr], **info["params"])) if len(vr) else np.array([9.0]))
    confere(fechados == len(info["alvos"]), f"pincel: {fechados} de {len(info['alvos'])} alvos retirados e fechados com um toque no pé")
    e = erros[-1]
    confere(e.mean() <= ERRO_MEDIO and e.max() <= ERRO_MAX, f"pincel: erro dos remendos médio {e.mean():.3f} mm, máximo {e.max():.3f} mm")
    confere(float(forma(s.m.V, **info["params"]).max()) <= SOBRA and s.m.componentes()[1] == 1 and len(s.m.bordas()[0]) == 0,
            "pincel: nada sobrando acima da peça, um pedaço só, malha fechada")
    confere(not s.det["alvos"], f"pincel: os alvos retirados saíram da lista ({len(s.det['alvos'])} ficaram)")
    for _ in range(len(info["alvos"])):
        s.desfazer()
    confere(s.m.n_faces == n0 and len(s.det["alvos"]) == len(info["alvos"]) and s.pode_desfazer() is None, "desfazer devolve a malha e a lista de alvos como estavam")
    # ---- furos: abre furos na peça limpa (cilindros, face, ressalto) e fecha
    s.limpar()
    furos_ = [((25, 0, 60), 6), ((0, 18, 15), 5), ((5, 5, 120), 6), ((-18, 0, 40), 5), ((0, 25, 41.5), 4), ((-25, 0, 70), 1.2)]
    for c, r in furos_:
        s.pintar("depois", [[c[0], c[1], c[2], r, 1]])
        s.apagar_selecao("depois", preencher=False)
    lac = s.furos("depois")
    confere(len(lac) == len(furos_), f"furos: {len(lac)} contornos abertos achados (abertos: {len(furos_)})")
    res = s.preencher_furos("depois", ate=30.0)
    ml = s.limpa["malha"]
    vr = np.unique(ml.F[s.limpa["remendo"]])
    e = np.abs(forma(ml.V[vr], **info["params"]))
    confere(res["fechados"] == len(furos_) and len(ml.bordas()[0]) == 0, f"furos: {res['fechados']} de {len(furos_)} fechados; malha fechada de novo")
    confere(e.mean() <= ERRO_MEDIO and e.max() <= ERRO_MAX, f"furos: erro dos remendos médio {e.mean():.3f} mm, máximo {e.max():.3f} mm")
    confere(any("cilindro" in x for x in res["referencias"]) and any(x.startswith("plano") for x in res["referencias"]),
            "furos: fechados seguindo a forma em volta (" + ", ".join(res["referencias"]) + ")")
    # ---- canto de três faces arrancado: nenhuma superfície simples explica; entra o preenchimento geral
    sc = app.Sessao(apoio.gravar_stl("chapa", pasta))
    sc.analisar()
    sc.limpar()
    sc.pintar("depois", [[70, 50, 0, 7, 1]])
    i = sc.apagar_selecao("depois", preencher=True)
    mc = sc.limpa["malha"]
    vr = np.unique(mc.F[sc.limpa["remendo"]])
    perto = vr[np.linalg.norm(mc.V[vr] - np.array([70.0, 50.0, 0.0]), axis=1) < 9.0]
    e = np.abs(pecas.chapa(mc.V[perto]))
    confere(i["fechados"] == i["furos"] >= 1 and len(mc.bordas()[0]) == 0 and reparo._invertidos(mc)[1].sum() == 0,
            "canto de três faces: fechado (" + ", ".join(sorted(set(i["referencias"]))) + "), malha fechada e sem triângulo virado")
    confere(e.max() < 4.0, f"canto de três faces: o remendo arredonda o canto (corte de Ø 14 mm), a até {e.max():.2f} mm da quina exata")
    # ---- alisar: um calombo posto na calota
    V, F, info = apoio.ler("casca")
    forma = pecas.FORMAS[info["forma"]]
    s = app.Sessao(apoio.gravar_stl("casca", pasta))
    s.analisar()
    s.limpar()
    ml = s.limpa["malha"]
    d = np.linalg.norm(ml.V - np.array([0.0, 0.0, 0.0]), axis=1)
    perto = d < 5
    V2 = ml.V.copy()
    V2[perto] += np.array([0, 0, 1.0]) * (0.6 * np.exp(-(d[perto] / 2.5) ** 2))[:, None]
    s.limpa = dict(s.limpa, malha=malha.Malha(V2, ml.F))
    e0 = float(np.abs(forma(s.limpa["malha"].V[perto], **info["params"])).max())
    s.pintar("depois", [[0, 0, 0.5, 8, 1]])
    s.alisar_selecao("depois", 3)
    e1 = float(np.abs(forma(s.limpa["malha"].V[perto], **info["params"])).max())
    confere(e1 < 0.2 * e0 and e1 < 0.15, f"alisar (refazer liso): calombo de {e0:.2f} mm cai para {e1:.2f} mm")
    # ---- reparo automático: defeitos postos de propósito na chapa
    s = app.Sessao(apoio.gravar_stl("chapa", pasta))
    s.analisar()
    s.limpar()
    ml = s.limpa["malha"]
    ml = reparo.apagar(ml, reparo.pintar(ml, None, [(-40, -20, 0, 2.0, 1)]), preencher=False, soltos=False)["malha"]      # furo pequeno
    F2, V2 = ml.F.copy().astype(np.int64), ml.V.copy()
    sel = reparo.pintar(ml, None, [(30, 20, 0, 6, 1)])
    F2[sel] = F2[sel][:, ::-1]                                                     # triângulos virados
    nv = len(V2)
    V2 = np.vstack([V2, [[0, 0, 30], [1, 0, 30], [0, 1, 30], [0, 0, 31]]])        # pedaço solto
    F2 = np.vstack([F2, [[nv, nv + 2, nv + 1], [nv, nv + 1, nv + 3], [nv + 1, nv + 2, nv + 3], [nv + 2, nv, nv + 3]]])
    f0 = ml.F[1000]
    nv = len(V2)
    V2 = np.vstack([V2, [ml.V[f0[0]] + ml.N[1000] * 0.5]])                         # lasca numa aresta
    F2 = np.vstack([F2, [[f0[0], f0[1], nv]]])
    ruim = malha.Malha(V2, F2)
    s.limpa = dict(s.limpa, malha=ruim, remendo=np.zeros(ruim.n_faces, bool))
    d0 = s.diagnosticar("depois")
    confere(d0["invertidos"] > 0 and d0["soltos"] >= 1 and d0["nao_variedade"] == 1 and d0["furos"] == 1,
            f"exame: {d0['invertidos']} pares virados, {d0['soltos']} soltos, {d0['nao_variedade']} aresta com três triângulos, {d0['furos']} furo")
    s.reparar("depois", furos_ate=10.0)
    d1 = s.diagnosticar("depois")
    confere(d1["invertidos"] == 0 and d1["soltos"] == 0 and d1["nao_variedade"] == 0 and d1["furos"] == 0 and d1["fechada"],
            "reparo automático: nada virado, nada solto, nenhuma lasca, malha fechada")
    vol = s.limpa["malha"].volume()
    confere(abs(vol - 140 * 100 * 12) / (140 * 100 * 12) < 0.002, f"reparo automático: volume da chapa {vol:.0f} mm³ (exato: 168000)")
    print(f"   {time.time() - t:.0f} s")


def main():
    print(f"Cleanmold {__version__} - validação")
    pasta = tempfile.mkdtemp(prefix="cleanmold_validar_")
    try:
        # ---- chapa: plano, e um alvo com o pé passando da aresta
        s, info, r = caso("chapa", pasta)
        confere(all((a["referencia"] or "").startswith("plano") for a in r["alvos"] if a["retirado"]), "referência dos remendos: plano")
        confere(any((a["arestas"] or 0) >= 1 for a in r["alvos"]), "aresta viva refeita no alvo da beirada")
        confere(len(s.limpa["malha"].bordas()[0]) == 0, "malha limpa fechada (sem arestas livres)")

        # ---- eixo: cilindros, face da ponta, e o sólido de revolução
        s, info, r = caso("eixo", pasta)
        refs = [a["referencia"] or "" for a in r["alvos"] if a["retirado"]]
        confere(sum(1 for x in refs if x.startswith("cilindro")) == 3 and sum(1 for x in refs if x.startswith("plano")) == 1,
                "referência dos remendos: 3 em cilindro e 1 em plano")
        for a in r["alvos"]:
            if (a["referencia"] or "").startswith("cilindro"):
                d = float(a["referencia"].split("Ø")[1].split("mm")[0].replace(",", "."))
                confere(min(abs(d - 36.0), abs(d - 50.0)) < 0.15, f"cilindro de referência Ø {d:.2f} mm (peça: 36 ou 50)")
        confere(len(s.limpa["malha"].bordas()[0]) == 0, "malha limpa fechada (sem arestas livres)")
        saidas.reconhecer(s)
        sol = s.solido
        if confere(sol is not None and sol["solido"], "peça de revolução reconhecida como sólido fechado"):
            ct = solido.cotas(sol)
            diam = sorted(c["valor"] for c in ct if c["tipo"] == "diametro")
            pos = sorted(c["valor"] for c in ct if c["tipo"] == "posicao")
            confere(len(diam) == 3 and np.allclose(diam, [36, 40, 50], atol=0.06), "diâmetros " + ", ".join(f"{x:.2f}" for x in diam) + " (gabarito 36, 40, 50)")
            confere(len(pos) == 3 and np.allclose(pos, [0, 40, 120], atol=0.15), "faces em z = " + ", ".join(f"{x:.2f}" for x in pos) + " (gabarito 0, 40, 120)")
            confere(sol["cobertura"] > 0.98, f"o perfil explica {100 * sol['cobertura']:.0f}% da malha")
            out = saidas.salvar(s, os.path.join(pasta, "saida"), "validacao", ["stl", "ply", "html", "csv", "step", "macro"],
                                ident=dict(peca="VALIDAÇÃO", responsavel=""))
            ruins = out.pop("falhas", {})
            inicio = dict(html=b"<!doctype html", step=b"ISO-10303-21", dxf=b"0", macro=b"' ---", ply=b"ply")
            for item in ("stl", "ply", "html", "csv", "step", "dxf", "macro"):
                c = out.get(item)
                ok = bool(c) and os.path.isfile(c) and os.path.getsize(c) > 200
                if ok and item in inicio:
                    with open(c, "rb") as fh:
                        ok = fh.read(64).lstrip(b"\xef\xbb\xbf \r\n").lower().startswith(inicio[item].lower())
                confere(ok, f"arquivo {item.upper()} gravado" + ("" if ok else f" ({ruins.get(item, 'vazio ou ausente')})"))
            if out.get("step"):
                import cadquery as cq
                forma = cq.importers.importStep(out["step"]).val()
                import math
                vol = math.pi * (18 ** 2 * 40 + 25 ** 2 * 55 + 8 / 3 * (25 ** 2 + 25 * 20 + 20 ** 2) + 20 ** 2 * 17)
                confere(len(forma.Solids()) == 1, "STEP com um corpo só (abre como peça)")
                confere(abs(forma.Volume() - vol) / vol < 0.003, f"volume do STEP {forma.Volume():.0f} mm³ (gabarito {vol:.0f})")
            if out.get("macro"):
                with open(out["macro"], "rb") as fh:
                    txt = fh.read().decode("cp1252")
                confere(all(x in txt for x in ("Sub main()", "CreateCenterLine", "CreateLine", "FeatureRevolve2", "AddDimension2")) and "\r\n" in txt,
                        "macro do SolidWorks com esboço, cotas e revolução")
            if out.get("stl"):
                m2 = malha.carregar(out["stl"])
                confere(m2.n_faces == s.limpa["malha"].n_faces, "o STL gravado volta com os mesmos triângulos")

        # ---- calota aberta: superfície curva, alvo na borda da malha, pé amassado, pedaços soltos
        s, info, r = caso("casca", pasta)
        confere(sum(1 for a in r["alvos"] if a["aviso"] and "borda da malha" in a["aviso"]) == 2, "dois alvos na borda da malha, com a borda refeita")
        confere(r["soltos_removidos"] >= 2, f"{r['soltos_removidos']} pedaços soltos apagados")
        # ---- o que não é de revolução não pode virar sólido
        V, F, _ = apoio.ler("chapa")
        try:
            solido.reconhecer(malha.Malha(V, F))
            confere(False, "a chapa foi aceita como peça de revolução")
        except solido.NaoRevolucao:
            confere(True, "a chapa é recusada como peça de revolução")
        # ---- malha otimizada ao abrir: tudo de novo, com menos triângulos
        if otimizar.disponivel():
            s, info, r = caso("chapa", pasta, otimizar_tol=0.05)
            confere(len(s.limpa["malha"].bordas()[0]) == 0, "malha limpa fechada (sem arestas livres)")
            s, info, r = caso("casca", pasta, otimizar_tol=0.05)
        else:
            confere(False, "a biblioteca de redução de malha (pyfqmr) não está instalada")
        ferramentas(pasta)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    print()
    if falhas:
        print(f"{falhas} conferência(s) falharam.")
        sys.exit(1)
    print("Tudo certo.")


if __name__ == "__main__":
    main()
