#!/usr/bin/env python3
"""stl2step-web: eenvoudige webpagina om STL's te uploaden, de voortgang te zien en STEP's te downloaden."""
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STL = Path(os.environ.get("STL_DIR", "/srv/cad/stl"))
STEP = Path(os.environ.get("STEP_DIR", "/srv/cad/step"))
STATE = Path(os.environ.get("STATE_FILE", Path.home() / "stl2step_state.json"))
BEZIG = STATE.with_name("stl2step_bezig.txt")
LOG = STEP / "conversie.log"
PREVIEW = Path(os.environ.get("PREVIEW_DIR", Path.home() / "preview"))
POORT = int(os.environ.get("PORT", "8080"))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "1024")) * 1024 * 1024

PAGINA = r"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>STL → STEP</title>
<style>
:root{--bg:#f4f5f7;--kaart:#fff;--tekst:#1c2430;--zacht:#667085;--lijn:#dde1e7;--accent:#0b6bcb;
--ok:#17803d;--okbg:#e3f5e9;--fout:#b42318;--foutbg:#fde8e6;--bezig:#9a5b00;--bezigbg:#fdf0d5;--wachtbg:#eceef2}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--kaart:#1b212a;--tekst:#e6e9ee;--zacht:#98a2b3;--lijn:#2c3440;
--accent:#5aa9f5;--ok:#6fd08c;--okbg:#173322;--fout:#ff8a7d;--foutbg:#3a1a17;--bezig:#f3c063;--bezigbg:#3a2c0f;--wachtbg:#262d38}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tekst);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--zacht);margin:0 0 20px}
.kaart{background:var(--kaart);border:1px solid var(--lijn);border-radius:10px;margin-bottom:16px}
#drop{border:2px dashed var(--lijn);border-radius:10px;padding:28px 16px;text-align:center;cursor:pointer;background:var(--kaart);margin-bottom:16px}
#drop.over{border-color:var(--accent);background:var(--wachtbg)}
#drop strong{color:var(--accent)}
#upl{color:var(--zacht);font-size:13px;min-height:1.5em;margin-top:6px}
table{width:100%;border-collapse:collapse}
th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--lijn);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--zacht);font-weight:600}
tr:last-child td{border-bottom:0}
td.naam{word-break:break-all}
td.r,th.r{text-align:right;white-space:nowrap}
.leeg{padding:22px;text-align:center;color:var(--zacht)}
.st{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12.5px;font-weight:600;white-space:nowrap}
.st.klaar{color:var(--ok);background:var(--okbg)}.st.mislukt{color:var(--fout);background:var(--foutbg)}
.st.bezig{color:var(--bezig);background:var(--bezigbg)}.st.wachten{color:var(--zacht);background:var(--wachtbg)}
a.knop,button{font:inherit;font-size:13px;border:1px solid var(--lijn);background:transparent;color:var(--tekst);
border-radius:6px;padding:4px 10px;cursor:pointer;text-decoration:none;display:inline-block;margin-left:4px}
a.knop{border-color:var(--accent);color:var(--accent)}
button:hover,a.knop:hover{background:var(--wachtbg)}
details{margin-top:6px;font-size:13px;color:var(--zacht)}
pre{margin:6px 0 0;white-space:pre-wrap;word-break:break-word;font:12.5px/1.45 ui-monospace,Consolas,monospace}
td.thumb{width:88px;padding-right:0}
.th{width:72px;height:54px;border-radius:6px;background:var(--wachtbg);display:block;border:1px solid var(--lijn)}
img.th{cursor:zoom-in}
#modal{position:fixed;inset:0;background:rgba(10,14,20,.6);display:none;align-items:center;justify-content:center;padding:16px;z-index:10}
#modal.open{display:flex}
#mbox{background:var(--kaart);border:1px solid var(--lijn);border-radius:12px;width:min(900px,100%);overflow:hidden}
#mkop{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--lijn)}
#mnaam{font-weight:600;flex:1;word-break:break-all}
#mcanvas{display:block;width:100%;height:min(62vh,560px);background:var(--wachtbg);touch-action:none;cursor:grab}
#mvoet{padding:8px 14px;color:var(--zacht);font-size:13px}
h2{font-size:14px;margin:0;padding:12px 14px;border-bottom:1px solid var(--lijn)}
#log{padding:12px 14px;max-height:260px;overflow:auto;color:var(--zacht)}
@media (max-width:600px){thead,td.g{display:none}td.thumb{float:right;width:auto}tr{display:block;padding:10px 14px;border-bottom:1px solid var(--lijn)}tr:last-child{border-bottom:0}td{display:block;padding:2px 0;border:0}td.r{text-align:left;white-space:normal;margin-top:6px}a.knop,button{margin:0 6px 4px 0}}
</style></head><body><main>
<h1>STL → STEP</h1>
<p class="sub">Zet een STL neer; de server maakt er een STEP van met echte vlakken en ronde gaten.</p>
<div id="drop"><div><strong>Kies STL-bestanden</strong> of sleep ze hierheen</div><div id="upl"></div>
<input id="kies" type="file" accept=".stl" multiple hidden></div>
<div class="kaart"><table><thead><tr><th></th><th>Bestand</th><th class="g r">Grootte</th><th>Status</th><th class="r"></th></tr></thead>
<tbody id="rijen"></tbody></table><div id="leeg" class="leeg">Nog geen bestanden.</div></div>
<div class="kaart"><h2>Logboek</h2><pre id="log"></pre></div>
</main>
<div id="modal"><div id="mbox"><div id="mkop"><span id="mnaam"></span><a id="mdl" class="knop">Download STEP</a><button id="msluit">Sluiten</button></div>
<canvas id="mcanvas"></canvas><div id="mvoet">Slepen = draaien · scrollen = zoomen · dubbelklik = beginstand</div></div></div>
<script>
const $=id=>document.getElementById(id);
const open_=new Set();
function grootte(b){if(b==null)return"";if(b<1024)return b+" B";if(b<1048576)return(b/1024).toFixed(0)+" kB";return(b/1048576).toFixed(1)+" MB"}
function el(t,k,tx){const e=document.createElement(t);if(k)e.className=k;if(tx!=null)e.textContent=tx;return e}
async function post(u){await fetch(u,{method:"POST"});ververs()}

