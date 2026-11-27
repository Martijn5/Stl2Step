#!/usr/bin/env python3
"""stl2step-watcher: houdt de STL-map in de gaten en zet nieuwe/gewijzigde STL's om naar STEP."""
import datetime
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

STL = Path(os.environ.get("STL_DIR", "/srv/cad/stl"))
STEP = Path(os.environ.get("STEP_DIR", "/srv/cad/step"))
FREECAD = os.environ.get("FREECADCMD", "freecadcmd")
CONVERT = Path(os.environ.get("CONVERT_SCRIPT", Path(__file__).with_name("convert.py")))
STATE = Path(os.environ.get("STATE_FILE", Path.home() / "stl2step_state.json"))
INTERVAL = float(os.environ.get("INTERVAL", "5"))      # seconden tussen controles
TIMEOUT = float(os.environ.get("TIMEOUT", "3600"))     # max. seconden per conversie
LOG = STEP / "conversie.log"
PREVIEW = Path(os.environ.get("PREVIEW_DIR", Path.home() / "preview"))   # 3D-previews voor de webpagina
BEZIG = STATE.with_name("stl2step_bezig.txt")           # naam van het bestand dat nu wordt omgezet (voor de webpagina)


def log(msg):
    regel = "%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(regel, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(regel + "\n")
    except OSError:
        pass


def laad_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def bewaar_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, STATE)


def converteer(stl):
    doel = STEP / (stl.stem + ".step")
    fout = STEP / (stl.stem + "_FOUT.txt")
    tmp = STEP / ("." + stl.stem + ".step.tmp")
    pv = PREVIEW / (stl.stem + ".s2p")
    pvtmp = PREVIEW / ("." + stl.stem + ".tmp")
    fd, rapport = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    env = dict(os.environ, STL2STEP_IN=str(stl), STL2STEP_OUT=str(tmp), STL2STEP_REPORT=rapport,
               STL2STEP_PREVIEW=str(pvtmp))
    log("start: %s" % stl.name)
    t0 = time.time()
    uitvoer = ""
    try:
        BEZIG.write_text(stl.name, encoding="utf-8")
        p = subprocess.run([FREECAD, str(CONVERT)], env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT, text=True)
        ok = p.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0
        uitvoer = p.stdout or ""
    except subprocess.TimeoutExpired:
        ok = False
        uitvoer = "afgebroken: duurde langer dan %d s" % TIMEOUT
    except OSError as e:
        ok = False
        uitvoer = "kan FreeCAD niet starten: %s" % e
    BEZIG.unlink(missing_ok=True)
    try:
        details = Path(rapport).read_text(encoding="utf-8").strip()
    except OSError:
        details = ""
    finally:
        try:
            os.unlink(rapport)
        except OSError:
            pass
    if ok:
        os.replace(tmp, doel)
        if pvtmp.exists() and pvtmp.stat().st_size > 12:
            os.replace(pvtmp, pv)
        else:
            pv.unlink(missing_ok=True)
        pvtmp.unlink(missing_ok=True)
        fout.unlink(missing_ok=True)
        log("klaar: %s -> %s (%.0f s)" % (stl.name, doel.name, time.time() - t0))
        for r in details.splitlines():
            log("    " + r)
    else:
        tmp.unlink(missing_ok=True)
        pvtmp.unlink(missing_ok=True)
        pv.unlink(missing_ok=True)
        fout.write_text("Conversie van %s mislukt.\n\n%s\n\n%s\n" % (stl.name, details, uitvoer[-4000:]),
                        encoding="utf-8")
        log("MISLUKT: %s (zie %s)" % (stl.name, fout.name))
    return ok


def main():
    STL.mkdir(parents=True, exist_ok=True)
    STEP.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    BEZIG.unlink(missing_ok=True)
    state = laad_state()
    vorige = {}
    log("watcher gestart; map: %s" % STL)
    while True:
        nu = {}
        try:
            bestanden = sorted(f for f in STL.iterdir() if f.is_file() and f.suffix.lower() == ".stl"
                               and not f.name.startswith("."))
        except OSError:
            bestanden = []
        for f in bestanden:
            try:
                st = f.stat()
            except OSError:
                continue
            sig = [st.st_size, st.st_mtime_ns]
            nu[f.name] = sig
            doel = STEP / (f.stem + ".step")
            gedaan = state.get(f.name)
            if gedaan and gedaan["sig"] == sig and (doel.exists() or not gedaan["ok"]):
                continue                      # al verwerkt (of al eens mislukt) in deze versie
            if vorige.get(f.name) != sig or st.st_size == 0:
                continue                      # nog aan het kopiëren: wacht tot grootte/tijd stabiel is
            ok = converteer(f)
            state[f.name] = {"sig": sig, "ok": ok}
            bewaar_state(state)
        # opruimen: verwijderde STL's uit de administratie halen
        weg = [n for n in state if n not in nu]
        if weg:
            for n in weg:
                del state[n]
            bewaar_state(state)
        vorige = nu
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
