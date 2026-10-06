"""Apoio aos testes: lê as peças de teste (testes/dados/*.npz) e as grava como STL quando preciso."""
import json, os
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))


def ler(nome):
    d = np.load(os.path.join(AQUI, "dados", nome + ".npz"))
    return d["V"].astype(float), d["F"].astype(np.int64), json.loads(str(d["info"]))


def gravar_stl(nome, pasta):
    """Grava a peça de teste como STL binário em `pasta` e devolve o caminho."""
    import sys
    sys.path.insert(0, os.path.dirname(AQUI))
    from cleanmold import malha
    V, F, _ = ler(nome)
    cam = os.path.join(pasta, nome + "_com_alvos.stl")
    malha.gravar_stl(malha.Malha(V, F), cam)
    return cam
