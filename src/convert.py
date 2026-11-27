# -*- coding: utf-8 -*-
"""
STL -> STEP met herkenning van vlakken en ronde gaten  (prototype)
-----------------------------------------------------------------
Headless versie voor de stl2step-dienst (draait onder freecadcmd).
Invoer/uitvoer via omgevingsvariabelen STL2STEP_IN, STL2STEP_OUT, STL2STEP_REPORT.
Het script
  1. maakt van de mesh een solid en voegt vlakke driehoekjes samen tot echte vlakken,
  2. zoekt ronde gaten (doorlopend of blind) en past er een echte cilinder op,
  3. snijdt die cilinder weg, zodat de gatwand een echt cilindervlak wordt,
  4. slaat het resultaat op als STEP.

Aannames: eenheden in mm, gesloten (waterdichte) mesh, gaten zijn rechte
volledige cilinders. Afrondingen, kegels, sleuven en uitstekende pennen
worden (nog) niet omgezet en blijven facetten.
"""
import math
import numpy as np

# ---------------- instellingen ----------------
HOEK_VLAK = 1.0      # graden: driehoeken binnen deze hoek van het startvlak horen bij hetzelfde vlak
HOEK_SCHERP = 30.0   # graden: knik groter dan dit = echte rand (geen gebogen oppervlak)
MAX_FOUT = 0.02      # max. afwijking van de cirkelfit, als fractie van de straal
MIN_DEKKING = 300.0  # graden: zo veel van de omtrek moet aanwezig zijn om als volledig gat te tellen
HOEK_AS = 2.0        # graden: vouwlijn binnen deze hoek van de cilinderas hoort bij dezelfde cilinder
SNAP_HOEK = 0.5      # graden: as binnen deze hoek van X/Y/Z wordt exact uitgelijnd
NAAD_TOL = 0.01      # mm: tolerantie bij het naaien van de mesh tot een solid


# ================= herkenning (alleen numpy) =================

