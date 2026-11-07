from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

FR_VAT = 0.20

LEGAL = ("Droit de rétractation 14 j (achat en ligne UE) + garantie légale de conformité 2 ans "
         "(neuf) auprès du vendeur.")


@dataclass
class RawOffer:
    pid: str                 # identifiant produit dans la boutique
    url: str
    title: str
    price: float | None      # prix affiché par la boutique (TVA de son pays)
    extra: str = ""          # description courte, pour lire les caractéristiques
    in_stock: bool | None = None
    seller: str = ""


@dataclass
class Source:
    key: str
    site: str                # nom affiché (ex. « Amazon »)
    country: str             # code pays de la boutique (FR, DE…)
    domain: str
    vat: float = FR_VAT      # TVA incluse dans les prix affichés
    ships_fr: str = "oui"    # « oui » ou texte d'avertissement
    returns: str = LEGAL
    warranty_new: str = "Garantie constructeur 5 ans (Exos, Ultrastar, WD Gold, Toshiba MG)."
    warranty_refurb: str = "Garantie du vendeur — durée à vérifier sur la fiche."
    notes: list[str] = field(default_factory=list)

    def scan(self, fetcher, cfg) -> list[RawOffer]:  # pragma: no cover
        raise NotImplementedError

    def price_fr(self, price: float | None) -> float | None:
        """Prix estimé livré en France : en vente à distance UE, la TVA française
        (20 %) remplace celle du pays de la boutique (règles OSS 2021)."""
        if price is None:
            return None
        return round(price / (1 + self.vat) * (1 + FR_VAT), 2)


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def euro(text: str | None) -> float | None:
    """« 1.149,00 € », « 999€95 », « € 1.266,00 », « 1,149.00 » -> float."""
    if not text:
        return None
    t = text.replace("\xa0", " ").replace(" ", " ")
    m = re.search(r"(\d[\d .,]*)\s*€\s*(\d{2})\b", t)          # 999€95 (centimes en exposant)
    if m and not re.search(r"[.,]\d{2}\s*€", t):
        return float(re.sub(r"[ .,]", "", m.group(1)) + "." + m.group(2))
    m = re.search(r"\d[\d .,]*", t)
    if not m:
        return None
    s = m.group(0).strip().replace(" ", "")
    if re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{1,2}$", s):
        s = s.replace(",", "")
    else:
        s = s.replace(".", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def jsonld_offer(html: str) -> tuple[float | None, bool | None]:
    """Lit le prix et le stock dans les données structurées schema.org d'une fiche."""
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
                continue
            if not isinstance(d, dict):
                continue
            if d.get("@type") in ("Offer", "AggregateOffer") and (d.get("price") or d.get("lowPrice")):
                av = str(d.get("availability", ""))
                stock = None if not av else ("InStock" in av or "LimitedAvailability" in av)
                return float(str(d.get("price") or d.get("lowPrice")).replace(",", ".")), stock
            for v in d.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return None, None
