"""Boutiques françaises / livrant la France : LDLC, Materiel.net, TopAchat, Alternate."""
from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

from .. import specs
from .base import RawOffer, Source, euro, jsonld_offer, soup


def _wanted(title: str, extra: str, cfg) -> bool:
    """Évite de télécharger la fiche de produits qui ne nous intéressent pas."""
    s = specs.parse(title, extra)
    lo, hi = cfg["capacity_min"], cfg["capacity_max"]
    return s.klass in cfg["classes"] and (s.capacity_tb is None or lo <= s.capacity_tb <= hi)


class LDLC(Source):
    LISTING = "https://www.ldlc.com/informatique/pieces-informatique/disque-dur-interne/c4697/+fi1192-l{lo}000h{hi}000.html"

    def scan(self, fetcher, cfg):
        url = self.LISTING.format(lo=int(cfg["capacity_min"]), hi=int(cfg["capacity_max"]))
        seen, out, pages = set(), [], [url]
        while pages and len(seen) < 400:
            page = pages.pop(0)
            s = soup(fetcher.get(page))
            for li in s.select("li.pdt-item"):
                a = li.select_one("h3 a")
                if not a:
                    continue
                href = urljoin("https://www.ldlc.com", a["href"])
                if href in seen:
                    continue
                seen.add(href)
                title = a.get_text(" ", strip=True)
                desc = (li.select_one("p.desc") or a).get_text(" ", strip=True)
                if not _wanted(title, desc, cfg):
                    continue
                price, stock = jsonld_offer(fetcher.get(href))   # prix chargé en JS sur la liste
                out.append(RawOffer(pid=li.get("data-id") or href, url=href, title=title,
                                    extra=desc, price=price, in_stock=stock))
            for nxt in s.select('ul.pagination a[href*="page"]'):
                u = urljoin(page, nxt["href"])
                if u not in seen and u not in pages and "page1/" not in u:
                    seen.add(u)
                    pages.append(u)
        return out


class Materiel(Source):
    LISTING = "https://www.materiel.net/disque-dur-interne/l430/+fi1192-l{lo}000h{hi}000/"

    def scan(self, fetcher, cfg):
        url = self.LISTING.format(lo=int(cfg["capacity_min"]), hi=int(cfg["capacity_max"]))
        out, pages, seen = {}, [url], {url}
        while pages:
            page = pages.pop(0)
            html = fetcher.get(page)
            s = soup(html)
            # les prix sont injectés par de petits scripts en fin de page
            inline = {m.group(1): soup(m.group(2).replace("\\'", "'")).get_text(" ", strip=True)
                      for m in re.finditer(r"getItem\('(AR\d+)', '\.o-product__prices'\)\.outerHTML = '(.*?)';\s", html, re.S)}
            stock_inline = {}
            for m in re.finditer(r"getItem\('(AR\d+)', '[^']*js__stock_web'\)", html):
                v = re.search(r'js__stock_web[^>]*>.*?o-availability__value--stock_\d+">([^<]*)',
                              html[m.end():m.end() + 3000], re.S)
                if v:
                    stock_inline.setdefault(m.group(1), v.group(1).lower())
            for li in s.select("li.c-products-list__item"):
                a = li.select_one("a.c-product__link")
                t = li.select_one(".c-product__title")
                if not a or not t:
                    continue
                pr = li.select_one(".o-product__price")
                st = li.select_one(".js__stock_web .o-availability__value") or li.select_one(".o-availability__value")
                desc = li.select_one(".c-product__description")
                pid = li.get("data-id") or a["href"]
                stock_txt = stock_inline.get(pid) or (st.get_text(" ", strip=True).lower() if st else "")
                out[pid] = RawOffer(
                    pid=pid, url=urljoin("https://www.materiel.net", a["href"]),
                    title=t.get_text(" ", strip=True),
                    extra=desc.get_text(" ", strip=True) if desc else "",
                    price=euro(inline.get(pid) or (pr.get_text(" ", strip=True) if pr else None)),
                    in_stock=None if not stock_txt else ("stock" in stock_txt),
                )
            for nxt in s.select('a[href*="/page"]'):
                u = urljoin(page, nxt["href"])
                if "/l430/" in u and "+fi1192" in u and u not in seen:
                    seen.add(u)
                    pages.append(u)
        return list(out.values())


class TopAchat(Source):
    BASE = "https://www.topachat.com/pages/produits_cat_est_micro_puis_rubrique_est_wdi_sata{suffix}.html"

    def scan(self, fetcher, cfg):
        out = {}
        for n in range(1, 15):
            url = self.BASE.format(suffix="" if n == 1 else f"_puis_page_est_{n}")
            s = soup(fetcher.get(url))
            wraps = s.select(".product-list__product-wrapper")
            new = 0
            for w in wraps:
                a = w.select_one("a[aria-label]")
                if not a:
                    continue
                pid = w.get("id") or a["href"]
                if pid in out:
                    continue
                new += 1
                pr = w.select_one(".product__price")
                st = w.select_one("[data-code]")
                out[pid] = RawOffer(
                    pid=pid, url=urljoin("https://www.topachat.com", a["href"]),
                    title=a["aria-label"], extra=w.get_text(" ", strip=True)[:300],
                    price=euro(pr.get_text(" ", strip=True)) if pr else None,
                    in_stock=None if not st else st.get("data-code") == "available",
                )
            if not wraps or not new:
                break
        return list(out.values())


class Alternate(Source):
    QUERIES = {"serveur": ["seagate exos", "ultrastar", "toshiba mg", "wd gold"],
               "nas_pro": ["ironwolf pro", "wd red pro"]}

    def scan(self, fetcher, cfg):
        out = {}
        for q in [q for k in cfg["classes"] for q in self.QUERIES.get(k, [])]:
            for page in range(1, 6):
                url = f"https://{self.domain}/listing.xhtml?q={quote_plus(q)}" + (f"&page={page}" if page > 1 else "")
                s = soup(fetcher.get(url))
                cards = s.select("a.productBox")
                new = 0
                for c in cards:
                    href = urljoin(f"https://{self.domain}", c.get("href", ""))
                    n = c.select_one(".product-name")
                    if not n or href in out:
                        continue
                    new += 1
                    pr = c.select_one(".price")
                    dl = c.select_one(".delivery-info")
                    dtxt = dl.get_text(" ", strip=True).lower() if dl else ""
                    out[href] = RawOffer(
                        pid=href.rsplit("/", 1)[-1], url=href, title=n.get_text(" ", strip=True),
                        extra=c.get_text(" ", strip=True)[:400],
                        price=euro(pr.get_text(" ", strip=True)) if pr else None,
                        in_stock=None if not dtxt else not any(w in dtxt for w in ("indisponible", "inconnu", "épuisé")),
                    )
                if len(cards) < 24 or not new:
                    break
        return list(out.values())


def make() -> list[Source]:
    return [
        LDLC(key="ldlc", site="LDLC", country="FR", domain="www.ldlc.com"),
        Materiel(key="materiel", site="Materiel.net", country="FR", domain="www.materiel.net"),
        TopAchat(key="topachat", site="TopAchat", country="FR", domain="www.topachat.com"),
        Alternate(key="alternate_fr", site="Alternate", country="FR", domain="www.alternate.fr",
                  notes=["Expédié depuis l'Allemagne, prix en TVA française."],
                  warranty_refurb="Reconditionné Alternate : durée de garantie indiquée sur la fiche produit."),
    ]