/* ---------- 3D-preview (WebGL2, geen externe bibliotheken) ---------- */
const VS=`#version 300 es
in vec3 p;uniform mat3 R;uniform vec3 c;uniform float s;uniform vec2 k;out vec3 vp;
void main(){vp=R*((p-c)*s);gl_Position=vec4(vp.x*k.x,vp.y*k.y,-vp.z*0.5,1.0);}`;
const FS=`#version 300 es
precision highp float;in vec3 vp;uniform vec3 kleur;uniform float licht;out vec4 o;
void main(){vec3 col=kleur;if(licht>0.5){vec3 n=normalize(cross(dFdx(vp),dFdy(vp)));
col*=0.42+0.62*abs(dot(n,normalize(vec3(0.35,0.55,1.0))));}o=vec4(col,1.0);}`;
function maakView(cv){
  const gl=cv.getContext("webgl2",{antialias:true,alpha:true,preserveDrawingBuffer:true});if(!gl)return null;
  const sh=(t,src)=>{const x=gl.createShader(t);gl.shaderSource(x,src);gl.compileShader(x);return x};
  const pr=gl.createProgram();gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS));gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,FS));
  gl.linkProgram(pr);if(!gl.getProgramParameter(pr,gl.LINK_STATUS))return null;gl.useProgram(pr);
  const U=n=>gl.getUniformLocation(pr,n),ap=gl.getAttribLocation(pr,"p");let geo=null,bt=null,bs=null;
  gl.enable(gl.DEPTH_TEST);gl.enableVertexAttribArray(ap);
  return {laad(g){if(bt){gl.deleteBuffer(bt);gl.deleteBuffer(bs)}geo=g;
      bt=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bt);gl.bufferData(gl.ARRAY_BUFFER,g.tri,gl.STATIC_DRAW);
      bs=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bs);gl.bufferData(gl.ARRAY_BUFFER,g.seg,gl.STATIC_DRAW)},
    teken(az,el,zoom){if(!geo)return;gl.viewport(0,0,cv.width,cv.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      const ca=Math.cos(az),sa=Math.sin(az),ce=Math.cos(el),se=Math.sin(el);
      // Z omhoog: R = Rx(el) * B * Rz(az), rij-voor-rij
      gl.uniformMatrix3fv(U("R"),true,[ca,-sa,0, se*sa,se*ca,ce, -ce*sa,-ce*ca,se]);
      gl.uniform3fv(U("c"),geo.c);gl.uniform1f(U("s"),geo.s);
      const a=cv.width/cv.height;gl.uniform2f(U("k"),zoom/Math.max(a,1),zoom*Math.min(a,1));
      gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);
      gl.bindBuffer(gl.ARRAY_BUFFER,bt);gl.vertexAttribPointer(ap,3,gl.FLOAT,false,0,0);
      gl.uniform3f(U("kleur"),.62,.71,.82);gl.uniform1f(U("licht"),1);gl.drawArrays(gl.TRIANGLES,0,geo.tri.length/3);
      gl.disable(gl.POLYGON_OFFSET_FILL);
      gl.bindBuffer(gl.ARRAY_BUFFER,bs);gl.vertexAttribPointer(ap,3,gl.FLOAT,false,0,0);
      gl.uniform3f(U("kleur"),.08,.11,.16);gl.uniform1f(U("licht"),0);gl.drawArrays(gl.LINES,0,geo.seg.length/3)}};
}
async function haalGeo(pv){
  const buf=await(await fetch("preview/"+pv)).arrayBuffer(),dv=new DataView(buf);
  if(buf.byteLength<12||dv.getUint32(0,true)!=0x31503253)throw new Error("geen preview");
  const nt=dv.getUint32(4,true),ns=dv.getUint32(8,true);
  const tri=new Float32Array(buf,12,nt*9),seg=new Float32Array(buf,12+nt*36,ns*6);
  const lo=[1e30,1e30,1e30],hi=[-1e30,-1e30,-1e30];
  for(let i=0;i<tri.length;i++){const j=i%3,v=tri[i];if(v<lo[j])lo[j]=v;if(v>hi[j])hi[j]=v}
  const c=[0,1,2].map(j=>(lo[j]+hi[j])/2),r=Math.hypot(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2])/2||1;
  return {tri,seg,c,s:1/r};
}
const AZ0=-0.6,EL0=0.45,thumbs=new Map(),bezigThumb=new Set();let thumbView,thumbCv,modalView;
async function maakThumb(pv,img){
  if(bezigThumb.has(pv))return;bezigThumb.add(pv);
  try{if(thumbView===undefined){thumbCv=document.createElement("canvas");thumbCv.width=288;thumbCv.height=216;thumbView=maakView(thumbCv)}
    if(!thumbView)return;const g=await haalGeo(pv);thumbView.laad(g);thumbView.teken(AZ0,EL0,0.92);
    thumbs.set(pv,thumbCv.toDataURL());if(img.isConnected)img.src=thumbs.get(pv);else ververs()}
  catch(e){}finally{bezigThumb.delete(pv)}
}
let cam={az:AZ0,el:EL0,zoom:0.9};
function tekenModal(){const cv=$("mcanvas"),d=window.devicePixelRatio||1,w=Math.round(cv.clientWidth*d),h=Math.round(cv.clientHeight*d);
  if(cv.width!=w||cv.height!=h){cv.width=w;cv.height=h}modalView.teken(cam.az,cam.el,cam.zoom)}