def ontdubbel(P, T, tol=1e-6):
    """Samenvallende punten samenvoegen zodat buren gevonden kunnen worden."""
    sleutel = np.round(P / tol).astype(np.int64)
    _, idx, inv = np.unique(sleutel, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    T2 = inv[T]
    goed = (T2[:, 0] != T2[:, 1]) & (T2[:, 1] != T2[:, 2]) & (T2[:, 0] != T2[:, 2])
    return P[idx], T2[goed]


def normalen(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    kr = np.cross(b - a, c - a)
    lengte = np.linalg.norm(kr, axis=1)
    n = kr / np.maximum(lengte, 1e-30)[:, None]
    return n, 0.5 * lengte, (a + b + c) / 3.0


def buurparen(T, nv):
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    f = np.tile(np.arange(len(T)), 3)
    e.sort(axis=1)
    k = e[:, 0].astype(np.int64) * nv + e[:, 1]
    o = np.argsort(k, kind="stable")
    k, f = k[o], f[o]
    gelijk = np.nonzero(k[1:] == k[:-1])[0]
    paren = np.stack([f[gelijk], f[gelijk + 1]], axis=1)
    randen = np.stack([k[gelijk] // nv, k[gelijk] % nv], axis=1)  # gedeelde rand (2 punten)
    return paren, randen

def csr(paren, n):
    a = np.concatenate([paren[:, 0], paren[:, 1]])
    b = np.concatenate([paren[:, 1], paren[:, 0]])
    o = np.argsort(a, kind="stable")
    a, b = a[o], b[o]
    start = np.searchsorted(a, np.arange(n + 1))
    return start, b


def vlakgebieden(n, opp, start, buur):
    """Groei vlakke gebieden vanaf het grootste driehoekje; vergelijk met de startnormaal (geen drift)."""
    cos_t = math.cos(math.radians(HOEK_VLAK))
    label = -np.ones(len(n), dtype=np.int64)
    g = 0
    for s in np.argsort(-opp):
        if label[s] >= 0:
            continue
        ns = n[s]
        label[s] = g
        stapel = [s]
        while stapel:
            t = stapel.pop()
            for u in buur[start[t]:start[t + 1]]:
                if label[u] < 0 and n[u] @ ns > cos_t:
                    label[u] = g
                    stapel.append(u)
        g += 1
    return label, g


def zoek(ouder, i):
    while ouder[i] != i:
        ouder[i] = ouder[ouder[i]]
        i = ouder[i]
    return i

def gladde_patches(label, ng, n, opp, paren, randlengte):
    """Voeg aangrenzende vlakgebieden samen tot een cilinder.

    Twee gebieden horen bij dezelfde cilinder als de knik klein is én de vouwlijn
    (kruisproduct van de normalen) evenwijdig loopt aan de as van die cilinder.
    Lange vouwlijnen gaan eerst, zodat een gatwand niet via een afronding aan een
    groot vlak vastgroeit.
    """
    gn = np.zeros((ng, 3))
    np.add.at(gn, label, n * opp[:, None])
    gn /= np.maximum(np.linalg.norm(gn, axis=1), 1e-30)[:, None]
    cos_s = math.cos(math.radians(HOEK_SCHERP))
    la, lb = label[paren[:, 0]], label[paren[:, 1]]
    m = la != lb
    gp, inv = np.unique(np.sort(np.stack([la[m], lb[m]], 1), axis=1), axis=0, return_inverse=True)
    rand = np.zeros(len(gp))                                   # totale vouwlengte per paar
    np.add.at(rand, inv.reshape(-1), randlengte[m])
    cos_as = math.cos(math.radians(HOEK_AS))
    ouder = np.arange(ng)
    as_ = np.zeros((ng, 3))                                    # as per groep, 0 = nog geen
    for i in np.argsort(-rand):                                # langste vouw eerst
        a, b = gp[i]
        if gn[a] @ gn[b] <= cos_s:
            continue                                           # scherpe rand
        vouw = np.cross(gn[a], gn[b])                          # richting van de vouwlijn
        vouw /= np.linalg.norm(vouw)                           # lengte 1
        ra, rb = zoek(ouder, a), zoek(ouder, b)
        if ra == rb:
            continue
        # alleen samenvoegen als de vouw langs de as van beide groepen loopt
        if all(not as_[r].any() or abs(as_[r] @ vouw) > cos_as for r in (ra, rb)):
            ouder[rb] = ra
            as_[ra] = vouw                                     # groep onthoudt zijn as
    wortel = np.array([zoek(ouder, i) for i in range(ng)])
    patch = wortel[label]
    aantal_gebieden = np.bincount(wortel, minlength=ng)
    return patch, aantal_gebieden


def snap_as(a):
    for i in range(3):
        if abs(a[i]) > math.cos(math.radians(SNAP_HOEK)):
            e = np.zeros(3)
            e[i] = math.copysign(1.0, a[i])
            return e
    return a / np.linalg.norm(a)


def pas_cilinder(P, T, n, opp, c, tris):
    """Cilinderfit op een patch. Geeft dict of (None, reden)."""
    N, A = n[tris], opp[tris]
    M = (N * A[:, None]).T @ N
    w, v = np.linalg.eigh(M)
    if w[0] / max(w.sum(), 1e-30) > 0.01:
        return None, "normalen niet loodrecht op één as (geen cilinder)"
    as_ = snap_as(v[:, 0])
    u = np.cross(as_, [1, 0, 0] if abs(as_[0]) < 0.9 else [0, 1, 0])
    u /= np.linalg.norm(u)
    vv = np.cross(as_, u)
    pts = P[np.unique(T[tris])]
    x, y, z = pts @ u, pts @ vv, pts @ as_
    Am = np.stack([x, y, np.ones_like(x)], 1)
    sol, *_ = np.linalg.lstsq(Am, x * x + y * y, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    r = math.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0))
    if r <= 0:
        return None, "cirkelfit mislukt"
    d = np.hypot(x - cx, y - cy)
    fout = np.abs(d - r).max()
    if fout > MAX_FOUT * r:
        return None, "punten liggen niet op een cirkel (afw. %.3f mm)" % fout
    hoek = np.sort(np.degrees(np.arctan2(y - cy, x - cx)))
    gaten = np.diff(np.concatenate([hoek, [hoek[0] + 360]]))
    dekking = 360 - gaten.max()
    # gat of pen? Bij een gat wijzen de normalen naar de as toe.
    cc = c[tris]
    radiaal = (cc @ u - cx)[:, None] * u + (cc @ vv - cy)[:, None] * vv
    is_gat = float(np.sum(np.einsum("ij,ij->i", N, radiaal) * A)) < 0
    centrum = cx * u + cy * vv
    return dict(as_=as_, centrum=centrum, r=r, z0=z.min(), z1=z.max(),
                dekking=dekking, is_gat=is_gat, fout=fout), None


def einde_dicht(n, opp, c, cil, z_eind):
    """Heeft het gat aan deze kant een bodem? Zoek vlakke driehoekjes binnen de cirkel op die hoogte."""
    as_, r = cil["as_"], cil["r"]
    tol = 0.01 * r + 1e-3
    zc = c @ as_
    rel = c - np.outer(zc, as_) - cil["centrum"]
    rad = np.linalg.norm(rel - np.outer(rel @ as_, as_), axis=1)
    m = (np.abs(n @ as_) > 0.99) & (np.abs(zc - z_eind) < tol) & (rad < 0.9 * r)
    return bool(m.any())


def herken(P, T):
    """Hoofdroutine. Geeft (gaten, overgeslagen, aantal_vlakken)."""
    P, T = ontdubbel(np.asarray(P, float), np.asarray(T, np.int64))
    n, opp, c = normalen(P, T)
    # oriëntatie controleren: volume moet positief zijn (normalen naar buiten)
    vol = np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])).sum() / 6
    if vol < 0:
        T = T[:, ::-1]
        n = -n
    paren, randen = buurparen(T,len(P))
    start, buur = csr(paren, len(T))
    label, ng = vlakgebieden(n, opp, start, buur)
    randlengte = np.linalg.norm(P[randen[:, 0]] - P[randen[:, 1]], axis=1)
    patch, aantal = gladde_patches(label, ng, n, opp, paren, randlengte)

    gaten, overgeslagen = [], []
    vlakken = 0
    for p in np.unique(patch):
        if aantal[p] <= 1:
            vlakken += 1
            continue
        tris = np.nonzero(patch == p)[0]
        cil, reden = pas_cilinder(P, T, n, opp, c, tris)
        if cil is None:
            overgeslagen.append((len(tris), reden))
            continue
        if not cil["is_gat"]:
            overgeslagen.append((len(tris), "uitstekende cilinder Ø%.2f (nog niet ondersteund)" % (2 * cil["r"])))
            continue
        if cil["dekking"] < MIN_DEKKING:
            overgeslagen.append((len(tris), "gedeeltelijke boog Ø%.2f, %.0f° (nog niet ondersteund)"
                                 % (2 * cil["r"], cil["dekking"])))
            continue
        cil["dicht0"] = einde_dicht(n, opp, c, cil, cil["z0"])
        cil["dicht1"] = einde_dicht(n, opp, c, cil, cil["z1"])
        gaten.append(cil)
    return gaten, overgeslagen, vlakken


