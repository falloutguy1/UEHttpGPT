"""Procedural world layout, loot, time of day and weather.

The map is split into three bands that blend into each other:

* West  - "Chernarus": DayZ countryside, villages, military camps, infected.
* Centre - the dead city: toxic surface air, Metro entrances, Fallout vaults.
* East  - "the Zone": anomaly fields, radiation rising toward the reactor.

``WorldLayout`` is deterministic for a seed, so Unreal (``level_builder.py``)
and the headless simulation always agree on where everything is."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from . import items
from .anomalies import AnomalyField
from .config import WORLD
from .survival import Environment

POI_KINDS = {
    # kind: (region, radius_m, base_rads/s, toxic_air, creatures, faction, loot table)
    "village": ("west", 150, 0.0, False, ("infected",), "survivors", "civilian"),
    "town": ("west", 350, 0.0, False, ("infected",), "survivors", "civilian"),
    "military": ("west", 250, 0.0, False, ("infected",), "duty", "military"),
    "farm": ("west", 100, 0.0, False, ("infected", "pseudodog"), None, "farm"),
    "vault": ("centre", 60, 0.0, False, ("feral_ghoul",), "brotherhood", "vault"),
    "metro_station": ("centre", 120, 0.0, False, ("nosalis", "watcher"), "hansa", "metro"),
    "ruins": ("centre", 300, 0.05, True, ("watcher", "demon", "feral_ghoul"), "raiders", "civilian"),
    "industrial": ("east", 300, 0.08, False, ("snork", "bloodsucker"), "freedom", "industrial"),
    "anomaly_field": ("east", 200, 0.3, False, ("pseudodog",), None, "zone"),
    "crater": ("east", 250, 2.0, False, ("feral_ghoul", "deathclaw"), "raiders", "zone"),
    "reactor": ("east", 400, 5.0, False, ("bloodsucker",), "monolith", "zone"),
}

POI_COUNTS = {"village": 10, "town": 4, "military": 3, "farm": 8, "vault": 2,
              "metro_station": 6, "ruins": 5, "industrial": 3, "anomaly_field": 6,
              "crater": 2, "reactor": 1}

NAMES = {
    "west": ["Novaya Sosna", "Vybor", "Gorka", "Staroye", "Pusta", "Kamensk",
             "Zelenogorsk", "Lopatino", "Myshkino", "Pogorevka", "Rogovo",
             "Nadezhdino", "Mogilevka", "Guglovo", "Dubrovka", "Grishino",
             "Kozlovka", "Pulkovo", "Tulga", "Msta", "Shakhovka", "Polana",
             "Orlovets", "Berezino", "Solnichniy"],
    "metro_station": ["Polis", "Paveletskaya", "VDNKh", "Kitay-Gorod", "Park Pobedy",
                      "Rizhskaya", "Prospekt Mira", "Novokuznetskaya", "Oktyabrskaya",
                      "Teatralnaya"],
    "vault": ["Vault 13", "Vault 81", "Vault 101", "Vault 22"],
    "centre": ["Dead City", "Ostankino", "Lubyanka", "Tverskaya", "Arbat",
               "Sparrow Hills"],
    "east": ["Rostok", "Agroprom", "Yantar", "Dark Valley", "Red Forest",
             "Jupiter", "Zaton", "Limansk", "Pripyat", "Army Warehouses",
             "Garbage", "Cordon", "Wild Territory", "Radar"],
}

LOOT_TABLES = {
    # table: [(item_id, weight, max_qty)]
    "civilian": [("canned_beans", 10, 1), ("canned_peaches", 8, 1), ("apple", 6, 1),
                 ("water_bottle", 8, 1), ("rag", 10, 4), ("matches", 6, 10),
                 ("can_opener", 3, 1), ("courier_bag", 3, 1), ("nuka_cola", 4, 1),
                 ("bottle_caps", 8, 25), ("scrap_metal", 6, 3), ("tetracycline", 2, 1),
                 ("filter", 4, 1), ("gas_mask", 1, 1)],
    "farm": [("apple", 10, 3), ("pond_water", 6, 1), ("rag", 6, 3),
             ("fire_axe", 2, 1), ("matches", 5, 5), ("raw_meat", 4, 2)],
    "military": [("mosin", 2, 1), ("m4a1", 1, 1), ("ammo_762x54", 6, 15),
                 ("ammo_556", 5, 30), ("plate_carrier", 1, 1), ("gorka_jacket", 4, 1),
                 ("bandage", 8, 2), ("morphine", 2, 1), ("military_ration", 6, 1),
                 ("hiking_backpack", 2, 1), ("saline", 2, 1), ("filter", 5, 2)],
    "vault": [("stimpak", 6, 2), ("radaway", 4, 1), ("rad_x", 4, 2),
              ("nuka_cola", 8, 2), ("pip_boy", 1, 1), ("laser_pistol", 2, 1),
              ("microfusion_cell", 5, 20), ("bottle_caps", 10, 60), ("radsuit", 1, 1)],
    "metro": [("filter", 10, 2), ("gas_mask", 3, 1), ("ammo_545_mil", 5, 15),
              ("ammo_545_dirty", 10, 30), ("bastard_smg", 2, 1), ("tikhar", 1, 1),
              ("ball_bearings", 6, 40), ("hand_charger", 2, 1), ("mushroom_tea", 6, 1)],
    "industrial": [("scrap_metal", 10, 5), ("ammo_545_dirty", 6, 30), ("ak74", 2, 1),
                   ("medkit_army", 4, 1), ("vodka_cossacks", 6, 1), ("bolt", 8, 20),
                   ("detector_echo", 2, 1)],
    "zone": [("bolt", 10, 30), ("vodka_cossacks", 6, 1), ("medkit_army", 4, 1),
             ("detector_bear", 1, 1), ("seva_suit", 1, 1), ("radaway", 3, 1),
             ("ammo_545_dirty", 6, 30)],
}


def roll_loot(table: str, rng: random.Random, rolls: int = 3,
              ammo_mult: float = 1.0) -> list:
    entries = LOOT_TABLES[table]
    weights = [w for _, w, _ in entries]
    found = []
    for _ in range(rolls):
        item_id, _, max_qty = rng.choices(entries, weights)[0]
        item = items.get(item_id)
        qty = rng.randint(1, max_qty)
        if item.category is items.Category.AMMO:
            qty = int(qty * ammo_mult)
        qty = max(1, min(qty, item.stack))
        condition = round(rng.uniform(0.25, 1.0), 2)
        contaminated = item.category in (items.Category.FOOD, items.Category.DRINK) \
            and rng.random() < 0.1
        found.append(items.make(item_id, qty, condition, contaminated))
    return found


@dataclass
class POI:
    kind: str
    name: str
    x: float
    y: float
    radius_m: float
    rads_per_sec: float
    toxic_air: bool
    creatures: tuple
    faction: str | None
    loot_table: str
    buildings: list = field(default_factory=list)   # (x, y, w, d, h, rot)
    loot_spots: list = field(default_factory=list)  # (x, y)
    underground: bool = False
    anomaly_field: AnomalyField | None = None

    @property
    def region(self) -> str:
        return POI_KINDS[self.kind][0]

    def contains(self, x: float, y: float) -> bool:
        return math.hypot(self.x - x, self.y - y) <= self.radius_m


class WorldLayout:
    def __init__(self, seed: int = 1986):
        self.seed = seed
        self.rng = random.Random(seed)
        self.size_m = WORLD.map_size_km * 1000.0
        self.pois: list[POI] = []
        self.roads: list[tuple] = []
        self._generate()

    # -- Generation -------------------------------------------------------------
    def region_bounds(self, region: str) -> tuple:
        third = self.size_m / 3
        index = {"west": 0, "centre": 1, "east": 2}[region]
        return index * third, (index + 1) * third

    def _generate(self) -> None:
        used_names = set()
        order = sorted(POI_KINDS, key=lambda k: -POI_KINDS[k][1])   # big first
        for kind in order:
            region, radius, rads, toxic, creatures, faction, loot = POI_KINDS[kind]
            for _ in range(POI_COUNTS[kind]):
                x, y = self._free_spot(region, radius)
                if kind == "reactor":
                    x, y = self.size_m * 0.92, self.size_m * 0.85
                name = self._name(kind if kind in NAMES else region, used_names)
                poi = POI(kind, name, x, y, radius, rads, toxic, creatures, faction,
                          loot, underground=kind in ("vault", "metro_station"))
                self._populate(poi)
                self.pois.append(poi)
        self._build_roads()

    def _free_spot(self, region: str, radius: float) -> tuple:
        lo, hi = self.region_bounds(region)
        margin = radius + 200
        for _ in range(200):
            x = self.rng.uniform(max(lo, margin), min(hi, self.size_m - margin))
            y = self.rng.uniform(margin, self.size_m - margin)
            if all(math.hypot(p.x - x, p.y - y) > p.radius_m + radius + 300
                   for p in self.pois):
                return x, y
        return x, y

    def _name(self, pool_key: str, used: set) -> str:
        pool = [n for n in NAMES[pool_key] if n not in used]
        name = self.rng.choice(pool) if pool else f"{pool_key.title()} {len(used)}"
        used.add(name)
        return name

    def _populate(self, poi: POI) -> None:
        rng = self.rng
        density = {"town": 40, "village": 14, "military": 10, "farm": 4,
                   "ruins": 30, "industrial": 12, "metro_station": 3, "vault": 1,
                   "crater": 3, "reactor": 6, "anomaly_field": 0}[poi.kind]
        for _ in range(density):
            r = poi.radius_m * math.sqrt(rng.random()) * 0.9
            a = rng.random() * math.tau
            bx, by = poi.x + r * math.cos(a), poi.y + r * math.sin(a)
            w, d = rng.uniform(8, 20), rng.uniform(8, 16)
            h = {"town": rng.uniform(6, 30), "ruins": rng.uniform(10, 45),
                 "industrial": rng.uniform(8, 25)}.get(poi.kind, rng.uniform(4, 9))
            poi.buildings.append((bx, by, w, d, h, rng.choice((0, 90, 180, 270))
                                  + rng.uniform(-8, 8)))
            poi.loot_spots.append((bx + rng.uniform(-3, 3), by + rng.uniform(-3, 3)))
        if poi.kind in ("anomaly_field", "crater", "reactor"):
            poi.anomaly_field = AnomalyField.generate(
                poi.name, (poi.x, poi.y), poi.radius_m * 0.8, rng,
                density=0.0006 if poi.kind == "anomaly_field" else 0.0002)

    def _build_roads(self) -> None:
        """Connect every settlement to its two nearest neighbours."""
        nodes = [p for p in self.pois if p.kind not in ("anomaly_field", "crater")]
        seen = set()
        for p in nodes:
            nearest = sorted((q for q in nodes if q is not p),
                             key=lambda q: math.hypot(q.x - p.x, q.y - p.y))[:2]
            for q in nearest:
                key = tuple(sorted((id(p), id(q))))
                if key not in seen:
                    seen.add(key)
                    self.roads.append(((p.x, p.y), (q.x, q.y)))

    # -- Queries ----------------------------------------------------------------
    def poi_at(self, x: float, y: float) -> POI | None:
        inside = [p for p in self.pois if p.contains(x, y)]
        return min(inside, key=lambda p: p.radius_m) if inside else None

    def region_at(self, x: float) -> str:
        return ("west", "centre", "east")[min(2, int(x / (self.size_m / 3)))]

    @property
    def dead_city(self) -> tuple:
        """(x, y, radius) of the toxic city core in the middle of the map."""
        return self.size_m / 2, self.size_m / 2, self.size_m * 0.1

    def in_dead_city(self, x: float, y: float) -> bool:
        cx, cy, r = self.dead_city
        return math.hypot(cx - x, cy - y) <= r

    def background_rads(self, x: float, y: float) -> float:
        """Radiation grows eastward and near the reactor even outside POIs."""
        east = max(0.0, (x / self.size_m - 0.55) / 0.45)
        reactor = next((p for p in self.pois if p.kind == "reactor"), None)
        near = 0.0
        if reactor:
            d = math.hypot(reactor.x - x, reactor.y - y)
            near = 1.0 * math.exp(-d / 1000.0)
        return round(0.01 * east + near, 4)

    def environment_at(self, x: float, y: float, clock: "Clock",
                       weather: "Weather", underground: bool = False) -> Environment:
        poi = self.poi_at(x, y)
        rads = self.background_rads(x, y)
        toxic = False
        if poi:
            falloff = 1.0 - math.hypot(poi.x - x, poi.y - y) / poi.radius_m
            rads += poi.rads_per_sec * max(0.0, falloff)
            toxic = poi.toxic_air
        # The dead city's core is toxic on the surface (Metro).
        if self.in_dead_city(x, y) and not underground:
            toxic = True
        if underground:
            toxic, rads = False, rads * 0.1
        if weather.state == "acid_rain" and not underground:
            rads += 0.02   # ~70 rads per hour caught outside
        return Environment(
            air_temp_c=10.0 if underground else weather.temperature(clock),
            raining=weather.state in ("rain", "storm", "acid_rain") and not underground,
            sheltered=underground,
            rads_per_sec=rads,
            toxic_air=toxic,
        )


@dataclass
class Clock:
    seconds: float = 8 * 3600.0          # start at 08:00 on day 1

    def advance(self, dt: float) -> None:
        self.seconds += dt

    @property
    def day(self) -> int:
        return int(self.seconds // 86400) + 1

    @property
    def hour(self) -> float:
        return (self.seconds % 86400) / 3600.0

    @property
    def is_night(self) -> bool:
        return self.hour < 5.5 or self.hour >= 21.0

    @property
    def sun_pitch_deg(self) -> float:
        """For the Unreal directional light: -90 = noon overhead."""
        return -math.sin((self.hour - 6.0) / 24.0 * math.tau) * 80.0

    def __str__(self) -> str:
        h = int(self.hour)
        m = int((self.hour - h) * 60)
        return f"Day {self.day} {h:02d}:{m:02d}"


class Weather:
    STATES = ("clear", "overcast", "fog", "rain", "storm", "acid_rain")
    TRANSITIONS = {
        "clear": {"clear": 6, "overcast": 3, "fog": 1},
        "overcast": {"clear": 2, "overcast": 4, "rain": 3, "fog": 1, "acid_rain": 1},
        "fog": {"fog": 3, "overcast": 3, "clear": 2},
        "rain": {"rain": 4, "overcast": 3, "storm": 2},
        "storm": {"storm": 2, "rain": 4, "overcast": 2},
        "acid_rain": {"acid_rain": 2, "overcast": 4, "rain": 1},
    }

    def __init__(self, rng: random.Random, state: str = "overcast"):
        self.rng = rng
        self.state = state
        self._timer = rng.uniform(1800, 5400)

    def tick(self, dt: float) -> str | None:
        self._timer -= dt
        if self._timer > 0:
            return None
        self._timer = self.rng.uniform(1800, 5400)
        options = self.TRANSITIONS[self.state]
        new = self.rng.choices(list(options), list(options.values()))[0]
        changed = new != self.state
        self.state = new
        return new if changed else None

    def temperature(self, clock: Clock) -> float:
        # Chernarus autumn: ~4C at night, ~16C mid-afternoon.
        daily = 10.0 + 6.0 * math.sin((clock.hour - 9.0) / 24.0 * math.tau)
        return daily + {"clear": 1.0, "overcast": 0.0, "fog": -1.0, "rain": -3.0,
                        "storm": -5.0, "acid_rain": -2.0}[self.state]

    @property
    def fog_density(self) -> float:
        return {"clear": 0.01, "overcast": 0.02, "fog": 0.2, "rain": 0.05,
                "storm": 0.08, "acid_rain": 0.06}[self.state]
