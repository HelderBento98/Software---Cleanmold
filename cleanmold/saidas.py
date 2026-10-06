"""Arquivos que o Cleanmold grava e o sólido reconhecido (o que a interface mostra e exporta)."""
import math
import os
import shutil
import tempfile

import numpy as np

from . import app, cad, malha, pdf, relatorio, solido

NOMES = dict(stl="_limpa.stl", ply="_limpa.ply", pdf="_limpeza.pdf", html="_limpeza.html", csv="_limpeza.csv",
             step="_solido.step", macro="_solidworks.swb", dxf="_perfil.dxf")


def reconhecer(s, d=None, log=lambda t: None):
    """Reconhece a peça de revolução na malha limpa (ou na original, se ainda não foi limpa)."""
    d = d or {}
    m = s.limpa["malha"] if s.limpa else s.m
    passo = float(d.get("arredondar") or 0.01)
    if passo not in (0.001, 0.01, 0.05, 0.1, 0.5, 1.0):
        raise ValueError("Arredondamento inválido.")
    detalhe = float(d.get("detalhe") if d.get("detalhe") is not None else 1.0)
    if not (0.0 <= detalhe <= 20.0):
        raise ValueError("O menor detalhe precisa ficar entre 0 e 20 mm.")
    s.solido = None
    s.solido_erro = None
    try:
        s.solido = solido.reconhecer(m, log=log, passo_cota=passo, detalhe=detalhe)
        s.solido["da_limpa"] = s.limpa is not None
        s.solido["detalhe"] = detalhe
        log("Peça de revolução reconhecida.")
    except solido.NaoRevolucao as e:
        s.solido_erro = str(e)
        log("Não é peça de revolução: " + str(e))
    return s.solido


def resumo_solido(s):
    sol = getattr(s, "solido", None)
    if sol is None:
        return dict(erro=getattr(s, "solido_erro", None)) if getattr(s, "solido_erro", None) else None
    ents = []
    for e in sol["perfil"]:
        ents.append(dict(tipo=e["tipo"], forma=e.get("forma"), p0=[float(x) for x in e["p0"]], p1=[float(x) for x in e["p1"]],
                         c=[float(x) for x in e["c"]] if e["tipo"] == "arco" else None, r=float(e["r"]) if e["tipo"] == "arco" else None,
                         sentido=e.get("sentido")))
    outros = [[dict(tipo=e["tipo"], p0=[float(x) for x in e["p0"]], p1=[float(x) for x in e["p1"]],
                    c=[float(x) for x in e["c"]] if e["tipo"] == "arco" else None, r=float(e["r"]) if e["tipo"] == "arco" else None,
                    sentido=e.get("sentido")) for e in o] for o in sol["outros"]]
    return dict(tipo="revolucao", solido=sol["solido"], fechado=sol["fechado"],
                setor=None if sol["setor"] is None else math.degrees(sol["setor"]),
                comprimento=sol["comprimento"], raio_max=sol["raio_max"], cobertura=sol["cobertura"],
                fracao_eixo=sol["fracao_eixo"], rms=sol["rms"], tolerancia=sol["tolerancia"], passo_cota=sol["passo_cota"],
                detalhe=sol.get("detalhe", 1.0), da_limpa=sol.get("da_limpa", True),
                entidades=ents, outros=outros, cotas=solido.cotas(sol),
                ponto=[float(x) for x in sol["ponto"]], eixo=[float(x) for x in sol["eixo"]])


def solido_para_tela(s):
    sol = getattr(s, "solido", None)
    if sol is None:
        return None
    Vs, Fs = [], []
    n = 0
    for ents in [sol["perfil"]] + list(sol["outros"]):
        tmp = dict(sol)
        tmp["perfil"] = [e for e in ents if e.get("forma") != "eixo"]
        if not tmp["perfil"]:
            continue
        V, F = solido.malha_de_revolucao(tmp)
        Vs.append(V)
        Fs.append(F + n)
        n += len(V)
    V, F = np.vstack(Vs), np.vstack(Fs)
    cab = dict(blocos={}, triangulos=int(len(F)))
    return app._empacotar(cab, [("V", V.astype(np.float32)), ("I", F.astype(np.uint32))])


def salvar(s, pasta, base, itens, ident=None, log=lambda t: None):
    """Grava os arquivos pedidos. Devolve {item: caminho, ..., 'falhas': {item: motivo}}."""
    out, falhas = {}, {}
    os.makedirs(pasta, exist_ok=True)
    ml = s.limpa["malha"]
    resumo = s.resumo()

    def cam(k):
        return os.path.join(pasta, base + NOMES[k])
    for k in itens:
        try:
            if k == "stl":
                log("Gravando a malha limpa (STL)…")
                out[k] = malha.gravar_stl(ml, cam(k))
            elif k == "ply":
                log("Gravando a malha limpa (PLY)…")
                out[k] = malha.gravar_ply(ml, cam(k))
            elif k == "html":
                out[k] = relatorio.gerar_html(resumo, cam(k), ident)
            elif k == "csv":
                out[k] = relatorio.gerar_csv(resumo, cam(k))
            elif k == "pdf":
                log("Montando o relatório em PDF…")
                tmp = tempfile.mkdtemp(prefix="cleanmold_rel_")
                try:
                    h = relatorio.gerar_html(resumo, os.path.join(tmp, "relatorio.html"), ident)
                    out[k] = pdf.html_para_pdf(h, cam(k))
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            elif k in ("step", "macro"):
                sol = getattr(s, "solido", None)
                if sol is None:
                    reconhecer(s, None, log)
                    sol = s.solido
                if sol is None:
                    raise RuntimeError(getattr(s, "solido_erro", None) or "a peça não foi reconhecida como de revolução")
                if k == "step":
                    log("Montando o sólido (STEP)…")
                    out[k], eh = cad.gravar_step(sol, cam(k))
                    try:
                        out["dxf"] = cad.gravar_dxf(sol, cam("dxf"))
                    except Exception as e:                     # o DXF é um extra: não derruba o STEP
                        log(f"O perfil em DXF não saiu ({e}).")
                else:
                    out[k] = cad.gravar_macro(sol, cam(k), ident.get("peca") if ident else base)
        except OSError as e:
            falhas[k] = app.erro_de_arquivo(e)
        except Exception as e:
            falhas[k] = str(e) or type(e).__name__
    out["falhas"] = falhas
    return out
