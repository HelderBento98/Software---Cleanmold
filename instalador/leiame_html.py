"""Gera LEIA-ME.html a partir do LEIA-ME.md (o .md não abre com dois cliques no Windows)."""
import markdown, sys, os, html
pasta = sys.argv[1]
md = open(os.path.join(pasta, "LEIA-ME.md"), encoding="utf-8").read()
corpo = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
css = """
body{font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1a1f25;max-width:900px;margin:32px auto;padding:0 24px}
h1{font-size:26px;color:#0f7a4d;margin:0 0 4px} h2{font-size:19px;margin:32px 0 8px;padding-top:14px;border-top:1px solid #e3e6ea}
h3{font-size:15.5px;margin:22px 0 6px} code{font-family:Consolas,monospace;font-size:13.5px;background:#e8f5ee;padding:1px 4px;border-radius:3px}
pre{background:#f6f7f9;border:1px solid #e3e6ea;border-radius:6px;padding:10px 12px;overflow:auto} pre code{background:none;padding:0}
table{border-collapse:collapse;margin:10px 0;font-size:14px} th,td{border:1px solid #d5d9df;padding:5px 9px;text-align:left;vertical-align:top}
th{background:#1a1f25;color:#fff;font-weight:600} a{color:#0d6b43} li{margin:3px 0}
@media print{body{margin:0;max-width:none;font-size:11pt} h2{break-after:avoid}}
"""
doc = f"<!doctype html>\n<html lang='pt-BR'><head><meta charset='utf-8'><title>Cleanmold — LEIA-ME</title><style>{css}</style></head><body>\n{corpo}\n</body></html>\n"
open(os.path.join(pasta, "LEIA-ME.html"), "w", encoding="utf-8").write(doc)
print("LEIA-ME.html", len(doc) // 1024, "kB")
