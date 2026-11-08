from __future__ import annotations

import time
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from . import db
from .scanner import SOURCES_INFO

STATIC = Path(__file__).parent / "static"


def create_app(scanner) -> FastAPI:
    app = FastAPI(title="HDD Hunter")
    port = db.load_config()["port"]
    own = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # L'interface n'écoute que sur 127.0.0.1, mais une page web ouverte dans le navigateur pourrait
        # quand même lui envoyer des requêtes (changer les critères, lancer des scans) ou passer par un
        # domaine qui pointe vers 127.0.0.1 (« DNS rebinding »). On n'accepte que l'interface elle-même.
        host = request.headers.get("host", "").lower()
        origin = request.headers.get("origin")
        site = request.headers.get("sec-fetch-site", "none")
        navigation = request.method == "GET" and request.headers.get("sec-fetch-mode") == "navigate"
        if host not in own or (origin is not None and origin.split("://", 1)[-1] not in own) \
                or (site not in ("same-origin", "none") and not navigation):
            return JSONResponse({"error": "requête refusée"}, status_code=403)
        return await call_next(request)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/offers")
    def offers(all: bool = False):
        con = db.connect()
        q = "SELECT * FROM offers" + ("" if all else " WHERE active=1") + " ORDER BY price_fr"
        rows = [dict(r) for r in con.execute(q)]
        # prix le plus bas jamais vu pour chaque offre
        lows = {r["offer_id"]: r["lo"] for r in con.execute("SELECT offer_id, MIN(price_fr) lo FROM prices GROUP BY offer_id")}
        con.close()
        cfg = db.load_config()
        for r in rows:
            r["match"] = db.matches(r, cfg)
            r["lowest"] = lows.get(r["id"])
            r["eur_tb"] = round(r["price_fr"] / r["capacity_tb"], 1) if r["price_fr"] and r["capacity_tb"] else None
        return rows

    @app.get("/api/history/{offer_id}")
    def history(offer_id: int):
        con = db.connect()
        pts = [dict(r) for r in con.execute("SELECT ts, price_fr, in_stock, seller FROM prices WHERE offer_id=? ORDER BY ts", (offer_id,))]
        con.close()
        return pts

    @app.get("/api/best")
    def best(days: int = 90):
        """Meilleur prix (critères de recherche) par jour et par capacité."""
        # Un relevé n'est enregistré que quand le prix change (ou toutes les 6 h) : pour chaque jour, chaque
        # offre en vente compte au prix qu'elle avait ce jour-là, y compris celui hérité des jours précédents.
        import datetime as dt
        cfg = db.load_config()
        con = db.connect()
        offers = {r["id"]: dict(r) for r in con.execute("SELECT * FROM offers")}
        points: dict[int, list] = {}
        for r in con.execute("SELECT offer_id, ts, price_fr, in_stock FROM prices ORDER BY ts"):
            points.setdefault(r["offer_id"], []).append((r["ts"], r["price_fr"], r["in_stock"]))
        con.close()
        any_price = dict(cfg, price_min=0, price_max=10**9)  # la courbe montre aussi les prix hors budget
        today = dt.date.today()
        first_day = max(dt.date.fromtimestamp(time.time() - days * 86400),
                        min((dt.date.fromtimestamp(p[0][0]) for p in points.values()), default=today))
        best: dict[tuple[str, float], float] = {}
        for oid, pts in points.items():
            o = offers.get(oid)
            if not o or not o["capacity_tb"]:
                continue
            on_sale_until = time.time() if o["active"] else (o["last_seen"] or pts[-1][0])
            i, current = 0, None                       # current = dernier relevé connu avant le jour courant
            day = first_day
            while day <= today:
                start = dt.datetime.combine(day, dt.time()).timestamp()
                end = start + 86400
                while i < len(pts) and pts[i][0] < start:
                    current = pts[i]; i += 1
                if start > on_sale_until:
                    break
                todays = [current] if current else []
                j = i
                while j < len(pts) and pts[j][0] < end:
                    todays.append(pts[j]); j += 1
                for _, price, stock in todays:
                    if price is not None and db.matches(dict(o, price_fr=price, in_stock=stock), any_price):
                        k = (day.isoformat(), o["capacity_tb"])
                        best[k] = min(best.get(k, 1e12), price)
                day += dt.timedelta(days=1)
        return [dict(day=d, capacity_tb=c, price=round(p, 2)) for (d, c), p in sorted(best.items())]

    @app.get("/api/status")
    def status():
        con = db.connect()
        last = {r["source"]: dict(r) for r in con.execute(
            "SELECT * FROM scans WHERE id IN (SELECT MAX(id) FROM scans GROUP BY source)")}
        events = [dict(r) for r in con.execute("SELECT * FROM events ORDER BY ts DESC LIMIT 30")]
        n_prices = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        con.close()
        cfg = db.load_config()
        return dict(
            sources=[dict(s, last=last.get(s["key"]), enabled=s["key"] not in cfg["disabled_sources"],
                          backoff_until=scanner.backoff.get(s["key"], (0, 0))[0] or None) for s in SOURCES_INFO],
            running=scanner.running, current=scanner.current, next_run=scanner.next_run,
            requests=scanner.fetcher.count, events=events, history_points=n_prices, now=time.time(),
        )

    @app.get("/api/urls")
    def urls():
        """Chaque URL jamais vue (même retirée de la vente) avec tous ses relevés de prix."""
        con = db.connect()
        offs = {r["id"]: dict(r) for r in con.execute(
            "SELECT id, url, site, country, title, family, brand, capacity_tb, condition, condition_src, "
            "condition_note, seller, active, first_seen, last_seen, price_fr, in_stock, rpm, cache_mb, klass, interface FROM offers")}
        for o in offs.values():
            o["points"] = []
        for r in con.execute("SELECT offer_id, ts, price_fr, seller FROM prices ORDER BY ts"):
            if r["offer_id"] in offs:
                offs[r["offer_id"]]["points"].append([round(r["ts"]), r["price_fr"], r["seller"] or ""])
        con.close()
        return [o for o in offs.values() if o["points"]]

    @app.get("/api/export.csv")
    def export_csv():
        """Tous les relevés : une ligne = une URL à une date avec son prix."""
        import csv, io
        from fastapi.responses import Response
        con = db.connect()
        rows = con.execute(
            """SELECT p.ts, o.url, o.site, o.country, o.title, o.capacity_tb, o.condition, p.seller,
                      p.price_fr, p.in_stock, o.active
               FROM prices p JOIN offers o ON o.id=p.offer_id ORDER BY o.url, p.ts""").fetchall()
        con.close()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["date", "url", "site", "pays", "titre", "capacite_to", "etat", "vendeur",
                    "prix_livre_fr_eur", "en_stock", "encore_en_vente"])
        for r in rows:
            w.writerow([time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), r["url"], r["site"], r["country"],
                        r["title"], r["capacity_tb"], r["condition"], r["seller"] or "",
                        str(r["price_fr"]).replace(".", ","), {1: "oui", 0: "non"}.get(r["in_stock"], ""),
                        "oui" if r["active"] else "non"])
        name = time.strftime("hddhunter-prix-%Y%m%d.csv")
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/boot.js")
    def boot():
        """Données initiales chargées avec la page (premier affichage immédiat)."""
        import json
        from fastapi.responses import Response
        data = dict(cfg=db.load_config(), offers=offers(), status=status(), best=best(120), urls=urls())
        return Response("window.BOOT=" + json.dumps(data, ensure_ascii=False) + ";",
                        media_type="application/javascript", headers={"Cache-Control": "no-store"})

    @app.post("/api/scan")
    def scan_now():
        scanner.trigger()
        return {"ok": True}

    @app.get("/api/config")
    def get_config():
        return db.load_config()

    @app.post("/api/config")
    def set_config(new: dict = Body(...)):
        return db.save_config(new)

    return app
