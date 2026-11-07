from . import amazon, shops_fr

ALL = shops_fr.make() + amazon.make()
BY_KEY = {s.key: s for s in ALL}
