"""Validação da instalação: limpa peças de teste de forma conhecida, com os alvos reais fundidos nelas, e confere
contra o gabarito. Termina com código 0 se tudo conferir.

    python testes/validar.py

O que é conferido em cada peça: todos os alvos achados, no lugar e do tipo certos; todos retirados e fechados;
erro do remendo contra a forma exata da peça; nada de alvo sobrando; e, no eixo, o sólido de revolução (cotas,
volume do STEP, macro do SolidWorks)."""
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
from cleanmold import __version__, alvos, app, cad, limpeza, malha, saidas, solido

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


def caso(nome, pasta):
    V, F, info = apoio.ler(nome)
    cam = apoio.gravar_stl(nome, pasta)
    print(f"\n== {nome}: {len(F):,}".replace(",", ".") + f" triângulos, {len(info['alvos'])} alvos")
    t = time.time()
    s = app.Sessao(cam)
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
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    print()
    if falhas:
        print(f"{falhas} conferência(s) falharam.")
        sys.exit(1)
    print("Tudo certo.")


if __name__ == "__main__":
    main()