def omschrijf(g):
    soort = "blind" if (g["dicht0"] or g["dicht1"]) else "doorlopend"
    return "Ø%.3f mm, diepte %.2f mm, %s" % (2 * g["r"], g["z1"] - g["z0"], soort)


# ================= FreeCAD-deel =================

def mesh_naar_solid(mesh):
    import Part
    vorm = Part.Shape()
    vorm.makeShapeFromMesh(mesh.Topology, NAAD_TOL)
    try:
        solid = Part.Solid(Part.Shell(vorm.Faces))
    except Exception:
        solid = Part.makeSolid(vorm)
    if solid.Volume < 0:
        solid.reverse()
    return solid.removeSplitter()


def snij_gaten(solid, gaten, meldingen):
    import FreeCAD as App
    import Part
    for g in gaten:
        r = g["r"] + max(0.002, 3 * g["fout"])      # net ruim, zodat alle facetten verdwijnen
        ext = 0.1 * g["r"] + 0.1                      # open kant iets doorsteken
        z0 = g["z0"] - (0 if g["dicht0"] else ext)
        z1 = g["z1"] + (0 if g["dicht1"] else ext)
        as_ = App.Vector(*g["as_"])
        basis = App.Vector(*(g["centrum"] + z0 * g["as_"]))
        cil = Part.makeCylinder(r, z1 - z0, basis, as_)
        try:
            nieuw = solid.cut(cil)
            if nieuw.isValid() and len(nieuw.Solids) >= 1:
                solid = nieuw
                meldingen.append("✓ " + omschrijf(g))
            else:
                meldingen.append("✗ " + omschrijf(g) + "  (snijden gaf ongeldige vorm)")
        except Exception as e:
            meldingen.append("✗ " + omschrijf(g) + "  (fout: %s)" % e)
    return solid.removeSplitter()


