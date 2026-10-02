import os
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, importer
from .geocode import geocode_sicher
from .parser import parse_eur, parse_edikt

BASE = Path(__file__).resolve().parent
SITE_NAME = os.environ.get("SITE_NAME", "Versteigerungs-Immobilien Österreich")

app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
security = HTTPBasic()


def eur(value):
    if value is None:
        return "–"
    return "€ " + f"{value:,.0f}".replace(",", ".")


def datum(value):
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%d.%m.%Y, %H:%M Uhr") if dt.hour or dt.minute else dt.strftime("%d.%m.%Y")


def m2(value):
    if value is None:
        return "–"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").removesuffix(",00") + " m²"


templates.env.filters["eur"] = eur
templates.env.filters["m2"] = m2
templates.env.filters["datum"] = datum
templates.env.globals.update(
    SITE_NAME=SITE_NAME,
    BUNDESLAENDER=db.BUNDESLAENDER,
    OBJEKTARTEN=db.OBJEKTARTEN,
    IMPRESSUM=os.environ.get("IMPRESSUM", ""),
)


@app.on_event("startup")
def startup():
    db.init_db()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    user = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise HTTPException(503, "Admin deaktiviert: Umgebungsvariable ADMIN_PASSWORD setzen.")
    ok = secrets.compare_digest(credentials.username.encode(), user.encode()) and \
        secrets.compare_digest(credentials.password.encode(), password.encode())
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsche Zugangsdaten",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def _num(value):
    return parse_eur(value) if value not in (None, "") else None


# ---------- Öffentliche Seiten ----------

class Filter:
    """Gemeinsame Such-Parameter für Liste und Karte."""

    def __init__(self, q: str = "", bundesland: str = "", objektart: str = "",
                 preis_min: str = "", preis_max: str = "", flaeche_min: str = "",
                 vergangene: str = "", sort: str = "termin"):
        self.f = dict(q=q, bundesland=bundesland, objektart=objektart, preis_min=preis_min,
                      preis_max=preis_max, flaeche_min=flaeche_min, vergangene=vergangene, sort=sort)

    def context(self, request):
        f = self.f
        objekte = db.search(
            q=f["q"].strip() or None, bundesland=f["bundesland"] or None,
            objektart=f["objektart"] or None, preis_min=_num(f["preis_min"]),
            preis_max=_num(f["preis_max"]), flaeche_min=_num(f["flaeche_min"]),
            nur_kommende=not f["vergangene"], sort=f["sort"],
            now_iso=datetime.now().strftime("%Y-%m-%dT%H:%M"),
        )
        return {"objekte": objekte, "objektarten": db.objektarten(), "f": f,
                "query": request.url.query}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, filt: Filter = Depends()):
    return templates.TemplateResponse(request, "index.html", {**filt.context(request), "ansicht": "liste"})


@app.get("/karte", response_class=HTMLResponse)
def karte(request: Request, filt: Filter = Depends()):
    ctx = filt.context(request)
    punkte = [{
        "id": o["id"], "lat": o["lat"], "lon": o["lon"], "genau": bool(o["geo_genau"]),
        "titel": o["titel"] or o["objektart"] or "Liegenschaft",
        "ort": " ".join(x for x in (o["plz"], o["ort"]) if x),
        "adresse": o["adresse"] or "", "schaetzwert": eur(o["schaetzwert"]),
        "gebot": eur(o["geringstes_gebot"]), "termin": datum(o["termin"]),
    } for o in ctx["objekte"] if o["lat"] is not None]
    return templates.TemplateResponse(request, "karte.html", {
        **ctx, "ansicht": "karte", "punkte": punkte,
        "ohne_position": len(ctx["objekte"]) - len(punkte),
    })


@app.get("/objekt/{objekt_id}", response_class=HTMLResponse)
def detail(request: Request, objekt_id: int):
    o = db.get(objekt_id)
    if not o or not o["aktiv"]:
        raise HTTPException(404, "Objekt nicht gefunden")
    return templates.TemplateResponse(request, "detail.html", {"o": o})


@app.get("/impressum", response_class=HTMLResponse)
def impressum(request: Request):
    return templates.TemplateResponse(request, "impressum.html", {})


