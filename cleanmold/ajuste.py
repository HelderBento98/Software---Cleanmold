"""Ajustes geométricos por mínimos quadrados: plano, esfera, cilindro, cone, e rotações."""
import numpy as np
from scipy.optimize import least_squares


def base_ortonormal(a):
    """Dois vetores unitários perpendiculares a `a` (e entre si), formando base destra (e1, e2, a)."""
    a = np.asarray(a, float)
    a = a / np.linalg.norm(a)
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(t, a)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    return e1, e2, a


def rotacao_entre(a, b):
    """Matriz que leva o vetor unitário a no vetor unitário b pelo caminho mais curto."""
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c < -1 + 1e-12:
        e1, _, _ = base_ortonormal(a)
        return 2 * np.outer(e1, e1) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)


def rotacao_eixo(a, ang):
    a = np.asarray(a, float) / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def plano(P, pesos=None):
    """Plano de mínimos quadrados: (ponto, normal unitária, rms)."""
    P = np.asarray(P, float)
    w = np.ones(len(P)) if pesos is None else np.asarray(pesos, float)
    c = (P * w[:, None]).sum(0) / w.sum()
    Q = (P - c) * np.sqrt(w)[:, None]
    _, s, vt = np.linalg.svd(Q, full_matrices=False)
    n = vt[2]
    d = (P - c) @ n
    return c, n, float(np.sqrt(np.average(d * d, weights=w)))


def plano_robusto(P, voltas=6, k=2.5):
    """Plano que ignora pontos fora do padrão (repondera pelo resíduo). Devolve (ponto, normal, sigma, dentro)."""
    P = np.asarray(P, float)
    w = np.ones(len(P))
    c, n, _ = plano(P)
    s = 1.0
    for _ in range(voltas):
        d = (P - c) @ n
        s = 1.4826 * np.median(np.abs(d - np.median(d))) + 1e-6
        w = 1.0 / (1.0 + (d / (k * s)) ** 2) ** 2
        c, n, _ = plano(P, w)
    d = (P - c) @ n
    return c, n, float(s), np.abs(d) < 3 * k * s


def esfera(P):
    """Esfera de mínimos quadrados (algébrica + refino geométrico): (centro, raio, rms)."""
    P = np.asarray(P, float)
    m = P.mean(0)
    Q = P - m
    A = np.c_[2 * Q, np.ones(len(Q))]
    b = (Q * Q).sum(1)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = x[:3]
    r = np.sqrt(max(x[3] + c @ c, 1e-12))

    def res(u):
        return np.linalg.norm(Q - u[:3], axis=1) - u[3]
    try:
        s = least_squares(res, np.r_[c, r], loss="soft_l1", f_scale=max(0.05, 0.02 * r), max_nfev=60)
        c, r = s.x[:3], abs(s.x[3])
    except Exception:
        pass
    d = np.linalg.norm(Q - c, axis=1) - r
    return c + m, float(r), float(np.sqrt(np.mean(d * d)))


def _eixo_de(u, e1, e2, a0):
    a = a0 + u[0] * e1 + u[1] * e2
    return a / np.linalg.norm(a)


def cilindro(P, eixo0, ponto0, raio0, raio_fixo=False, escala=0.2):
    """Cilindro de mínimos quadrados partindo de um chute. Devolve (ponto do eixo, eixo, raio, rms).
    O ponto devolvido é o do eixo mais próximo do centro dos dados."""
    P = np.asarray(P, float)
    e1, e2, a0 = base_ortonormal(eixo0)
    m = P.mean(0)
    p0 = np.asarray(ponto0, float)
    p0 = p0 + ((m - p0) @ a0) * a0

    def res(u):
        a = _eixo_de(u[:2], e1, e2, a0)
        c = p0 + u[2] * e1 + u[3] * e2
        Q = P - c
        rho = np.linalg.norm(Q - np.outer(Q @ a, a), axis=1)
        return rho - (raio0 if raio_fixo else u[4])
    u0 = np.zeros(4 if raio_fixo else 5)
    if not raio_fixo:
        u0[4] = raio0
    s = least_squares(res, u0, loss="soft_l1", f_scale=escala, max_nfev=80)
    a = _eixo_de(s.x[:2], e1, e2, a0)
    c = p0 + s.x[2] * e1 + s.x[3] * e2
    c = c + ((m - c) @ a) * a
    r = raio0 if raio_fixo else abs(s.x[4])
    d = res(s.x)
    return c, a, float(r), float(np.sqrt(np.mean(d * d)))


def cone(P, eixo0, ponto0):
    """Cone de mínimos quadrados: raio(z) = r0 + k·z ao longo do eixo. Devolve (ponto, eixo, r0, k, rms)."""
    P = np.asarray(P, float)
    e1, e2, a0 = base_ortonormal(eixo0)
    m = P.mean(0)
    p0 = np.asarray(ponto0, float)
    p0 = p0 + ((m - p0) @ a0) * a0
    Q0 = P - p0
    rho0 = np.linalg.norm(Q0 - np.outer(Q0 @ a0, a0), axis=1)

    def res(u):
        a = _eixo_de(u[:2], e1, e2, a0)
        c = p0 + u[2] * e1 + u[3] * e2
        Q = P - c
        z = Q @ a
        rho = np.linalg.norm(Q - np.outer(z, a), axis=1)
        return (rho - (u[4] + u[5] * z)) / np.sqrt(1 + u[5] * u[5])
    s = least_squares(res, np.r_[0, 0, 0, 0, np.median(rho0), 0.0], loss="soft_l1", f_scale=0.2, max_nfev=120)
    a = _eixo_de(s.x[:2], e1, e2, a0)
    c = p0 + s.x[2] * e1 + s.x[3] * e2
    d = res(s.x)
    return c, a, float(s.x[4]), float(s.x[5]), float(np.sqrt(np.mean(d * d)))


def rigido(A, B, pesos=None, escala=False):
    """Transformação (s, R, t) que leva os pontos A aos pontos B (pares na mesma ordem): B ≈ s·R·A + t."""
    A = np.asarray(A, float)
    B = np.asarray(B, float)
    w = np.ones(len(A)) if pesos is None else np.asarray(pesos, float)
    w = w / w.sum()
    ca, cb = (A * w[:, None]).sum(0), (B * w[:, None]).sum(0)
    Xa, Xb = A - ca, B - cb
    H = (Xa * w[:, None]).T @ Xb
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1, 1, d])
    R = Vt.T @ D @ U.T
    s = 1.0
    if escala:
        var = (w * (Xa * Xa).sum(1)).sum()
        s = float((S * np.diag(D)).sum() / max(var, 1e-30))
    t = cb - s * R @ ca
    return s, R, t
