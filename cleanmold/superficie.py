"""Superfície de referência ao lado do alvo: o que a peça "seria" debaixo dele.

A partir dos pontos da peça em volta do pé do alvo, escolhe o modelo mais simples que explica a vizinhança
(plano, cilindro, esfera, cone ou superfície suave de 2º grau) e sabe dizer a distância de qualquer ponto a
ele. O remendo que fecha o furo é gerado sobre esse modelo."""
import numpy as np
from scipy.optimize import least_squares

from . import ajuste


class Modelo:
    nome = "?"

    def dist(self, P):
        """Distância com sinal de cada ponto à superfície (positiva do lado de fora da peça)."""
        raise NotImplementedError

    def descricao(self):
        return self.nome


class Plano(Modelo):
    nome = "plano"

    def __init__(self, c, n):
        self.c, self.n = np.asarray(c, float), np.asarray(n, float) / np.linalg.norm(n)

    def dist(self, P):
        return (np.asarray(P) - self.c) @ self.n


class Quadrica(Modelo):
    """Altura sobre um plano como polinômio de 2º grau: superfície suave, pouco curva."""
    nome = "superfície curva suave"

    def __init__(self, c, e1, e2, n, coef):
        self.c, self.e1, self.e2, self.n, self.k = c, e1, e2, n, np.asarray(coef, float)

    def _alt(self, u, v):
        k = self.k
        return k[0] + k[1] * u + k[2] * v + k[3] * u * u + k[4] * u * v + k[5] * v * v

    def dist(self, P):
        Q = np.asarray(P) - self.c
        u, v, w = Q @ self.e1, Q @ self.e2, Q @ self.n
        gu = self.k[1] + 2 * self.k[3] * u + self.k[4] * v
        gv = self.k[2] + self.k[4] * u + 2 * self.k[5] * v
        return (w - self._alt(u, v)) / np.sqrt(1 + gu * gu + gv * gv)

    def raios(self):
        """Raios de curvatura principais no centro (mm; infinito = reto)."""
        H = np.array([[2 * self.k[3], self.k[4]], [self.k[4], 2 * self.k[5]]])
        w = np.linalg.eigvalsh(H)
        return [float(1 / abs(x)) if abs(x) > 1e-9 else float("inf") for x in w]

    def descricao(self):
        r = sorted(self.raios())
        f = lambda x: "reto" if x > 5000 else f"R {x:.0f} mm"
        return f"superfície curva suave ({f(r[0])} × {f(r[1])})"


class Cilindro(Modelo):
    nome = "cilindro"

    def __init__(self, c, a, r, sinal=1.0):
        self.c, self.a, self.r, self.s = np.asarray(c, float), np.asarray(a, float) / np.linalg.norm(a), float(r), float(sinal)

    def dist(self, P):
        Q = np.asarray(P) - self.c
        rho = np.linalg.norm(Q - np.outer(Q @ self.a, self.a), axis=1)
        return self.s * (rho - self.r)

    def descricao(self):
        return f"cilindro Ø {2 * self.r:.2f} mm" + ("" if self.s > 0 else " (furo)")


class Esfera(Modelo):
    nome = "esfera"

    def __init__(self, c, r, sinal=1.0):
        self.c, self.r, self.s = np.asarray(c, float), float(r), float(sinal)

    def dist(self, P):
        return self.s * (np.linalg.norm(np.asarray(P) - self.c, axis=1) - self.r)

    def descricao(self):
        return f"esfera R {self.r:.2f} mm" + ("" if self.s > 0 else " (côncava)")


class Cone(Modelo):
    nome = "cone"

    def __init__(self, c, a, r0, k, sinal=1.0):
        self.c, self.a, self.r0, self.k, self.s = np.asarray(c, float), np.asarray(a, float), float(r0), float(k), float(sinal)

    def dist(self, P):
        Q = np.asarray(P) - self.c
        z = Q @ self.a
        rho = np.linalg.norm(Q - np.outer(z, self.a), axis=1)
        return self.s * (rho - (self.r0 + self.k * z)) / np.sqrt(1 + self.k * self.k)

    def descricao(self):
        return f"cone de {2 * np.degrees(np.arctan(abs(self.k))):.1f}° (Ø {2 * self.r0:.1f} mm no alvo)"


