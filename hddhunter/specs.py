"""Déduit les caractéristiques d'un disque à partir de son titre / sa description.

Les fiches des boutiques ne donnent pas toujours le cache ou la vitesse : on lit
d'abord le texte, puis on complète avec les caractéristiques connues de la gamme
(ex. Exos X22 = 512 Mo). Une valeur complétée est marquée « estimée ».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# Classes de disques
SERVER = "serveur"          # Exos, Ultrastar, Toshiba MG, WD Gold
NAS_PRO = "nas_pro"         # IronWolf Pro, WD Red Pro, N300, Synology HAT
OTHER = "autre"             # surveillance, bureau, SMR, externes… (ignorés)

# (regex sur le texte, marque, gamme, classe, cache par défaut ou fonction(capacité))
FAMILIES: list[tuple[str, str, str, str, object]] = [
    (r"exos\s*x\s?16\b", "Seagate", "Exos X16", SERVER, 256),
    (r"exos\s*x\s?18\b", "Seagate", "Exos X18", SERVER, 256),
    (r"exos\s*x\s?20\b", "Seagate", "Exos X20", SERVER, 256),
    (r"exos\s*x\s?22\b", "Seagate", "Exos X22", SERVER, 512),
    (r"exos\s*x\s?24\b", "Seagate", "Exos X24", SERVER, 512),
    (r"exos\s*x\s?(26|28|30|32)\b", "Seagate", "Exos X", SERVER, 512),
    (r"exos\s*m\b", "Seagate", "Exos M", SERVER, 512),
    (r"\bexos\b", "Seagate", "Exos", SERVER, lambda c: 512 if c and c >= 22 else 256),
    (r"ironwolf\s*pro", "Seagate", "IronWolf Pro", NAS_PRO, lambda c: 512 if c and c >= 22 else 256),
    (r"ultrastar.*\bhc\s?6\d0\b|\bhc\s?6\d0\b", "WD", "Ultrastar SMR", OTHER, 512),
    (r"ultrastar.*\bhc\s?5[5-9]0\b|\bdc\s?hc\s?5[5-9]0\b", "WD", "Ultrastar DC", SERVER, 512),
    (r"ultrastar", "WD", "Ultrastar", SERVER, 512),
    (r"\bwd\s*gold\b|\bwd\d{3}kryz\b|\bgold\b.*western|western.*\bgold\b", "WD", "WD Gold", SERVER, 512),
    (r"red\s*pro", "WD", "WD Red Pro", NAS_PRO, 512),
    (r"\bmg0?7", "Toshiba", "Toshiba MG07", SERVER, 256),
    (r"\bmg0?(8|9)|\bmg1[0-2]", "Toshiba", "Toshiba MG", SERVER, 512),
    (r"toshiba.*enterprise|enterprise.*toshiba", "Toshiba", "Toshiba MG", SERVER, 512),
    (r"\bn300\b", "Toshiba", "Toshiba N300", NAS_PRO, 512),
    (r"\bhat5\d{3}", "Synology", "Synology HAT5300", NAS_PRO, 512),
    (r"\bhat3\d{3}", "Synology", "Synology HAT3300", NAS_PRO, 512),
    (r"skyhawk|purple|surveillance|barracuda|\bblue\b|ironwolf(?!\s*pro)|red plus|\bwd\s*red\b|\bs300\b|\bp300\b|\bx300\b", "", "", OTHER, None),
]

# Numéros de modèle -> gamme (quand le titre ne cite pas la gamme)
MODEL_RE = [
    (r"\bST(\d{2})000NM\w*", "Seagate", "Exos", SERVER),
    (r"\bST(\d{2})000N[TE]\w*", "Seagate", "IronWolf Pro", NAS_PRO),
    (r"\bST(\d{2})000(VE|VN|DM|VX)\w*", "Seagate", "", OTHER),
    (r"\bWU[HS]72(\d{2})\d{2}\w*", "WD", "Ultrastar DC", SERVER),
    (r"\bWD(\d{2,3})[0-9]?KRYZ\b", "WD", "WD Gold", SERVER),
    (r"\bWD(\d{2,3})[0-9]?KFGX\b", "WD", "WD Red Pro", NAS_PRO),
    (r"\bMG\d{2}[AS][A-Z]A(\d{2})T\w*", "Toshiba", "Toshiba MG", SERVER),
]

EXTERNAL_RE = re.compile(
    r"extern|expansion|desktop[- ]?festplatte|my ?book|elements|\busb\b|portable|tragbar|"
    r"\bssd\b|\bnvme\b|boîtier|gehäuse|enclosure|\bnas\s+\d-baies|\bds\d{3,4}\+?\b|"
    r"lot de|pack de|\b\d\s?x\s?\d{2}\s?(to|tb)\b|\b\d+er[- ]?pack",
    re.I,
)

REFURB_RE = re.compile(
    r"reconditionn|remis\s+à\s+neuf|recertif|refurb|renewed|generalüberholt|generaluberholt|"
    r"überholt|ricondizionat|rigenerat|reacondicionad|reconstruido|gereviseerd|gerecertificeerd|"
    r"renouvel|renovad|certifi[ée]e? en usine|certificato in fabbrica|recertificado|werksüberholt|"
    r"werkzertifiziert|seconda vita|\bb-ware\b",
    re.I,
)

# Références Seagate vendues (presque) uniquement en « factory recertified » : modèles
# hyperscale / SED en …NM00xC (ST16000NM002C, ST22000NM000C, ST24000NM000C, ST26000NM000C,
# ST28000NM000C…). Constaté sur Amazon : même référence annoncée « Refurbished » ailleurs.
RECERT_SKU_RE = re.compile(r"\bST\d{2}000NM00\dC\b", re.I)
USED_RE = re.compile(r"\boccasion\b|\bused\b|gebraucht|\busato\b|\busado\b|\btweedehands\b|\bpre-?owned\b", re.I)


@dataclass
class Spec:
    brand: str = ""
    family: str = ""
    klass: str = OTHER
    model_no: str = ""
    capacity_tb: float | None = None
    rpm: int | None = None
    cache_mb: int | None = None
    cache_estimated: bool = False
    interface: str = "SATA"
    condition: str = "neuf"     # neuf / reconditionné / occasion
    condition_src: str = "titre"  # titre | référence | fiche | avis : d'où vient l'état
    condition_note: str = ""
    external: bool = False

    def dict(self):
        return asdict(self)


def _capacity(text: str) -> float | None:
    vals = []
    for m in re.finditer(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s?-?\s?(tb|to|tbyte|terabyte|téraoctets?)\b", text, re.I):
        v = float(m.group(1).replace(",", "."))
        if 1 <= v <= 40:
            vals.append(v)
    return max(vals) if vals else None


def _cache(text: str) -> int | None:
    for m in re.finditer(r"(?<!\d)(64|128|256|512|1024)\s?(mo|mb|mib|mbyte)\b", text, re.I):
        return int(m.group(1))
    return None


def _rpm(text: str) -> int | None:
    m = re.search(r"(?<![\d.])(7[ .]?200|5[ .]?400|5[ .]?900|5[ .]?640|10[ .]?000|15[ .]?000)\s?"
                  r"(rpm|tr\.?/?\s?min|tpm|u\.?/?\s?min|t/min|giri|rpm|min-1|/min)", text, re.I)
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def parse(title: str, extra: str = "") -> Spec:
    text = f"{title} {extra}"
    low = text.lower()
    s = Spec()
    s.external = bool(EXTERNAL_RE.search(title))

    # numéro de modèle
    for rx, brand, fam, klass in MODEL_RE:
        m = re.search(rx, text, re.I)
        if m:
            s.model_no = m.group(0).upper()
            s.brand, s.family, s.klass = brand, fam, klass
            n = int(m.group(1))
            cap = n / 10 if n >= 100 else n          # WD161KRYZ -> 16.1 -> 16
            s.capacity_tb = float(int(cap)) if n >= 100 else float(n)
            break

    cap = _capacity(text)
    if cap:
        s.capacity_tb = cap

    # gamme (prioritaire sur la déduction par numéro de modèle)
    for rx, brand, fam, klass, cache in FAMILIES:
        if re.search(rx, low, re.I):
            if klass == OTHER and s.klass == SERVER and fam == "":
                continue  # mot générique (« blue »…) dans un titre de disque serveur
            s.brand = brand or s.brand
            s.family = fam or s.family
            s.klass = klass
            c = cache(s.capacity_tb) if callable(cache) else cache
            explicit = _cache(text)
            if explicit:
                s.cache_mb = explicit
            elif c:
                s.cache_mb, s.cache_estimated = c, True
            break
    else:
        s.cache_mb = _cache(text)

    if not s.brand:
        for b in ("Seagate", "Toshiba", "Western Digital", "WD", "Synology", "HGST"):
            if b.lower() in low:
                s.brand = "WD" if b in ("Western Digital", "HGST") else b
                break

    s.rpm = _rpm(text)
    if s.rpm is None and s.klass in (SERVER, NAS_PRO):
        s.rpm = 7200  # toutes ces gammes tournent à 7200 tr/min

    if re.search(r"\bsas\b|\b12\s?gb/?s\b|sas\s?12", low) and "sata" not in low.replace("sas/sata", ""):
        s.interface = "SAS"

    if REFURB_RE.search(text):
        s.condition = "reconditionné"
    elif USED_RE.search(text):
        s.condition = "occasion"
    elif (m := RECERT_SKU_RE.search(text)):
        s.condition, s.condition_src = "reconditionné", "référence"
        s.condition_note = (f"Le titre ne le dit pas, mais la référence {m.group(0).upper()} est vendue "
                            "comme « factory recertified » Seagate.")

    if s.external:
        s.klass = OTHER
    return s
