"""Relatório da limpeza: o que foi retirado, com que referência cada furo foi fechado e o que conferir."""
import csv
import html
import os
import time

from . import __version__

CSS = """
*{box-sizing:border-box} body{font-family:"Segoe UI",Arial,sans-serif;font-size:11px;color:#1a1f25;margin:0;padding:14mm 12mm}
h1{font-size:18px;margin:0 0 2px} h2{font-size:12px;margin:16px 0 6px;text-transform:uppercase;letter-spacing:.6px;color:#5a6470}
.sub{color:#5a6470;margin-bottom:10px} .marca{color:#12784a;font-weight:700;letter-spacing:.5px}
table{border-collapse:collapse;width:100%} th{background:#1a1f25;color:#fff;font-weight:600;text-align:left;padding:4px 6px;font-size:10px}
td{padding:3px 6px;border-bottom:1px solid #eceef1;vertical-align:top} td.n{font-family:Consolas,monospace;white-space:nowrap}
.chip{display:inline-block;padding:1px 7px;border-radius:9px;font-size:10px;font-weight:600}
.ok{background:#e7f5ec;color:#15803d} .av{background:#fdf1e2;color:#8a5200} .no{background:#fdeaea;color:#b91c1c} .ne{background:#f3f4f6;color:#5a6470}
.grade{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0} .cx{border:1px solid #dfe2e7;border-radius:6px;padding:6px 8px}
.cx b{display:block;font-size:15px;font-family:Consolas,monospace} .nota{color:#5a6470;margin-top:12px;line-height:1.45}
@page{size:A4;margin:0} @media print{body{padding:14mm 12mm}}
"""


def _br(v, d=2):
    if v is None:
        return "—"
    return f"{float(v):.{d}f}".replace(".", ",")


def _situacao(a):
    if not a.get("retirado"):
        return "ne", "não retirado"
    if not a.get("preenchido"):
        return "no", "retirado, furo aberto"
    if a.get("aviso") or (a.get("degrau") or 0) > 0.8:
        return "av", "conferir"
    return "ok", "retirado e fechado"


def linhas(resumo):
    out = []
    for a in resumo["alvos"]:
        cls, sit = _situacao(a)
        obs = a.get("aviso") or ""
        if a.get("retirado") and a.get("preenchido") and (a.get("degrau") or 0) > 0.8:
            obs = (obs + "; " if obs else "") + f"o contorno do furo fica até {_br(a['degrau'], 1)} mm fora da referência"
        out.append(dict(n=a["i"] + 1, tipo=a["nome"] + (" (pé amassado)" if a.get("deformado") else ""), conf=a["confianca"],
                        x=a["centro"][0], y=a["centro"][1], z=a["centro"][2], ref=a.get("referencia") or "—",
                        sigma=a.get("sigma"), area=a.get("area"), cls=cls, sit=sit, obs=obs))
    return out


def gerar_html(resumo, destino, ident=None):
    ident = ident or {}
    ls = linhas(resumo)
    n_ret = sum(1 for a in resumo["alvos"] if a.get("retirado"))
    n_ok = sum(1 for l in ls if l["cls"] == "ok")
    n_av = sum(1 for l in ls if l["cls"] in ("av", "no"))
    e = html.escape
    corpo = [f"<div class='marca'>CLEANMOLD</div><h1>Relatório de limpeza da malha</h1>",
             f"<div class='sub'>{e(resumo['arquivo'])} · {time.strftime('%d/%m/%Y %H:%M')}"
             + (f" · peça {e(ident['peca'])}" if ident.get("peca") else "")
             + (f" · responsável {e(ident['responsavel'])}" if ident.get("responsavel") else "") + "</div>",
             "<div class='grade'>",
             f"<div class='cx'>Alvos retirados<b>{n_ret}</b></div>",
             f"<div class='cx'>Fechados sem ressalva<b>{n_ok}</b></div>",
             f"<div class='cx'>A conferir<b>{n_av}</b></div>",
             f"<div class='cx'>Pedaços soltos apagados<b>{resumo.get('soltos_removidos', 0)}</b></div>",
             "</div>",
             f"<div class='sub'>Malha original: {resumo['triangulos']:,} triângulos · malha limpa: {(resumo.get('triangulos_limpa') or 0):,} triângulos · "
             f"margem {_br(resumo['opcoes']['margem'], 1)} mm · alcance {_br(resumo['opcoes']['alcance'], 1)} mm</div>".replace(",", ".").replace(". ", ", ", 0),
             "<h2>Alvos</h2><table><tr><th>Nº</th><th>Tipo</th><th>Confiança</th><th>Posição do pé (X; Y; Z) mm</th>"
             "<th>Referência do remendo</th><th>Ruído da ref. (mm)</th><th>Área (mm²)</th><th>Situação</th><th>Observação</th></tr>"]
    for l in ls:
        corpo.append(f"<tr><td class='n'>{l['n']}</td><td>{e(l['tipo'])}</td><td class='n'>{_br(100 * l['conf'], 0)} %</td>"
                     f"<td class='n'>{_br(l['x'], 1)}; {_br(l['y'], 1)}; {_br(l['z'], 1)}</td><td>{e(l['ref'])}</td>"
                     f"<td class='n'>{_br(l['sigma'], 3)}</td><td class='n'>{_br(l['area'], 0)}</td>"
                     f"<td><span class='chip {l['cls']}'>{e(l['sit'])}</span></td><td>{e(l['obs'])}</td></tr>")
    corpo.append("</table>")
    corpo.append("<p class='nota'><b>Como ler.</b> A referência é a superfície ajustada à peça em volta do pé do alvo; o remendo é gerado "
                 "sobre ela e emendado no contorno do furo. O ruído é o espalhamento dos pontos da peça em torno dessa referência: é a "
                 "precisão que se pode esperar do remendo. “Conferir” marca os casos em que o contorno do furo não assentou todo na "
                 "referência (rebarba do escaneamento, ressalto ou parede junto ao alvo): olhe esses remendos antes de medir em cima deles. "
                 "O remendo é uma reconstrução: a superfície que estava debaixo do alvo não foi escaneada.</p>")
    corpo.append(f"<p class='nota'>Cleanmold {__version__}</p>")
    doc = f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Limpeza - {e(resumo['arquivo'])}</title><style>{CSS}</style></head><body>{''.join(corpo)}</body></html>"
    tmp = str(destino) + ".parcial"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, destino)
    return destino


def gerar_csv(resumo, destino):
    tmp = str(destino) + ".parcial"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["n", "tipo", "confianca_%", "x_mm", "y_mm", "z_mm", "referencia", "ruido_mm", "area_remendo_mm2", "situacao", "observacao"])
        for l in linhas(resumo):
            w.writerow([l["n"], l["tipo"], _br(100 * l["conf"], 0), _br(l["x"], 3), _br(l["y"], 3), _br(l["z"], 3), l["ref"],
                        _br(l["sigma"], 3) if l["sigma"] is not None else "", _br(l["area"], 1) if l["area"] is not None else "", l["sit"], l["obs"]])
    os.replace(tmp, destino)
    return destino
