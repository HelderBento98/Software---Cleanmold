"""Uso em linha de comando:

    python -m cleanmold                       abre a interface
    python -m cleanmold malha.stl             limpa e grava malha_limpa.stl e o relatório ao lado da malha
    python -m cleanmold malha.stl --saida pasta --solido --margem 1,5
"""
import argparse, os, sys


class _Opcoes(argparse.ArgumentParser):
    """Erro de opção em uma linha, em português, sem o bloco "usage" em inglês."""
    def error(self, message):
        m = message
        for ingles, portugues in (("invalid float value", "não é um número"), ("invalid _dec value", "não é um número"),
                                  ("unrecognized arguments", "opção desconhecida"), ("expected one argument", "falta o valor"), ("argument ", "")):
            m = m.replace(ingles, portugues)
        print("ERRO: " + m + ". Use --help para ver as opções.", file=sys.stderr)
        sys.exit(2)


def _dec(texto):
    """Número com vírgula ou ponto decimal (--margem 1,5)."""
    return float(str(texto).strip().replace(",", "."))


def main(argv=None):
    ap = _Opcoes(prog="cleanmold", description="Retira os alvos de escaneamento de uma malha 3D e fecha os furos pela superfície vizinha")
    ap.add_argument("malha", nargs="?", help="arquivo STL / PLY / OBJ / OFF")
    ap.add_argument("--gui", action="store_true", help="abrir a interface (padrão quando não se informa a malha)")
    ap.add_argument("--saida", help="pasta de saída (padrão: pasta da malha)")
    ap.add_argument("--margem", type=_dec, default=None, help="mm retirados a mais em volta do recorte (padrão 1,2)")
    ap.add_argument("--alcance", type=_dec, default=None, help="mm em volta do pé onde rebarbas grudadas são recortadas (padrão 8)")
    ap.add_argument("--manter-soltos", action="store_true", help="não apagar os pedaços soltos")
    ap.add_argument("--todos", action="store_true", help="retirar também os alvos de confiança baixa")
    ap.add_argument("--solido", action="store_true", help="reconhecer peça de revolução e gravar STEP, DXF e macro do SolidWorks")
    ap.add_argument("--ply", action="store_true", help="gravar também a malha limpa em PLY")
    ap.add_argument("--peca", help="identificação da peça / nº do desenho")
    ap.add_argument("--responsavel", help="responsável")
    a = ap.parse_args(argv)
    if a.gui or not a.malha:
        from .servidor import main as servidor_main
        servidor_main()
        return
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo and fluxo.reconfigure(errors="replace")
        except Exception:
            pass
    try:
        _linha_de_comando(a)
    except OSError as e:
        from .app import erro_de_arquivo
        print(f"ERRO: {erro_de_arquivo(e)}" + (f": {e.filename}" if getattr(e, "filename", None) else ""), file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, ValueError) as e:
        print("ERRO: " + str(e), file=sys.stderr)
        sys.exit(2)


def _linha_de_comando(a):
    from . import app, saidas
    if not os.path.isfile(a.malha):
        raise ValueError(f"a malha: arquivo não encontrado: {a.malha}")
    if a.saida and os.path.exists(a.saida) and not os.path.isdir(a.saida):
        raise ValueError(f"--saida: {a.saida} é um arquivo, não uma pasta.")
    s = app.Sessao(a.malha, log=print)
    s.analisar()
    alvos_ = s.det["alvos"]
    for i, al in enumerate(alvos_):
        print(f"  alvo {i + 1}: {al['nome']}{' (pé amassado)' if al.get('deformado') else ''}, confiança {100 * al['confianca']:.0f}%"
              f"{'' if al['seguro'] else ' - baixa'}, pé em ({al['centro'][0]:.1f}; {al['centro'][1]:.1f}; {al['centro'][2]:.1f})")
    escolha = list(range(len(alvos_))) if a.todos else None
    s.limpar(escolha, dict(margem=a.margem, alcance=a.alcance, remover_soltos=not a.manter_soltos))
    r = s.resumo()
    n_ok = sum(1 for x in r["alvos"] if x["retirado"] and x["preenchido"] and not x["aviso"] and (x["degrau"] or 0) <= 0.8)
    n_ret = sum(1 for x in r["alvos"] if x["retirado"])
    print(f"{n_ret} alvos retirados; {n_ok} fechados sem ressalva; {r['soltos_removidos']} pedaços soltos apagados")
    for x in r["alvos"]:
        if x["retirado"] and (x["aviso"] or not x["preenchido"] or (x["degrau"] or 0) > 0.8):
            print(f"  CONFERIR alvo {x['i'] + 1}: {x['aviso'] or ''}" + (f" contorno até {x['degrau']:.1f} mm fora da referência" if (x["degrau"] or 0) > 0.8 else ""))
    itens = ["stl", "html", "csv"] + (["ply"] if a.ply else [])
    if a.solido:
        saidas.reconhecer(s, None, log=print)
        if s.solido is None:
            print("AVISO: " + (s.solido_erro or "a peça não foi reconhecida como de revolução"))
        else:
            itens += ["step", "macro"]
    pasta = a.saida or os.path.dirname(os.path.abspath(a.malha))
    os.makedirs(pasta, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.malha))[0]
    out = saidas.salvar(s, pasta, base, itens, ident=dict(peca=a.peca, responsavel=a.responsavel), log=lambda t: None)
    falhas = out.pop("falhas", {})
    print("\nArquivos:")
    for k, v in out.items():
        print(f"  {k}: {v}")
    for k, v in falhas.items():
        print(f"  {k}: NAO GERADO - {v}")


def _aviso_de_partida(msg):
    """No Windows a janela preta fecha junto com o erro: mostra numa caixa de mensagem."""
    try:
        print(msg)
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "O Cleanmold não conseguiu abrir.\n\n" + msg[-1500:], "Cleanmold", 0x10 | 0x10000 | 0x40000)
        except Exception:
            pass


def _sem_console():
    """Aberto pelo atalho (pythonw) não existe console: saída padrão vazia vira um destino que aceita tudo."""
    for nome in ("stdout", "stderr"):
        if getattr(sys, nome) is None:
            try:
                setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


if __name__ == "__main__":
    _sem_console()
    interface = len(sys.argv) < 2 or "--gui" in sys.argv
    try:
        main()
    except SystemExit:
        raise
    except ImportError as e:
        if interface:
            _aviso_de_partida(f"Falta uma biblioteca do Cleanmold neste Python ({getattr(e, 'name', None) or e}).\n\n"
                              "Rode de novo o instalador do Cleanmold (ou o INSTALAR.bat, se você usa o pacote .zip) e abra de novo.\n\n"
                              f"Python usado: {sys.executable}")
            sys.exit(1)
        raise
    except Exception:
        import traceback
        if interface:
            _aviso_de_partida(traceback.format_exc())
            sys.exit(1)
        raise
