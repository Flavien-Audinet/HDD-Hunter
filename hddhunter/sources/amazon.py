from __future__ import annotations

import re
from urllib.parse import quote_plus

from .base import RawOffer, Source, euro, soup

QUERIES = {
    "serveur": ["seagate exos", "wd ultrastar dc hc", "toshiba mg10 mg09", "wd gold"],
    "nas_pro": ["seagate ironwolf pro", "wd red pro"],
}

COUNTRIES = [
    # code, domaine, TVA locale, langue d'en-tête
    ("FR", "www.amazon.fr", 0.20),
    ("DE", "www.amazon.de", 0.19),
    ("IT", "www.amazon.it", 0.22),
    ("ES", "www.amazon.es", 0.21),
    ("NL", "www.amazon.nl", 0.21),
    ("BE", "www.amazon.com.be", 0.21),
]


class Amazon(Source):
    def scan(self, fetcher, cfg):
        out: dict[str, RawOffer] = {}
        queries = [q for k in cfg["classes"] for q in QUERIES.get(k, [])]
        for q in queries:
            for page in (1, 2):
                url = f"https://{self.domain}/s?k={quote_plus(q)}" + (f"&page={page}" if page > 1 else "")
                html = fetcher.get(url)
                s = soup(html)
                items = s.select('div[data-component-type="s-search-result"]')
                for it in items:
                    asin = it.get("data-asin")
                    # selon la mise en page, un 1er <h2> peut ne contenir que la marque
                    cands = [h.get("aria-label") or h.get_text(" ", strip=True) for h in it.select("h2")]
                    title = max(cands, key=len, default="")
                    if not asin or not title:
                        continue
                    if len(title) < 25:   # marque seule : on complète avec le texte de la carte
                        title = it.get_text(" ", strip=True)[:250]
                    title = re.sub(r"^(Sponsored Ad|Annonce sponsorisée|Sponsorisé|Gesponsert|Sponsorizzato|Patrocinado|Gesponsord)\s*[–:-]?\s*",
                                   "", title, flags=re.I).strip()
                    p = it.select_one(".a-price:not(.a-text-price) .a-offscreen")
                    price = euro(p.get_text()) if p else None
                    if price is None:
                        continue  # pas de prix = indisponible ou seulement « autres vendeurs »
                    out[asin] = RawOffer(pid=asin, url=f"https://{self.domain}/dp/{asin}",
                                         title=title, price=price, in_stock=True)
                if len(items) < 10:
                    break
        return list(out.values())


def make() -> list[Amazon]:
    res = []
    for cc, dom, vat in COUNTRIES:
        res.append(Amazon(
            key=f"amazon_{cc.lower()}", site="Amazon", country=cc, domain=dom, vat=vat,
            ships_fr="oui" if cc == "FR" else
            "en général (articles expédiés par Amazon) — à vérifier sur la fiche",
            returns="Retour 30 j chez Amazon ; garantie A à Z sur les vendeurs tiers.",
            warranty_refurb="Amazon Renewed : garantie Amazon 1 an. Autres reconditionnés : voir le vendeur.",
            notes=[] if cc == "FR" else [
                "Prix converti avec la TVA française (20 %) — Amazon recalcule la TVA à la commande.",
                "Frais de port vers la France non inclus (souvent offerts au-delà d'un seuil)."],
        ))
    return res


def inspect_page(html: str) -> dict:
    """Lit une fiche produit Amazon pour détecter un reconditionné non signalé dans le titre.
    Renvoie {condition, src, note, seller} ; condition = None si rien de suspect."""
    from ..specs import REFURB_RE, USED_RE
    s = soup(html)

    def text(sel):
        return " ".join(e.get_text(" ", strip=True) for e in s.select(sel))

    el = s.select_one("#sellerProfileTriggerId") or s.select_one("#merchantInfoFeature_feature_div .offer-display-feature-text")
    seller = re.sub(r"\s+", " ", el.get_text(" ", strip=True) if el else "").strip()[:80]
    if not seller and re.search(r"Amazon(\.\w+)?\s*$", text("#merchantInfoFeature_feature_div")):
        seller = "Amazon"
    res = dict(condition=None, src="", note="", seller=seller)

    # 1. programme Amazon Renewed / état « d'occasion » dans l'encart d'achat
    # (ces blocs existent vides sur toutes les fiches : il faut qu'ils aient du contenu)
    if any(e.get_text(strip=True) for e in s.select("[id^=renewed]")):
        return dict(res, condition="reconditionné", src="fiche", note="Fiche Amazon Renewed (reconditionné).")
    buybox = text("#usedBuySection, #buyBoxAccordion .a-accordion-active, #tabular-buybox, #qualifiedBuybox")
    if USED_RE.search(buybox) and not REFURB_RE.search(buybox):
        return dict(res, condition="occasion", src="fiche", note="Vendu d'occasion d'après l'encart d'achat.")

    # 2. description du vendeur
    desc = text("#productTitle, #feature-bullets, #productDescription, #productOverview_feature_div, "
                "#prodDetails, #detailBullets_feature_div, #aplus")
    m = REFURB_RE.search(desc)
    if m:
        ctx = desc[max(0, m.start() - 50):m.end() + 50].strip()
        return dict(res, condition="reconditionné", src="fiche", note=f"La fiche le précise : « …{ctx}… »")

    # 3. avis clients (indice plus faible)
    reviews = [e.get_text(" ", strip=True) for e in
               (s.select('[data-hook="review-body"]') or s.select('[data-hook="review"]'))]
    reviews = [re.sub(r"(Brief|Full) content visible, double tap to read (full|brief) content\.?|Read more", "", r).strip()
               for r in reviews]
    hits = [r for r in reviews if REFURB_RE.search(r)]
    if hits:
        m = REFURB_RE.search(hits[0])
        ctx = hits[0][max(0, m.start() - 60):m.end() + 60].strip()
        note = f"{len(hits)} avis client(s) sur {len(reviews)} parlent d'un disque reconditionné : « …{ctx}… »"
        if len(hits) >= 2 or len(hits) / len(reviews) >= 0.25:
            return dict(res, condition="reconditionné", src="avis", note=note)
        return dict(res, note="À vérifier — " + note)   # indice trop faible pour changer l'état
    return res