def schrijf_preview(solid, pad):
    """Licht 3D-model voor de webpagina: driehoekjes + de randen van de echte vlakken.
    Formaat: b"S2P1", uint32 aantal driehoeken, uint32 aantal lijnstukken, daarna float32-coordinaten."""
    import struct
    tol = max(solid.BoundBox.DiagonalLength * 0.002, 0.01)
    punten, tris = solid.tessellate(tol)
    V = np.array([[v.x, v.y, v.z] for v in punten], dtype=np.float32).reshape(-1, 3)
    T = np.array(tris, dtype=np.int64).reshape(-1, 3)
    soep = V[T].reshape(-1)
    stukken = []
    randen = solid.Edges
    if len(randen) <= 20000:              # bij een niet-herkende mesh zijn het er te veel
        for e in randen:
            try:
                a = np.array([[p.x, p.y, p.z] for p in e.discretize(Deflection=tol)], dtype=np.float32)
            except Exception:
                continue
            if len(a) >= 2:
                stukken.append(np.stack([a[:-1], a[1:]], 1).reshape(-1))
    lijnen = np.concatenate(stukken) if stukken else np.zeros(0, dtype=np.float32)
    with open(pad, "wb") as f:
        f.write(b"S2P1" + struct.pack("<II", len(soep) // 9, len(lijnen) // 6))
        f.write(soep.astype("<f4").tobytes())
        f.write(lijnen.astype("<f4").tobytes())


def main():
    import os
    import sys
    import traceback
    bron = os.environ["STL2STEP_IN"]
    doel = os.environ["STL2STEP_OUT"]
    rapport = os.environ.get("STL2STEP_REPORT")
    regels = []
    code = 0
    try:
        import Mesh
        mesh = Mesh.Mesh(bron)
        if mesh.CountFacets == 0:
            raise ValueError("lege of onleesbare STL")
        regels.append("%d driehoekjes" % mesh.CountFacets)
        try:
            P = np.array([[p.x, p.y, p.z] for p in mesh.Topology[0]])
            T = np.array(mesh.Topology[1], dtype=np.int64)
            gaten, overgeslagen, vlakken = herken(P, T)
        except Exception as e:
            gaten, overgeslagen, vlakken = [], [], 0
            regels.append("herkenning mislukt (%s); alleen vlakken samengevoegd" % e)
        solid = mesh_naar_solid(mesh)
        meldingen = []
        if gaten:
            try:
                solid = snij_gaten(solid, gaten, meldingen)
            except Exception as e:
                regels.append("gaten snijden mislukt (%s); gaten blijven facetten" % e)
        if not solid.isValid():
            raise ValueError(f"geen massief deel: STL is niet waterdicht, repareer de mesh {bron}")
        solid.exportStep(doel)
        if os.environ.get("STL2STEP_PREVIEW"):
            try:
                schrijf_preview(solid, os.environ["STL2STEP_PREVIEW"])
            except Exception as e:
                regels.append("preview maken mislukt (%s)" % e)
        regels.append("vlakke gebieden: %d, gaten herkend: %d" % (vlakken, len(gaten)))
        regels += meldingen
        regels += ["niet omgezet: %s (%d driehoekjes)" % (reden, k) for k, reden in overgeslagen]
    except Exception:
        code = 1
        regels.append(traceback.format_exc())
    if rapport:
        with open(rapport, "w", encoding="utf-8") as f:
            f.write("\n".join(regels) + "\n")
    sys.stdout.flush()
    os._exit(code)   # freecadcmd anders mogelijk in interactieve modus


try:
    import FreeCAD  # noqa: F401
    _in_freecad = True
except ImportError:
    _in_freecad = False   # buiten FreeCAD (testen): alleen functies laden
if _in_freecad:
    import os as _os
    if _os.environ.get("STL2STEP_IN"):
        main()