async function bekijk(b){
  $("mnaam").textContent=b.step;$("mdl").href="step/"+encodeURIComponent(b.step);$("modal").classList.add("open");
  if(modalView===undefined)modalView=maakView($("mcanvas"));
  if(!modalView){$("mvoet").textContent="3D-weergave wordt niet ondersteund door deze browser.";return}
  try{modalView.laad(await haalGeo(b.preview));cam={az:AZ0,el:EL0,zoom:0.9};tekenModal()}catch(e){$("mvoet").textContent="Preview kon niet geladen worden."}
}
function sluit(){$("modal").classList.remove("open")}
(function(){const cv=$("mcanvas");let vast=null;
  cv.onpointerdown=e=>{vast=[e.clientX,e.clientY];cv.setPointerCapture(e.pointerId)};
  cv.onpointermove=e=>{if(!vast||!modalView)return;cam.az+=(e.clientX-vast[0])*0.01;
    cam.el=Math.max(-1.57,Math.min(1.57,cam.el+(e.clientY-vast[1])*0.01));vast=[e.clientX,e.clientY];tekenModal()};
  cv.onpointerup=cv.onpointercancel=()=>{vast=null};
  cv.onwheel=e=>{e.preventDefault();if(!modalView)return;cam.zoom=Math.max(0.2,Math.min(12,cam.zoom*Math.exp(-e.deltaY*0.0015)));tekenModal()};
  cv.ondblclick=()=>{if(!modalView)return;cam={az:AZ0,el:EL0,zoom:0.9};tekenModal()};
  $("msluit").onclick=sluit;$("modal").onclick=e=>{if(e.target.id=="modal")sluit()};
  addEventListener("keydown",e=>{if(e.key=="Escape")sluit()});
  addEventListener("resize",()=>{if($("modal").classList.contains("open")&&modalView)tekenModal()});
})();
const LABEL={klaar:"Klaar",mislukt:"Mislukt",bezig:"Bezig…",wachten:"Wacht"};
async function ververs(){
  let d;try{d=await(await fetch("api/status")).json()}catch(e){return}
  const tb=$("rijen");tb.replaceChildren();$("leeg").style.display=d.bestanden.length?"none":"";
  for(const b of d.bestanden){
    const tr=el("tr"),n=el("td","naam",b.naam),th=el("td","thumb");
    if(b.preview){const im=el("img","th");im.alt="Preview";im.title="Bekijk in 3D";im.onclick=()=>bekijk(b);
      if(thumbs.has(b.preview))im.src=thumbs.get(b.preview);else maakThumb(b.preview,im);th.append(im)}
    else th.append(el("span","th"));
    if(b.info){const dt=el("details");dt.open=open_.has(b.naam);
      dt.addEventListener("toggle",()=>dt.open?open_.add(b.naam):open_.delete(b.naam));
      dt.append(el("summary",null,b.status=="mislukt"?"Foutmelding":"Details"),el("pre",null,b.info));n.append(dt)}
    const s=el("td");s.append(el("span","st "+b.status,LABEL[b.status]));
    const a=el("td","r");
    if(b.step){const l=el("a","knop","Download STEP");l.href="step/"+encodeURIComponent(b.step);a.append(l)}
    if(b.preview){const v=el("button",null,"Bekijk");v.onclick=()=>bekijk(b);a.append(v)}
    if(b.stl&&b.status!="bezig"&&b.status!="wachten"){const r=el("button",null,"Opnieuw");r.onclick=()=>post("api/opnieuw?naam="+encodeURIComponent(b.naam));a.append(r)}
    if(b.status!="bezig"){const x=el("button",null,"Verwijder");x.onclick=()=>{if(confirm("'"+b.naam+"' en de bijbehorende STEP verwijderen?"))post("api/verwijder?naam="+encodeURIComponent(b.naam))};a.append(x)}
    tr.append(th,n,el("td","g r",grootte(b.grootte)),s,a);tb.append(tr)}
  const lg=$("log"),onder=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-8;
  lg.textContent=d.log.join("\n")||"(leeg)";if(onder)lg.scrollTop=lg.scrollHeight;
}
function stuur(f){return new Promise(res=>{
  if(!/\.stl$/i.test(f.name)){res("geen STL: "+f.name);return}
  const x=new XMLHttpRequest();x.open("POST","api/upload?naam="+encodeURIComponent(f.name));
  x.upload.onprogress=e=>{$("upl").textContent=f.name+" uploaden… "+Math.round(100*e.loaded/e.total)+"%"};
  x.onload=()=>res(x.status==200?null:(f.name+": "+x.responseText));x.onerror=()=>res(f.name+": verbinding mislukt");x.send(f)})}
