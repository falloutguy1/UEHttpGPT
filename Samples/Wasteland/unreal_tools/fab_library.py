"""Uses the Fab assets you've added to your project.

Fab has no public API for your library, so first add the assets to the project:
Fab plugin (Window -> Fab) or fab.com -> My Library -> Add to Project. They
land under /Game/Fab (Megascans under /Game/Fab/Megascans; older Quixel Bridge
imports under /Game/Megascans; marketplace packs under /Game/<PackName>).

This module scans those folders, sorts every mesh and material into a game
role by name (building, rock, tree, wreck, barrel, zombie, ...), and the level
builder places them instead of placeholder cubes. Anything it guesses wrong
can be pinned in ``fab_overrides.json`` next to ``setup_wasteland.py``:

    {"building.town": ["/Game/Fab/Soviet_Apartment/SM_Khrushchevka"],
     "creature.infected": ["/Game/Fab/Zombie_Pack/SK_Zombie_01"],
     "ignore": ["/Game/Fab/Some_Pack/SM_Unwanted"]}
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOTS = ("/Game/Fab", "/Game/Megascans", "/Game")
SKIP_ROOTS = ("/Game/Wasteland", "/Game/Developers", "/Game/Collections",
              "/Game/__ExternalActors__", "/Game/__ExternalObjects__")
OVERRIDES = Path(__file__).resolve().parents[1] / "fab_overrides.json"

# role -> keywords. First match wins, so specific roles come first.
MESH_ROLES = (
    ("building.metro", ("metro", "subway", "platform", "tunnel", "station", "turnstile")),
    ("building.vault", ("vault", "bunker", "blastdoor", "hatch", "shelter")),
    ("building.industrial", ("factory", "warehouse", "hangar", "silo", "tank", "industrial",
                             "pipe", "chimney", "container", "crane", "reactor", "cooling")),
    ("building.military", ("military", "barrack", "checkpoint", "watchtower", "sandbag",
                           "hesco", "outpost", "army")),
    ("building.ruins", ("ruin", "destroyed", "collapsed", "damaged", "abandoned", "broken")),
    ("building.village", ("house", "cottage", "barn", "shed", "cabin", "hut", "shack",
                          "village", "farm", "wooden")),
    ("building.town", ("building", "apartment", "khrushchevka", "panel", "facade",
                       "shop", "store", "church", "office", "hospital", "school", "garage",
                       "kiosk", "brutalist", "soviet")),
    ("vehicle", ("car", "truck", "bus", "van", "lada", "uaz", "btr", "bmp", "tractor",
                 "vehicle", "wreck", "train", "wagon", "railcar", "trolley")),
    ("container", ("barrel", "crate", "box", "locker", "cabinet", "chest", "safe", "drum",
                   "fridge", "suitcase", "bag")),
    ("furniture", ("chair", "table", "bed", "sofa", "couch", "shelf", "desk", "stool",
                   "mattress", "wardrobe", "bench")),
    ("fence", ("fence", "wall", "barrier", "gate", "railing", "barbed", "concrete_block")),
    ("utility", ("pole", "lamp", "streetlight", "powerline", "pylon", "sign", "hydrant",
                 "antenna", "transformer", "generator")),
    ("debris", ("debris", "rubble", "trash", "garbage", "junk", "pile", "scrap", "tire",
                "brick", "plank", "pallet", "cinder", "leaves")),
    ("rock", ("rock", "boulder", "stone", "cliff", "pebble", "slab")),
    ("tree", ("tree", "birch", "pine", "spruce", "oak", "trunk", "stump", "log", "dead_tree")),
    ("foliage", ("bush", "shrub", "grass", "fern", "weed", "plant", "nettle", "moss")),
    ("weapon", ("rifle", "ak", "pistol", "gun", "shotgun", "smg", "mosin", "weapon", "axe")),
    ("item", ("can", "bottle", "canteen", "medkit", "bandage", "syringe", "gasmask",
              "gas_mask", "filter", "ammo", "radio", "battery", "detector")),
)

CREATURE_ROLES = (
    ("creature.feral_ghoul", ("ghoul",)),
    ("creature.deathclaw", ("deathclaw", "claw", "horned")),
    ("creature.bloodsucker", ("bloodsucker", "tentacle", "vampire")),
    ("creature.pseudodog", ("dog", "hound")),
    ("creature.watcher", ("wolf", "watcher")),
    ("creature.snork", ("snork",)),
    ("creature.nosalis", ("nosalis", "rat", "mole")),
    ("creature.librarian", ("librarian", "ape", "gorilla", "yeti")),
    ("creature.demon", ("demon", "bat", "winged", "gargoyle")),
    ("creature.infected", ("zombie", "infected", "undead", "walker", "mutant", "monster",
                           "creature")),
    ("npc", ("soldier", "stalker", "survivor", "character", "man", "woman", "npc", "human",
             "bandit", "mannequin", "metahuman")),
)

MATERIAL_ROLES = (
    ("Asphalt", ("asphalt", "road", "tarmac")),
    ("Tiles", ("tile", "ceramic", "mosaic")),
    ("Brick", ("brick",)),
    ("RustMetal", ("rust", "corroded", "oxid")),
    ("MetalPlate", ("metal", "steel", "iron", "plate", "aluminium", "aluminum")),
    ("PaintedMetal", ("painted",)),
    ("WoodPlanks", ("wood", "plank", "timber")),
    ("Mud", ("mud", "swamp", "wet_soil")),
    ("BurntGround", ("burnt", "burned", "ash", "scorched", "charred")),
    ("Gravel", ("gravel", "pebbles", "ballast")),
    ("ForestGround", ("forest", "leaves", "moss", "soil", "dirt", "ground")),
    ("Grass", ("grass", "meadow", "lawn")),
    ("ConcreteDirty", ("dirty_concrete", "concrete_dirty", "stained", "grimy")),
    ("Concrete", ("concrete", "cement", "plaster", "stucco")),
)

# POI kind -> building roles to draw from, best first.
POI_BUILDINGS = {
    "village": ("building.village", "building.town"),
    "farm": ("building.village",),
    "town": ("building.town", "building.village"),
    "military": ("building.military", "building.industrial", "building.town"),
    "ruins": ("building.ruins", "building.town"),
    "industrial": ("building.industrial", "building.ruins", "building.town"),
    "reactor": ("building.industrial",),
    "metro_station": ("building.metro", "building.town"),
    "vault": ("building.vault", "building.industrial"),
    "crater": ("debris", "rock"),
}

_NOISE = {"sm", "sk", "s", "mi", "m", "mat", "t", "lod", "lod0", "lod1", "var", "a", "b",
          "c", "01", "02", "03", "high", "low", "mid", "inst", "instance", "bp"}


def tokens(name: str) -> list:
    """'SM_OldConcrete_Barrier_uhrmbd_LOD0' -> ['old', 'concrete', 'barrier', ...]"""
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    parts = re.split(r"[^A-Za-z0-9]+", name.lower())
    return [p for p in parts if p and p not in _NOISE and not p.isdigit()]


def _match(name: str, path: str, roles) -> str | None:
    words = tokens(name) + tokens(path.rsplit("/", 1)[0].rsplit("/", 1)[-1])
    joined = "_".join(words)
    for role, keywords in roles:
        for kw in keywords:
            if kw in words or ("_" in kw and kw in joined) or \
                    any(w.startswith(kw) and len(kw) > 3 for w in words):
                return role
    return None


def classify(name: str, path: str, asset_class: str) -> str | None:
    """Role for one asset, or None if we can't tell."""
    if asset_class == "SkeletalMesh":
        return _match(name, path, CREATURE_ROLES)
    if asset_class == "StaticMesh":
        return _match(name, path, MESH_ROLES)
    if asset_class in ("MaterialInstanceConstant", "Material"):
        role = _match(name, path, MATERIAL_ROLES)
        return f"material.{role}" if role else None
    return None


