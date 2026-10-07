"""Peças de teste: forma exata (distância com sinal) das peças sobre as quais os alvos foram montados.

A validação usa estas funções para conferir o corte: depois da limpeza, nada pode sobrar acima da peça, e da
superfície dela só pode ter saído o disco debaixo de cada pé."""
import numpy as np


def chapa(P, lx=140.0, ly=100.0, lz=12.0):
    """Bloco de lx × ly × lz com a face de cima em z = 0."""
    q = np.abs(P - np.array([0, 0, -lz / 2])) - np.array([lx / 2, ly / 2, lz / 2])
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(1), 0)


EIXO = [(0.0, 18.0), (40.0, 18.0), (40.0, 25.0), (95.0, 25.0), (103.0, 20.0), (120.0, 20.0)]   # (z, raio)


def eixo(P, perfil=EIXO):
    """Eixo escalonado ao longo de Z: perfil de (z, raio), fechado nas duas pontas."""
    z, r = P[:, 2], np.hypot(P[:, 0], P[:, 1])
    pol = np.array([(perfil[0][0], 0.0)] + list(perfil) + [(perfil[-1][0], 0.0)])
    q = np.c_[z, r]
    d = np.full(len(q), np.inf)
    dentro = np.zeros(len(q), bool)
    for a, b in zip(pol, np.roll(pol, -1, axis=0)):
        ab = b - a
        t = np.clip(((q - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        d = np.minimum(d, np.linalg.norm(q - (a + t[:, None] * ab), axis=1))
        c = (a[1] > q[:, 1]) != (b[1] > q[:, 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = a[0] + (q[:, 1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        dentro ^= c & (q[:, 0] < xi)
    return np.where(dentro, -d, d)


def casca(P, R=260.0, lx=150.0, ly=110.0, esp=10.0):
    """Calota de raio R (convexa para +Z, topo em z = 0), recortada num retângulo, com espessura esp."""
    c = np.array([0, 0, -R])
    rho = np.linalg.norm(P - c, axis=1)
    d = np.maximum(rho - R, (R - esp) - rho)
    d = np.maximum(d, np.abs(P[:, 0]) - lx / 2)
    d = np.maximum(d, np.abs(P[:, 1]) - ly / 2)
    return d


FORMAS = dict(chapa=chapa, eixo=eixo, casca=casca)