async function upload(lijst){const fouten=[];for(const f of lijst){const e=await stuur(f);if(e)fouten.push(e)}
  $("upl").textContent=fouten.length?fouten.join(" · "):"";$("kies").value="";ververs()}
const dr=$("drop");dr.onclick=()=>$("kies").click();$("kies").onchange=e=>upload(e.target.files);
dr.ondragover=e=>{e.preventDefault();dr.classList.add("over")};dr.ondragleave=()=>dr.classList.remove("over");
dr.ondrop=e=>{e.preventDefault();dr.classList.remove("over");upload(e.dataTransfer.files)};
ververs();setInterval(ververs,2500);
</script></body></html>
"""


def veilige_naam(naam):
    """Alleen een kale bestandsnaam toestaan (geen paden, geen verborgen bestanden)."""
    if not naam or naam != os.path.basename(naam) or "\\" in naam or naam.startswith(".") or "\x00" in naam:
        return None
    return naam


def lees(pad, limiet=4000):
    try:
        return pad.read_text(encoding="utf-8", errors="replace")[-limiet:].strip()
    except OSError:
        return ""


def log_details():
    """Per bestandsnaam de detailregels van de laatste geslaagde conversie uit het logboek."""
    regels = lees(LOG, 200000).splitlines()
    details, huidig = {}, None
    for r in regels:
        tekst = r[21:] if len(r) > 21 else ""
        if tekst.startswith("klaar: "):
            huidig = tekst[7:].split(" -> ")[0]
            details[huidig] = []
        elif tekst.startswith("    ") and huidig:
            details[huidig].append(tekst.strip())
        else:
            huidig = None
    return regels[-60:], details


def preview_ref(stam):
    pv = PREVIEW / (stam + ".s2p")
    try:
        return "%s?v=%d" % (urllib.parse.quote(pv.name), pv.stat().st_mtime_ns)
    except OSError:
        return None


def status():
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    bezig = lees(BEZIG)
    logregels, details = log_details()
    uit, gezien = [], set()
    try:
        stls = sorted((f for f in STL.iterdir() if f.is_file() and f.suffix.lower() == ".stl"
                       and not f.name.startswith(".")), key=lambda f: -f.stat().st_mtime)
    except OSError:
        stls = []
    for f in stls:
        st = f.stat()
        step = STEP / (f.stem + ".step")
        gezien.add(step.name)
        s = state.get(f.name)
        actueel = bool(s) and s["sig"] == [st.st_size, st.st_mtime_ns]
        info = ""
        if f.name == bezig:
            stat = "bezig"
        elif actueel and s["ok"] and step.exists():
            stat = "klaar"
            info = "\n".join(details.get(f.name, []))
        elif actueel and not s["ok"]:
            stat = "mislukt"
            info = lees(STEP / (f.stem + "_FOUT.txt"))
        else:
            stat = "wachten"
        uit.append({"naam": f.name, "stl": True, "grootte": st.st_size, "status": stat,
                    "step": step.name if stat == "klaar" else None, "info": info,
                    "preview": preview_ref(f.stem) if stat == "klaar" else None})
    try:   # STEP's waarvan de STL al weg is, blijven te downloaden
        for f in sorted(STEP.iterdir()):
            if f.is_file() and f.suffix.lower() == ".step" and f.name not in gezien and not f.name.startswith("."):
                uit.append({"naam": f.name, "stl": False, "grootte": f.stat().st_size, "status": "klaar",
                            "step": f.name, "info": "", "preview": preview_ref(f.stem)})
    except OSError:
        pass
    return {"bestanden": uit, "log": logregels}


class Handler(BaseHTTPRequestHandler):
    server_version = "stl2step"

    def log_message(self, *a):
        pass

    def stuur(self, code, body, ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def naam_param(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return veilige_naam((q.get("naam") or [""])[0])

    def do_GET(self):
        pad = urllib.parse.urlsplit(self.path).path
        if pad == "/":
            return self.stuur(200, PAGINA, "text/html; charset=utf-8")
        if pad == "/api/status":
            return self.stuur(200, json.dumps(status()), "application/json")
        if pad.startswith("/step/"):
            naam = veilige_naam(urllib.parse.unquote(pad[6:]))
            f = STEP / naam if naam else None
            if not f or f.suffix.lower() != ".step" or not f.is_file():
                return self.stuur(404, "niet gevonden")
            self.send_response(200)
            self.send_header("Content-Type", "application/step")
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(naam))
            self.end_headers()
            with open(f, "rb") as h:
                while True:
                    blok = h.read(1 << 16)
                    if not blok:
                        break
                    self.wfile.write(blok)
            return
        if pad.startswith("/preview/"):
            naam = veilige_naam(urllib.parse.unquote(pad[9:]))
            f = PREVIEW / naam if naam else None
            if not f or f.suffix != ".s2p" or not f.is_file():
                return self.stuur(404, "niet gevonden")
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=31536000, immutable")   # adres bevat een versienummer
            self.end_headers()
            self.wfile.write(data)
            return
        self.stuur(404, "niet gevonden")

    def do_POST(self):
        pad = urllib.parse.urlsplit(self.path).path
        naam = self.naam_param()
        if not naam:
            return self.stuur(400, "ongeldige bestandsnaam")
        if pad == "/api/upload":
            if not naam.lower().endswith(".stl"):
                return self.stuur(400, "alleen .stl-bestanden")
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self.stuur(411, "lengte ontbreekt")
            if n <= 0 or n > MAX_UPLOAD:
                return self.stuur(413, "bestand is leeg of te groot")
            tmp = STL / (".upload-" + naam + ".part")     # de watcher slaat bestanden met een punt over
            try:
                with open(tmp, "wb") as h:
                    over = n
                    while over:
                        blok = self.rfile.read(min(over, 1 << 16))
                        if not blok:
                            raise OSError("upload afgebroken")
                        h.write(blok)
                        over -= len(blok)
                os.replace(tmp, STL / naam)
            except OSError as e:
                tmp.unlink(missing_ok=True)
                return self.stuur(500, str(e))
            return self.stuur(200, "ok")
        stam = naam.rsplit(".", 1)[0]
        if pad == "/api/verwijder":
            if naam.lower().endswith(".stl"):
                (STL / naam).unlink(missing_ok=True)
            (STEP / (stam + ".step")).unlink(missing_ok=True)
            (STEP / (stam + "_FOUT.txt")).unlink(missing_ok=True)
            (PREVIEW / (stam + ".s2p")).unlink(missing_ok=True)
            return self.stuur(200, "ok")
        if pad == "/api/opnieuw":
            f = STL / naam
            if not naam.lower().endswith(".stl") or not f.is_file():
                return self.stuur(404, "niet gevonden")
            os.utime(f)                                     # nieuwe tijd -> watcher zet hem opnieuw om
            return self.stuur(200, "ok")
        self.stuur(404, "niet gevonden")


if __name__ == "__main__":
    STL.mkdir(parents=True, exist_ok=True)
    STEP.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", POORT), Handler).serve_forever()
