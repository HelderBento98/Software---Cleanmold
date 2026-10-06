"""Abre o Cleanmold sem janela de console (é o que o atalho do Menu Iniciar executa).

Não depende da pasta atual: acha o programa pela posição deste arquivo. Se algo falhar antes de o programa
conseguir avisar por conta própria, mostra uma caixa de mensagem em vez de fechar em silêncio.
"""
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))


def _caixa(texto):
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, texto[-1800:], "Cleanmold", 0x10 | 0x10000 | 0x40000)
        except Exception:
            pass


def main():
    for nome in ("stdout", "stderr"):                    # pythonw não tem console
        if getattr(sys, nome) is None:
            try:
                setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass
    os.chdir(AQUI)
    if AQUI not in sys.path:
        sys.path.insert(0, AQUI)
    sys.argv = [os.path.join(AQUI, "cleanmold", "__main__.py")]
    try:
        import runpy
        runpy.run_module("cleanmold", run_name="__main__", alter_sys=True)
    except SystemExit:
        raise
    except ImportError as e:
        _caixa("O Cleanmold não conseguiu abrir: falta uma biblioteca neste computador "
               f"({getattr(e, 'name', None) or e}).\n\nRode o instalador do Cleanmold de novo.")
        sys.exit(1)
    except Exception:
        import traceback
        _caixa("O Cleanmold não conseguiu abrir.\n\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
