import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from hddhunter.specs import parse, SERVER, NAS_PRO, OTHER  # noqa: E402

CASES = [
    # titre, attendu (sous-ensemble)
    ("Seagate Exos X22 22TB Interne Festplatte – Factory Recertified – 3.5 Zoll SATA 6 Gbits/s",
     dict(family="Exos X22", capacity_tb=22, cache_mb=512, rpm=7200, condition="reconditionné", klass=SERVER)),
    ("Seagate Exos 28TB Interne Server Festplatte ST28000NM000C 3,5 Zoll HDD SATA 6Gb/s 7200RPM",
     dict(capacity_tb=28, rpm=7200, klass=SERVER, cache_mb=512, condition="reconditionné", condition_src="référence")),
    ("Seagate Exos X18 Enterprise, 18TB HDD, CMR 3.5\", Hyperscale SATA 6GB/s, 7.200 U/min, 512e",
     dict(family="Exos X18", capacity_tb=18, cache_mb=256, rpm=7200)),
    ("Seagate IronWolf Pro 16 To (ST16000NT001)", dict(klass=NAS_PRO, capacity_tb=16, cache_mb=256)),
    ("Western Digital Ultrastar DC HC570 22 To (0F48155)", dict(klass=SERVER, capacity_tb=22, cache_mb=512)),
    ("Western Digital WD Gold 20 To (WD203KRYZ)", dict(klass=SERVER, capacity_tb=20, family="WD Gold")),
    ("Seagate SkyHawk AI 24 To (ST24000VE002)", dict(klass=OTHER)),
    ("Seagate 24TB Expansion Desktop-Festplatte | MicroB to USB-C (STNP24000400)", dict(klass=OTHER)),
    ("Seagate Exos 26 TB Reconditionné, Disque dur", dict(condition="reconditionné", capacity_tb=26, cache_mb=512)),
    ("Seagate Exos X24 disque dur 24 To 7200 tr/min 512 Mo 3.5\" SATA",
     dict(cache_mb=512, cache_estimated=False, rpm=7200, capacity_tb=24)),
    ("Toshiba MG10 20 To (MG10ACA20TE)", dict(klass=SERVER, capacity_tb=20, cache_mb=512)),
    ("Seagate Exos X20 20TB SAS 12Gb/s ST20000NM002D", dict(interface="SAS")),
    ("Seagate Exos X20 20TB SATA ST20000NM007D", dict(interface="SATA")),
    ("WD Ultrastar DC HC620 14TB SMR", dict(klass=OTHER)),
    ("Seagate Exos X16 16TB (Generalüberholt)", dict(condition="reconditionné", capacity_tb=16)),
    ("Exos ST26000NM000C Internal Hard Drive 26TB 3.5\" SATA3 HDD 7200RPM 512MB Cache",
     dict(condition="reconditionné", condition_src="référence", capacity_tb=26, cache_mb=512)),
    ("Seagate Exos X16 Enterprise Class ST16000NM002C Disque dur interne HDD 3,5\" 16 To",
     dict(condition="reconditionné", condition_src="référence")),
    ("Seagate Exos X24 24 To (ST24000NM002H)", dict(condition="neuf", condition_src="titre")),
    ("Seagate Exos ST26000NM000C 26 To (certifié en usine)", dict(condition="reconditionné", condition_src="titre")),
]


def test_cases():
    bad = []
    for title, exp in CASES:
        s = parse(title).dict()
        for k, v in exp.items():
            if s[k] != v:
                bad.append(f"{title[:50]!r}: {k}={s[k]!r} (attendu {v!r})")
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    test_cases()
    print("OK", len(CASES), "cas")
