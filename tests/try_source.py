"""Usage : python tests/try_source.py ldlc amazon_de …  — scanne sans rien enregistrer."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from hddhunter import db, specs
from hddhunter.fetch import Fetcher
from hddhunter.sources import BY_KEY

cfg = db.load_config()
f = Fetcher(min_delay=float(sys.argv[1]) if sys.argv[1].replace('.', '').isdigit() else 6)
for key in [a for a in sys.argv[1:] if a in BY_KEY]:
    src = BY_KEY[key]
    try:
        raws = src.scan(f, cfg)
    except Exception as e:
        print(f"## {key}: {type(e).__name__} {e}"); continue
    kept = []
    for r in raws:
        s = specs.parse(r.title, r.extra)
        if s.klass in ("serveur", "nas_pro") and s.capacity_tb and 10 <= s.capacity_tb <= 32:
            o = dict(s.dict(), price_fr=src.price_fr(r.price), in_stock=None if r.in_stock is None else int(r.in_stock))
            kept.append((db.matches(o, cfg), o, r))
    print(f"## {key}: {len(raws)} lus, {len(kept)} disques serveur/NAS pro, {sum(k[0] for k in kept)} correspondent")
    for m, o, r in sorted(kept, key=lambda k: (k[1]['price_fr'] or 9e9)):
        print(f"  {'✔' if m else ' '} {o['price_fr'] or 0:7.2f}€ {o['capacity_tb']:>4g}To {o['cache_mb'] or '?':>4}{'~' if o['cache_estimated'] else ' '} {o['rpm'] or '?'} {o['interface']:4} {o['condition']:13} stock={o['in_stock']} | {r.title[:70]}")
print("requêtes:", f.count)
