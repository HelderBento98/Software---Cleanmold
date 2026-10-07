"""Gera LICENCAS_DE_TERCEIROS.txt a partir das bibliotecas instaladas no Python que vai dentro do instalador.

    python licencas.py <pasta site-packages> <arquivo de saída>
"""
import email
import glob
import os
import sys

CABECALHO = """Cleanmold - programas de terceiros incluidos na instalacao
=========================================================

O Cleanmold usa os programas e bibliotecas abaixo, de codigo aberto. Cada um continua sob a licenca dos seus
autores. O texto completo de cada licenca esta na pasta do componente:
  python\\LICENSE.txt                               (Python)
  python\\Lib\\site-packages\\<nome>-<versao>.dist-info\\  (bibliotecas)
  cleanmold\\web\\vendor\\                               (three.js, three-mesh-bvh e fontes IBM Plex)

As bibliotecas sao arquivos separados e podem ser substituidas por outra versao compativel.

Python 3.13 (distribuicao WinPython)        Python Software Foundation License
three.js r160                               MIT
three-mesh-bvh 0.9.15                       MIT
IBM Plex Sans / IBM Plex Mono               SIL Open Font License 1.1

Bibliotecas Python
------------------
"""


def main(site_packages, saida):
    linhas = []
    for pasta in sorted(glob.glob(os.path.join(site_packages, "*.dist-info")), key=str.lower):
        with open(os.path.join(pasta, "METADATA"), encoding="utf-8", errors="replace") as fh:
            m = email.message_from_string(fh.read())
        lic = m.get("License-Expression") or ""
        if not lic:
            classes = [c.split(" :: ")[-1] for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
            lic = ", ".join(classes) or (m.get("License") or "").strip().split("\n")[0][:60]
        linhas.append(f"{(m.get('Name') + ' ' + m.get('Version')):44}{lic or 'ver a pasta .dist-info'}")
    with open(saida, "w", encoding="ascii", errors="replace", newline="\r\n") as fh:
        fh.write(CABECALHO + "\n".join(linhas) + "\n")
    print(len(linhas), "bibliotecas em", saida)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
