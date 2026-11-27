"""Tests voor de herkenning van vlakken en gaten (alleen numpy nodig, geen FreeCAD).

Uitvoeren:  python3 tests/test_herkenning.py   of   pytest tests
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import convert as h  # noqa: E402


def plaat(N=32, r=5.0, half=20.0, dikte=10.0, blind_diepte=None, cx=3.0, cy=-2.0):
    """Gesloten mesh van een vierkante plaat met een rond gat (doorlopend of blind)."""
    ang = np.arange(N) * 2 * np.pi / N
    ci = np.stack([cx + r * np.cos(ang), cy + r * np.sin(ang)], 1)
    s = half / np.maximum(np.abs(np.cos(ang)), np.abs(np.sin(ang)))
    sq = np.stack([s * np.cos(ang), s * np.sin(ang)], 1)
    P, T = [], []

    def add(xy, z):
        i = len(P)
        P.extend([[x, y, z] for x, y in xy])
        return i

    zt, zb = dikte, 0.0
    zbot = zb if blind_diepte is None else zt - blind_diepte
    ct, st = add(ci, zt), add(sq, zt)
    cb2, sb = add(ci, zbot), add(sq, zb)
    for k in range(N):
        j = (k + 1) % N
        T += [[ct + k, st + k, st + j], [ct + k, st + j, ct + j]]        # bovenkant
        T += [[sb + k, sb + j, st + j], [sb + k, st + j, st + k]]        # buitenwand
        T += [[ct + k, ct + j, cb2 + j], [ct + k, cb2 + j, cb2 + k]]     # gatwand
    if blind_diepte is None:
        for k in range(N):
            j = (k + 1) % N
            T += [[cb2 + k, sb + j, sb + k], [cb2 + k, cb2 + j, sb + j]]  # onderkant
    else:
        m = len(P)
        P.append([cx, cy, zbot])
        T += [[m, cb2 + k, cb2 + (k + 1) % N] for k in range(N)]          # bodem van het gat
        m2 = len(P)
        P.append([0, 0, zb])
        T += [[m2, sb + (k + 1) % N, sb + k] for k in range(N)]           # onderkant
    return np.array(P, float), np.array(T)


def controleer_gat(g, d, diepte, blind):
    assert abs(2 * g["r"] - d) < 1e-6
    assert abs((g["z1"] - g["z0"]) - diepte) < 1e-6
    assert (g["dicht0"] or g["dicht1"]) == blind
    assert np.allclose(g["centrum"][:2], [3.0, -2.0]) and np.allclose(np.abs(g["as_"]), [0, 0, 1])


def test_doorlopend_gat():
    gaten, overgeslagen, vlakken = h.herken(*plaat())
    assert vlakken == 6 and not overgeslagen and len(gaten) == 1
    controleer_gat(gaten[0], 10.0, 10.0, blind=False)


def test_blind_gat():
    gaten, overgeslagen, vlakken = h.herken(*plaat(blind_diepte=6.0))
    assert vlakken == 7 and not overgeslagen and len(gaten) == 1
    controleer_gat(gaten[0], 10.0, 6.0, blind=True)


def test_fijne_mesh():
    gaten, _, vlakken = h.herken(*plaat(N=200))
    assert vlakken == 6 and len(gaten) == 1
    controleer_gat(gaten[0], 10.0, 10.0, blind=False)


def test_omgekeerde_normalen():
    P, T = plaat()
    gaten, _, _ = h.herken(P, T[:, ::-1])
    assert len(gaten) == 1
    controleer_gat(gaten[0], 10.0, 10.0, blind=False)


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_"):
            f()
            print("ok ", naam)
