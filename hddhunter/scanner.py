"""Boucle de surveillance : scanne chaque boutique, enregistre les prix, prévient
quand un disque correspondant apparaît ou baisse."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
import traceback

from . import db, specs
from .fetch import Blocked, Disallowed, Fetcher
from .sources import ALL, BY_KEY
from .sources.amazon import Amazon, inspect_page

log = logging.getLogger("hddhunter")

KEEP_CLASSES = (specs.SERVER, specs.NAS_PRO)
HISTORY_EVERY = 6 * 3600       # un point d'historique au moins toutes les 6 h, sinon à chaque changement
PAGE_RECHECK = 7 * 86400       # relecture d'une fiche Amazon (état, vendeur) au plus une fois par semaine
PAGES_PER_SCAN = 15            # fiches lues au maximum par boutique et par passage (vérification de l'état)
SELLER_PAGES_PER_SCAN = 10     # + fiches relues après un changement de prix, pour savoir quel vendeur l'affiche


class Scanner:
    def __init__(self):
        self.fetcher = Fetcher(log=log.info)
        self.wake = threading.Event()
        self.running = False
        self.current = None           # source en cours de scan
        self.next_run = 0.0
        self.backoff: dict[str, tuple[float, int]] = {}   # source -> (jusqu'à, nb d'échecs)
        self.pending: list[tuple[float, str, str]] = []    # alertes du cycle (prix, type, texte)
        self.price_changed: set[int] = set()               # offres Amazon dont le prix vient de bouger

    # ------------------------------------------------------------------ boucle
    def loop(self):
        # au redémarrage, ne pas rescanner si le dernier passage est récent
        con = db.connect()
        last = con.execute("SELECT MAX(finished) FROM scans").fetchone()[0] or 0
        con.close()
        wait = last + db.load_config()["interval_min"] * 60 - time.time()
        if wait > 0:
            self.next_run = time.time() + wait
            self.wake.wait(timeout=wait)
            self.wake.clear()
        while True:
            try:
                self.run_cycle()
            except Exception:  # ne jamais arrêter le service
                log.error("cycle : %s", traceback.format_exc())
            cfg = db.load_config()
            self.next_run = time.time() + cfg["interval_min"] * 60
            self.wake.wait(timeout=cfg["interval_min"] * 60)
            self.wake.clear()

    def trigger(self):
        self.backoff.clear()
        self.wake.set()

    def run_cycle(self):
        cfg = db.load_config()
        self.running = True
        try:
            for src in ALL:
                if src.key in cfg["disabled_sources"]:
                    continue
                until, _ = self.backoff.get(src.key, (0, 0))
                if until > time.time():
                    continue
                self.current = src.key
                self.scan_source(src, cfg)
        finally:
            self.running, self.current = False, None
            self.notify(cfg)

    def notify(self, cfg):
        """Une seule notification macOS par cycle, même s'il y a beaucoup d'alertes."""
        alerts, self.pending = sorted(self.pending), []
        if not alerts or not cfg.get("notify"):
            return
        if len(alerts) == 1:
            title = "HDD Hunter — " + ("nouvelle offre" if alerts[0][1] == "nouveau" else "baisse de prix")
            text = alerts[0][2]
        else:
            n_new = sum(a[1] == "nouveau" for a in alerts)
            parts = [f"{n_new} nouvelle(s) offre(s)"] if n_new else []
            if len(alerts) - n_new:
                parts.append(f"{len(alerts) - n_new} baisse(s)")
            title = "HDD Hunter — " + " et ".join(parts)
            text = "La moins chère : " + alerts[0][2]
        # Les titres viennent des sites web : ils sont passés en arguments, jamais insérés dans le script.
        script = ("on run argv\n"
                  "display notification (item 1 of argv) with title (item 2 of argv) "
                  "subtitle (item 3 of argv) sound name \"Glass\"\nend run")
        try:
            subprocess.run(["osascript", "-e", script, text, title, f"http://127.0.0.1:{cfg['port']}"],
                           timeout=10, capture_output=True)
        except Exception:
            pass

    # ------------------------------------------------------------------ source
    def scan_source(self, src, cfg):
        con = db.connect()
        started = time.time()
        status, msg, found, matched = "ok", "", 0, 0
        try:
            raws = src.scan(self.fetcher, cfg)
            found = len(raws)
            seen = set()
            self.price_changed = set()   # offres dont le prix vient de changer (vendeur à relire)
            for r in raws:
                oid, is_match = self.store(con, src, r, cfg)
                if oid:
                    seen.add(oid)
                    matched += is_match
            # ce qui n'a pas été revu n'est plus en vente — sauf si la page est revenue vide
            # (souci passager du site : on ne retire rien sur un passage sans résultat)
            if found:
                ids = ",".join(map(str, seen)) or "0"
                con.execute(f"UPDATE offers SET active=0 WHERE source=? AND id NOT IN ({ids})", (src.key,))
            con.commit()
            if isinstance(src, Amazon):
                self.inspect_pages(con, src, cfg)
            self.backoff.pop(src.key, None)
            if not found:
                status, msg = "vide", "aucun produit lu — la mise en page du site a peut-être changé"
        except Blocked as e:
            n = self.backoff.get(src.key, (0, 0))[1] + 1
            self.backoff[src.key] = (time.time() + min(3 * 3600 * n, 24 * 3600), n)
            status, msg = "bloqué", f"{e} — nouvel essai dans {min(3 * n, 24)} h"
        except Disallowed as e:
            status, msg = "interdit", f"robots.txt refuse {e}"
        except Exception as e:
            status, msg = "erreur", f"{type(e).__name__}: {e}"
            log.error("%s : %s", src.key, traceback.format_exc())
        con.execute("INSERT INTO scans(source,started,finished,status,found,matched,message) VALUES(?,?,?,?,?,?,?)",
                    (src.key, started, time.time(), status, found, matched, msg))
        con.commit()
        con.close()
        log.info("%-13s %-8s %3d produits, %2d correspondent %s", src.key, status, found, matched, msg)

    def store(self, con, src, r, cfg):
        s = specs.parse(r.title, r.extra)
        if s.klass not in KEEP_CLASSES or not s.capacity_tb or not (10 <= s.capacity_tb <= 32):
            return None, False
        now = time.time()
        key = f"{src.key}|{r.pid}"
        price_fr = src.price_fr(r.price)
        stock = None if r.in_stock is None else int(r.in_stock)
        row = con.execute("SELECT * FROM offers WHERE key=?", (key,)).fetchone()
        if row is not None and s.condition == "neuf" and row["page_checked"]:
            # le titre ne dit rien, mais la fiche produit (lue plus tôt) en dit plus
            if row["page_condition"]:
                s.condition, s.condition_src, s.condition_note = row["page_condition"], row["page_src"], row["page_note"]
            elif row["page_note"]:
                s.condition_note = row["page_note"]
        fields = dict(source=src.key, site=src.site, country=src.country, url=r.url, title=r.title,
                      brand=s.brand, family=s.family, model_no=s.model_no, capacity_tb=s.capacity_tb,
                      rpm=s.rpm, cache_mb=s.cache_mb, cache_estimated=int(s.cache_estimated),
                      interface=s.interface, condition=s.condition, klass=s.klass,
                      condition_src=s.condition_src, condition_note=s.condition_note,
                      price=r.price, price_fr=price_fr, in_stock=stock, active=1, last_seen=now)
        if row is None:
            fields.update(key=key, first_seen=now)
            cols = ",".join(fields)
            cur = con.execute(f"INSERT INTO offers({cols}) VALUES({','.join('?' * len(fields))})", list(fields.values()))
            oid = cur.lastrowid
            was_match, old_price = False, None
        else:
            oid = row["id"]
            was_match = row["active"] and db.matches(dict(row), cfg)
            old_price = row["price_fr"]
            con.execute(f"UPDATE offers SET {','.join(k + '=?' for k in fields)} WHERE id=?", [*fields.values(), oid])

        last = con.execute("SELECT ts, price_fr, in_stock, seller FROM prices WHERE offer_id=? ORDER BY ts DESC LIMIT 1",
                           (oid,)).fetchone()
        price_moved = last is None or last["price_fr"] != price_fr
        if price_fr is not None and (price_moved or last["in_stock"] != stock or now - last["ts"] > HISTORY_EVERY):
            # même prix : très probablement le même vendeur ; prix différent : vendeur à relire sur la fiche
            seller = None if price_moved else last["seller"]
            con.execute("INSERT INTO prices(offer_id, ts, price_fr, in_stock, seller) VALUES(?,?,?,?,?)",
                        (oid, now, price_fr, stock, seller))
            if price_moved and isinstance(src, Amazon):
                self.price_changed.add(oid)

        is_match = db.matches(fields, cfg)
        if is_match and not was_match:
            self.event(con, oid, price_fr, "nouveau", f"{s.family or s.brand} {s.capacity_tb:g} To {s.condition} — "
                       f"{price_fr:.0f} € sur {src.site} {src.country}")
        elif is_match and old_price and price_fr < old_price * 0.97:
            self.event(con, oid, price_fr, "baisse", f"{s.family or s.brand} {s.capacity_tb:g} To : {old_price:.0f} → "
                       f"{price_fr:.0f} € sur {src.site} {src.country}")
        return oid, is_match

    def inspect_pages(self, con, src, cfg):
        """Lit des fiches produit Amazon :
        - les offres « neuves » proches des critères, une fois par semaine, pour repérer les reconditionnés
          que le titre ne signale pas (programme Renewed, description, avis) ;
        - les offres proches des critères dont le prix vient de changer, pour savoir quel vendeur
          affiche ce nouveau prix (changement de vendeur dans le panier, guerre de prix entre vendeurs).
        Une fiche qui sert aux deux n'est lue qu'une fois."""
        widen = dict(price_min=cfg["price_min"] * 0.85, price_max=cfg["price_max"] * 1.15)
        near_new = dict(cfg, **widen, conditions=["neuf"])
        near_any = dict(cfg, **widen, conditions=sorted(set(cfg["conditions"]) | {"neuf"}))
        rows = con.execute(
            "SELECT * FROM offers WHERE source=? AND active=1 AND condition='neuf' "
            "AND (page_checked IS NULL OR page_checked < ?) ORDER BY price_fr",
            (src.key, time.time() - PAGE_RECHECK)).fetchall()
        check_condition = [r for r in rows if db.matches(dict(r), near_new)][:PAGES_PER_SCAN]
        changed = getattr(self, "price_changed", set())
        moved = [r for r in con.execute("SELECT * FROM offers WHERE source=? AND active=1 ORDER BY price_fr", (src.key,))
                 if r["id"] in changed and db.matches(dict(r), near_any)][:SELLER_PAGES_PER_SCAN]
        todo, seen_ids = [], set()
        for r in moved + check_condition:          # priorité aux prix qui viennent de bouger
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"]); todo.append(r)
        cond_ids = {r["id"] for r in check_condition}
        for r in todo:
            try:
                info = inspect_page(self.fetcher.get(r["url"]))
            except (Blocked, Disallowed) as e:
                log.info("%s : lecture des fiches interrompue (%s)", src.key, e)
                break
            if info["seller"]:
                self.record_seller(con, src, r, info["seller"])
            if r["id"] not in cond_ids:            # fiche lue seulement pour le vendeur
                con.commit()
                continue
            con.execute("UPDATE offers SET page_checked=?, page_condition=?, page_src=?, page_note=? WHERE id=?",
                        (time.time(), info["condition"], info["src"], info["note"], r["id"]))
            if info["condition"]:
                con.execute("UPDATE offers SET condition=?, condition_src=?, condition_note=? WHERE id=?",
                            (info["condition"], info["src"], info["note"], r["id"]))
                log.info("%s : %s → %s (%s)", src.key, r["title"][:60], info["condition"], info["src"])
            elif info["note"]:
                con.execute("UPDATE offers SET condition_note=? WHERE id=?", (info["note"], r["id"]))
            con.commit()

    def record_seller(self, con, src, offer, seller):
        """Note le vendeur sur l'offre et sur son dernier relevé de prix (s'il n'est pas encore connu)."""
        previous = con.execute("SELECT seller FROM prices WHERE offer_id=? AND seller IS NOT NULL AND seller != '' "
                               "ORDER BY ts DESC LIMIT 1", (offer["id"],)).fetchone()
        con.execute("UPDATE offers SET seller=? WHERE id=?", (seller, offer["id"]))
        con.execute("UPDATE prices SET seller=? WHERE offer_id=? AND (seller IS NULL OR seller='') "
                    "AND ts=(SELECT MAX(ts) FROM prices WHERE offer_id=?)", (seller, offer["id"], offer["id"]))
        if previous and previous["seller"] != seller:
            log.info("%s : changement de vendeur sur « %s » : %s → %s (%.0f €)", src.key, offer["title"][:50],
                     previous["seller"], seller, offer["price_fr"] or 0)

    def event(self, con, oid, price, kind, text):
        con.execute("INSERT INTO events(ts,offer_id,kind,text) VALUES(?,?,?,?)", (time.time(), oid, kind, text))
        log.info("ALERTE %s : %s", kind, text)
        self.pending.append((price, kind, text))


SOURCES_INFO = [
    dict(key=s.key, site=s.site, country=s.country, domain=s.domain, ships_fr=s.ships_fr,
         returns=s.returns, warranty_new=s.warranty_new, warranty_refurb=s.warranty_refurb, notes=s.notes)
    for s in ALL
]
__all__ = ["Scanner", "SOURCES_INFO", "BY_KEY"]