@dataclass
class FabLibrary:
    by_role: dict = field(default_factory=dict)       # role -> [object path]
    unclassified: list = field(default_factory=list)
    rng: random.Random = field(default_factory=lambda: random.Random(1986))
    _loaded: dict = field(default_factory=dict)

    # -- Scanning (needs the editor) ----------------------------------------------------
    @classmethod
    def scan(cls, roots: tuple = DEFAULT_ROOTS, seed: int = 1986) -> "FabLibrary":
        import unreal
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        lib = cls(rng=random.Random(seed))
        seen = set()
        for root in roots:
            for data in registry.get_assets_by_path(root, recursive=True):
                package = str(data.package_name)
                if package in seen or package.startswith(SKIP_ROOTS):
                    continue
                seen.add(package)
                asset_class = str(data.asset_class_path.asset_name)
                name = str(data.asset_name)
                if re.search(r"_LOD[1-9]$", name, re.I):
                    continue
                lib.add(f"{package}.{name}", name, asset_class)
        lib.apply_overrides()
        unreal.log(f"Fab library: {lib.summary()}")
        return lib

    def add(self, object_path: str, name: str, asset_class: str) -> None:
        role = classify(name, object_path, asset_class)
        if role:
            self.by_role.setdefault(role, []).append(object_path)
        elif asset_class in ("StaticMesh", "SkeletalMesh"):
            self.unclassified.append(object_path)

    def apply_overrides(self, path: Path = OVERRIDES) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text())
        ignored = set(data.pop("ignore", []))
        for role, assets in data.items():
            self.by_role[role] = [a if "." in a.rsplit("/", 1)[-1] else f"{a}.{a.rsplit('/', 1)[-1]}"
                                  for a in assets]
        for role in self.by_role:
            self.by_role[role] = [a for a in self.by_role[role]
                                  if a not in ignored and a.split(".")[0] not in ignored]

    def summary(self) -> str:
        counts = ", ".join(f"{r}={len(a)}" for r, a in sorted(self.by_role.items()))
        return f"{counts}; unclassified={len(self.unclassified)}"

    def write_report(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"roles": self.by_role,
                                    "unclassified": self.unclassified}, indent=2))

    # -- Picking --------------------------------------------------------------------------
    def has(self, role: str) -> bool:
        return bool(self.by_role.get(role))

    def pick_path(self, *roles: str) -> str | None:
        for role in roles:
            options = self.by_role.get(role)
            if options:
                return self.rng.choice(options)
        return None

    def pick(self, *roles: str):
        """Loaded asset for the first role that has any, or None."""
        path = self.pick_path(*roles)
        if path is None:
            return None
        if path not in self._loaded:
            import unreal
            self._loaded[path] = unreal.load_asset(path)
        return self._loaded[path]

    def building_for(self, poi_kind: str):
        return self.pick(*POI_BUILDINGS.get(poi_kind, ("building.town",)))

    def material(self, slot: str):
        return self.pick(f"material.{slot}")