def _sigma(d):
    """Espalhamento robusto dos resíduos."""
    return float(1.4826 * np.median(np.abs(d - np.median(d)))) if len(d) else float("inf")


def _dentro(d, tol):
    return float(np.mean(np.abs(d) < tol)) if len(d) else 0.0


def ajustar(P, N, c, a, tol=0.35, registro=None):
    """Escolhe o modelo da superfície em volta do ponto c (eixo do alvo a, apontando para fora da peça).

    P, N: pontos e normais da peça na vizinhança (já sem o alvo). Devolve (modelo, sigma, fração dos pontos
    que o modelo explica dentro de ±tol). O plano ganha sempre que explica tão bem quanto os outros."""
    P = np.asarray(P, float)
    c = np.asarray(c, float)
    e1, e2, a = ajuste.base_ortonormal(a)
    cands = []

    # ---- plano: parte do plano de apoio do pé e reajusta só com quem está perto dele
    pc, pn = c.copy(), a.copy()
    for faixa in (1.5, 0.9, 0.6, 0.6):
        d = (P - pc) @ pn
        s = np.abs(d) < faixa
        if s.sum() < 12:
            break
        pc, pn, _ = ajuste.plano(P[s])
        if pn @ a < 0:
            pn = -pn
    plano = Plano(pc, pn)
    d = plano.dist(P)
    cands.append((plano, _sigma(d[np.abs(d) < 3 * tol]) if (np.abs(d) < 3 * tol).sum() > 10 else 9.0, _dentro(d, tol), 0))

    # ---- superfície suave de 2º grau sobre o plano (curvatura leve: fundidos, chapas calandradas, raios grandes)
    if len(P) >= 40:
        Q = P - pc
        q1, q2, _ = ajuste.base_ortonormal(pn)
        u, v, w = Q @ q1, Q @ q2, Q @ pn
        coef = np.zeros(6)
        s = np.abs(w) < 2.0
        for faixa in (1.2, 0.8, 0.6):
            if s.sum() < 30:
                break
            A = np.c_[np.ones(s.sum()), u[s], v[s], u[s] ** 2, u[s] * v[s], v[s] ** 2]
            coef, *_ = np.linalg.lstsq(A, w[s], rcond=None)
            res = w - (coef[0] + coef[1] * u + coef[2] * v + coef[3] * u * u + coef[4] * u * v + coef[5] * v * v)
            s = np.abs(res) < faixa
        quad = Quadrica(pc, q1, q2, pn, coef)
        if min(quad.raios()) > 60.0:                # mais curvo que isso não é "leve": fica para cilindro/esfera/cone
            d = quad.dist(P)
            cands.append((quad, _sigma(d[np.abs(d) < 3 * tol]) if (np.abs(d) < 3 * tol).sum() > 10 else 9.0, _dentro(d, tol), 2))

    # ---- curvas de verdade: só vale tentar se as normais giram ao longo da vizinhança
    if N is not None and len(P) >= 60:
        S = N.T @ N / len(N)
        w_, v_ = np.linalg.eigh(S)
        if w_[1] > 0.004:                            # normais não são todas paralelas
            lado = lambda mod: 1.0 if mod.dist((c + a * 1.0)[None])[0] > mod.dist((c - a * 1.0)[None])[0] else -1.0
            # esfera
            try:
                ec, er, _ = ajuste.esfera(P)
                for _ in range(3):
                    dd = np.abs(np.linalg.norm(P - ec, axis=1) - er)
                    s_ = dd < max(3 * tol, 2.5 * _sigma(dd[dd < 3.0]) + 0.05)
                    if s_.sum() < 40 or s_.all():
                        break
                    ec, er, _ = ajuste.esfera(P[s_])
                if 5.0 < er < 3000:
                    e = Esfera(ec, er)
                    e.s = lado(e)
                    d = e.dist(P)
                    cands.append((e, _sigma(d[np.abs(d) < 3 * tol]) if (np.abs(d) < 3 * tol).sum() > 10 else 9.0, _dentro(d, tol), 2))
            except Exception:
                pass
            # cilindro: eixo = direção em que as normais não têm componente
            try:
                eixo0 = v_[:, 0]
                Qp = P - P.mean(0)
                T = Qp - np.outer(Qp @ eixo0, eixo0)
                f1, f2, _ = ajuste.base_ortonormal(eixo0)
                x, y = T @ f1, T @ f2
                A = np.c_[2 * x, 2 * y, np.ones(len(x))]
                sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
                r0 = np.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 1e-9))
                p0 = P.mean(0) + sol[0] * f1 + sol[1] * f2
                if 4.0 < r0 < 3000:
                    cc, ca, cr, _ = ajuste.cilindro(P, eixo0, p0, r0, escala=0.15)
                    for _ in range(3):                      # reajusta só com quem está perto (vizinhos de outro diâmetro saem)
                        dd = np.abs(Cilindro(cc, ca, cr).dist(P))
                        s_ = dd < max(3 * tol, 2.5 * _sigma(dd[dd < 3.0]) + 0.05)
                        if s_.sum() < 40 or s_.all():
                            break
                        cc, ca, cr, _ = ajuste.cilindro(P[s_], ca, cc, cr, escala=0.1)
                    if 4.0 < cr < 3000:
                        cil = Cilindro(cc, ca, cr)
                        cil.s = lado(cil)
                        d = cil.dist(P)
                        sc = _sigma(d[np.abs(d) < 3 * tol]) if (np.abs(d) < 3 * tol).sum() > 10 else 9.0
                        cands.append((cil, sc, _dentro(d, tol), 2))
                        kc, ka, kr0, kk, _ = ajuste.cone(P, ca, cc)
                        if abs(kk) > 0.02 and kr0 > 3.0:
                            # r0 referido à altura do alvo
                            zc = (c - kc) @ ka
                            cone = Cone(kc + zc * ka, ka, kr0 + kk * zc, kk)
                            cone.s = lado(cone)
                            d = cone.dist(P)
                            cands.append((cone, _sigma(d[np.abs(d) < 3 * tol]) if (np.abs(d) < 3 * tol).sum() > 10 else 9.0, _dentro(d, tol), 3))
            except Exception:
                pass

    # ---- escolha: quem explica mais pontos; empate técnico vai para o mais simples
    melhor = max(c_[2] for c_ in cands)
    cands.sort(key=lambda c_: c_[3])
    for mod, sig, frac, _ in cands:
        if frac >= melhor - 0.04:
            if registro is not None:
                registro.append([(m.nome, round(s, 3), round(f, 3)) for m, s, f, _ in cands])
            return mod, sig, frac
    return cands[0][:3]


def altura_sobre(modelo, P0, n, voltas=12):
    """Para cada ponto P0, o deslocamento t ao longo de n que o leva à superfície: modelo.dist(P0 + t·n) = 0."""
    P0 = np.asarray(P0, float)
    t0 = np.zeros(len(P0))
    d0 = modelo.dist(P0)
    t1 = -d0
    d1 = modelo.dist(P0 + t1[:, None] * n)
    for _ in range(voltas):
        den = d1 - d0
        den = np.where(np.abs(den) < 1e-12, 1e-12, den)
        t2 = t1 - d1 * (t1 - t0) / den
        t2 = np.where(np.abs(d1) < 1e-7, t1, t2)
        t0, d0, t1 = t1, d1, t2
        d1 = modelo.dist(P0 + t1[:, None] * n)
        if np.max(np.abs(d1)) < 1e-6:
            break
    return t1