# ---------- Admin ----------

@app.get("/admin", response_class=HTMLResponse)
def admin_list(request: Request, meldung: str = "", _=Depends(require_admin)):
    return templates.TemplateResponse(request, "admin_list.html", {
        "objekte": db.all_objekte(), "ohne_koordinaten": len(db.ohne_koordinaten()),
        "meldung": meldung,
    })


@app.post("/admin/geocode")
def admin_geocode(_=Depends(require_admin)):
    gefunden = offen = 0
    for o in db.ohne_koordinaten():
        treffer = geocode_sicher(dict(o))
        if treffer:
            db.update(o["id"], treffer)
            gefunden += 1
        else:
            offen += 1
    meldung = f"{gefunden} Objekt(e) auf der Karte verortet"
    if offen:
        meldung += f", {offen} nicht gefunden – Koordinaten bitte manuell eintragen"
    return RedirectResponse("/admin?" + urlencode({"meldung": meldung}), status_code=303)


@app.get("/admin/neu", response_class=HTMLResponse)
def admin_new(request: Request, _=Depends(require_admin)):
    return templates.TemplateResponse(request, "admin_form.html", {"o": {"aktiv": 1}, "rohtext": ""})


@app.post("/admin/parse", response_class=HTMLResponse)
def admin_parse(request: Request, rohtext: str = Form(""), objekt_id: str = Form(""),
                _=Depends(require_admin)):
    o = dict(db.get(int(objekt_id))) if objekt_id else {"aktiv": 1}
    o.update(parse_edikt(rohtext))
    return templates.TemplateResponse(request, "admin_form.html", {
        "o": o, "rohtext": rohtext, "hinweis": "Felder aus dem Text vorausgefüllt – bitte prüfen!",
    })


def _form_data(form):
    data = {}
    for f in db.FIELDS:
        v = (form.get(f) or "").strip()
        if f in db.NUMERIC_FIELDS:
            data[f] = _num(v)
        elif f in db.COORD_FIELDS:
            try:
                data[f] = float(v.replace(",", ".")) if v else None
            except ValueError:
                data[f] = None
        elif f == "geo_genau":
            data[f] = 1 if v == "1" else 0
        elif f == "aktiv":
            data[f] = 1 if form.get("aktiv") else 0
        else:
            data[f] = v or None
    return data


@app.post("/admin/speichern")
async def admin_save(request: Request, _=Depends(require_admin)):
    form = await request.form()
    data = _form_data(form)
    if not data["aktenzeichen"]:
        return templates.TemplateResponse(request, "admin_form.html", {
            "o": {**data, "id": form.get("id") or None}, "rohtext": form.get("rohtext", ""),
            "fehler": "Aktenzeichen ist erforderlich.",
        }, status_code=400)
    if data["lat"] is None or data["lon"] is None:
        data.update(geocode_sicher(data))
    if form.get("id"):
        db.update(int(form["id"]), data)
    else:
        db.insert(data)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/import", response_class=HTMLResponse)
def admin_import_form(request: Request, _=Depends(require_admin)):
    return templates.TemplateResponse(request, "admin_import.html", {"text": "", "results": None})


@app.post("/admin/import", response_class=HTMLResponse)
def admin_import(request: Request, text: str = Form(""), _=Depends(require_admin)):
    ids = importer.extract_ids(text)
    results = importer.import_ids(ids) if ids else []
    return templates.TemplateResponse(request, "admin_import.html", {
        "text": text, "results": results,
        "fehler": None if ids else "Keine Links auf edikte.justiz.gv.at gefunden.",
    })


@app.get("/admin/{objekt_id}", response_class=HTMLResponse)
def admin_edit(request: Request, objekt_id: int, _=Depends(require_admin)):
    o = db.get(objekt_id)
    if not o:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "admin_form.html", {"o": dict(o), "rohtext": ""})


@app.post("/admin/{objekt_id}/loeschen")
def admin_delete(objekt_id: int, _=Depends(require_admin)):
    db.delete(objekt_id)
    return RedirectResponse("/admin", status_code=303)
