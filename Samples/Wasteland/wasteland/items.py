"""Item catalog. Rows here are exported to an Unreal DataTable (see
``datatables.py``), and the ``mesh_hint`` column tells the asset pipeline which
free asset source to fill each item from."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class Category(str, Enum):
    FOOD = "food"
    DRINK = "drink"
    MEDICAL = "medical"
    WEAPON = "weapon"
    AMMO = "ammo"
    CLOTHING = "clothing"
    CONTAINER = "container"
    TOOL = "tool"
    FILTER = "filter"
    ARTIFACT = "artifact"
    CURRENCY = "currency"
    JUNK = "junk"


@dataclass(frozen=True)
class ItemDef:
    id: str
    name: str
    category: Category
    weight_kg: float
    value: int                      # base value in bottle caps
    size: tuple = (1, 1)            # inventory grid cells (w, h), DayZ-style
    stack: int = 1
    origin: str = "dayz"            # which franchise flavor it comes from
    effects: dict = field(default_factory=dict)
    mesh_hint: str = ""             # search phrase for the asset pipeline

    @property
    def cells(self) -> int:
        return self.size[0] * self.size[1]


@dataclass
class ItemStack:
    """A concrete item in the world. Condition follows DayZ's five states."""
    item: ItemDef
    quantity: int = 1
    condition: float = 1.0          # 1.0 pristine .. 0.0 ruined
    contaminated: bool = False      # dirty water, raw meat, irradiated cans

    @property
    def condition_label(self) -> str:
        c = self.condition
        if c <= 0.0:
            return "Ruined"
        if c < 0.3:
            return "Badly Damaged"
        if c < 0.5:
            return "Damaged"
        if c < 0.7:
            return "Worn"
        return "Pristine"

    @property
    def weight(self) -> float:
        return self.item.weight_kg * self.quantity

    def split(self, amount: int) -> "ItemStack":
        if not 0 < amount < self.quantity:
            raise ValueError("invalid split amount")
        self.quantity -= amount
        return replace(self, quantity=amount)


def _i(*args, **kwargs) -> ItemDef:
    return ItemDef(*args, **kwargs)


C = Category
ITEMS = {i.id: i for i in (
    # --- DayZ survival staples ------------------------------------------------
    _i("canned_beans", "Baked Beans", C.FOOD, 0.4, 8, (1, 2), origin="dayz",
       effects={"energy": 25, "water": -2}, mesh_hint="tin can"),
    _i("canned_peaches", "Canned Peaches", C.FOOD, 0.4, 10, (1, 2),
       effects={"energy": 18, "water": 8}, mesh_hint="tin can"),
    _i("apple", "Apple", C.FOOD, 0.2, 3, effects={"energy": 6, "water": 5},
       mesh_hint="apple"),
    _i("raw_meat", "Raw Steak", C.FOOD, 0.3, 4,
       effects={"energy": 8, "disease": "salmonella", "disease_chance": 0.6},
       mesh_hint="meat"),
    _i("cooked_meat", "Cooked Steak", C.FOOD, 0.25, 12,
       effects={"energy": 30}, mesh_hint="meat"),
    _i("water_bottle", "Water Bottle", C.DRINK, 1.0, 5, (1, 2),
       effects={"water": 40}, mesh_hint="plastic bottle"),
    _i("pond_water", "Pond Water (canteen)", C.DRINK, 1.0, 1, (1, 2),
       effects={"water": 30, "disease": "cholera", "disease_chance": 0.5},
       mesh_hint="canteen"),
    _i("rag", "Rags", C.MEDICAL, 0.05, 2, stack=6,
       effects={"stop_bleed": 1, "infection_chance": 0.15}, mesh_hint="cloth rag"),
    _i("bandage", "Bandage", C.MEDICAL, 0.05, 6, stack=4,
       effects={"stop_bleed": 1}, mesh_hint="bandage"),
    _i("saline", "Saline Bag", C.MEDICAL, 0.3, 25, (1, 2),
       effects={"blood": 1000}, mesh_hint="iv bag"),
    _i("tetracycline", "Tetracycline", C.MEDICAL, 0.05, 20,
       effects={"cure": ["cholera", "influenza", "wound_infection"]},
       mesh_hint="pill bottle"),
    _i("charcoal", "Charcoal Tablets", C.MEDICAL, 0.05, 12,
       effects={"cure": ["salmonella", "food_poisoning"]}, mesh_hint="pill box"),
    _i("morphine", "Morphine", C.MEDICAL, 0.05, 35,
       effects={"shock": -60, "fix_limbs": True}, mesh_hint="syringe"),
    _i("mosin", "Mosin 91/30", C.WEAPON, 4.0, 180, (6, 2), origin="dayz",
       effects={"damage": 95, "dtype": "ballistic", "accuracy": 0.9,
                "ammo": "ammo_762x54", "ap_cost": 35, "noise_m": 900},
       mesh_hint="bolt action rifle"),
    _i("m4a1", "M4-A1", C.WEAPON, 3.1, 450, (6, 3),
       effects={"damage": 38, "dtype": "ballistic", "accuracy": 0.8,
                "ammo": "ammo_556", "ap_cost": 20, "noise_m": 600},
       mesh_hint="assault rifle"),
    _i("fire_axe", "Fire Axe", C.WEAPON, 2.5, 60, (2, 5),
       effects={"damage": 45, "dtype": "melee", "accuracy": 0.95, "ap_cost": 25,
                "noise_m": 10}, mesh_hint="axe"),
    _i("ammo_762x54", "7.62x54R Rounds", C.AMMO, 0.025, 3, stack=20,
       mesh_hint="rifle cartridge"),
    _i("ammo_556", "5.56x45 Rounds", C.AMMO, 0.012, 2, stack=60,
       mesh_hint="rifle cartridge"),
    _i("hiking_backpack", "Hiking Backpack", C.CONTAINER, 1.5, 70, (5, 5),
       effects={"capacity_cells": 56}, mesh_hint="backpack"),
    _i("courier_bag", "Courier Bag", C.CONTAINER, 0.6, 20, (4, 4),
       effects={"capacity_cells": 20}, mesh_hint="shoulder bag"),
    _i("gorka_jacket", "Gorka Jacket", C.CLOTHING, 1.2, 60, (4, 4),
       effects={"insulation": 0.6, "waterproof": 0.5, "capacity_cells": 12,
                "slot": "top", "armor": {"melee": 5}}, mesh_hint="military jacket"),
    _i("plate_carrier", "Plate Carrier", C.CLOTHING, 6.0, 300, (5, 5),
       effects={"slot": "vest", "armor": {"ballistic": 40, "melee": 20},
                "capacity_cells": 0}, mesh_hint="plate carrier vest"),
    _i("matches", "Matches", C.TOOL, 0.05, 2, stack=20,
       effects={"fire_starter": True}, mesh_hint="matchbox"),
    _i("can_opener", "Can Opener", C.TOOL, 0.1, 5, mesh_hint="can opener"),

    # --- Fallout ----------------------------------------------------------------
    _i("bottle_caps", "Bottle Caps", C.CURRENCY, 0.0, 1, stack=100000,
       origin="fallout", mesh_hint="bottle cap"),
    _i("nuka_cola", "Nuka-Cola", C.DRINK, 0.5, 20, (1, 2), origin="fallout",
       effects={"water": 25, "energy": 5, "rads": 5}, mesh_hint="glass soda bottle"),
    _i("stimpak", "Stimpak", C.MEDICAL, 0.1, 50, origin="fallout",
       effects={"heal": 40, "fix_limbs": True}, mesh_hint="syringe"),
    _i("radaway", "RadAway", C.MEDICAL, 0.1, 80, origin="fallout",
       effects={"rads": -300}, mesh_hint="iv bag"),
    _i("rad_x", "Rad-X", C.MEDICAL, 0.05, 40, origin="fallout",
       effects={"rad_resist_buff": 0.5, "buff_sec": 600}, mesh_hint="pill bottle"),
    _i("pip_boy", "Pip-Boy 3000", C.TOOL, 1.0, 1000, (2, 2), origin="fallout",
       effects={"slot": "wrist", "shows_map": True, "geiger": True,
                "vats": True}, mesh_hint="wrist computer"),
    _i("laser_pistol", "AER9 Laser Pistol", C.WEAPON, 1.6, 400, (3, 2),
       origin="fallout",
       effects={"damage": 28, "dtype": "energy", "accuracy": 0.9,
                "ammo": "microfusion_cell", "ap_cost": 20, "noise_m": 80},
       mesh_hint="sci-fi pistol"),
    _i("microfusion_cell", "Microfusion Cell", C.AMMO, 0.02, 4, stack=50,
       origin="fallout", mesh_hint="battery cell"),
    _i("radsuit", "Hazmat Suit", C.CLOTHING, 4.0, 400, (5, 5), origin="fallout",
       effects={"slot": "suit", "insulation": 0.4, "waterproof": 1.0,
                "armor": {"radiation": 600, "chemical": 300}},
       mesh_hint="hazmat suit"),
    _i("scrap_metal", "Scrap Metal", C.JUNK, 0.5, 3, stack=10, origin="fallout",
       mesh_hint="scrap metal"),

    # --- S.T.A.L.K.E.R. -------------------------------------------------------
    _i("bolt", "Bolts", C.TOOL, 0.02, 0, stack=99, origin="stalker",
       effects={"throwable": True, "reveals_anomaly": True}, mesh_hint="metal bolt"),
    _i("detector_echo", "Echo Detector", C.TOOL, 0.3, 150, (1, 2), origin="stalker",
       effects={"artifact_range_m": 15, "shows_direction": False},
       mesh_hint="handheld detector"),
    _i("detector_bear", "Bear Detector", C.TOOL, 0.4, 600, (1, 2), origin="stalker",
       effects={"artifact_range_m": 30, "shows_direction": True},
       mesh_hint="handheld detector"),
    _i("vodka_cossacks", "Cossacks Vodka", C.DRINK, 0.5, 30, (1, 2), origin="stalker",
       effects={"rads": -60, "water": 5, "drunk_sec": 90}, mesh_hint="vodka bottle"),
    _i("medkit_army", "Army Medkit", C.MEDICAL, 0.4, 120, (2, 1), origin="stalker",
       effects={"heal": 60, "stop_bleed": 2}, mesh_hint="first aid kit"),
    _i("seva_suit", "SEVA Suit", C.CLOTHING, 7.0, 3500, (5, 6), origin="stalker",
       effects={"slot": "suit", "insulation": 0.5, "waterproof": 0.9,
                "armor": {"ballistic": 25, "radiation": 400, "fire": 150,
                          "electric": 150, "chemical": 250, "psy": 80},
                "sealed": True}, mesh_hint="sealed protective suit"),
    _i("ak74", "AK-74", C.WEAPON, 3.3, 400, (6, 3), origin="stalker",
       effects={"damage": 36, "dtype": "ballistic", "accuracy": 0.75,
                "ammo": "ammo_545_dirty", "ap_cost": 22, "noise_m": 600},
       mesh_hint="ak rifle"),
    # Artifacts: worn on the belt. Most emit radiation, so they're a trade-off.
    _i("art_jellyfish", "Jellyfish", C.ARTIFACT, 0.5, 800, origin="stalker",
       effects={"worn": {"rad_resist": 0.1, "rads_per_sec": 0.02},
                "anomaly": "vortex"}, mesh_hint="glowing stone artifact"),
    _i("art_stone_blood", "Stone Blood", C.ARTIFACT, 0.5, 1200, origin="stalker",
       effects={"worn": {"blood_regen_mult": 1.5, "rads_per_sec": 0.05},
                "anomaly": "fruit_punch"}, mesh_hint="red crystal artifact"),
    _i("art_fireball", "Fireball", C.ARTIFACT, 0.5, 1500, origin="stalker",
       effects={"worn": {"warmth_c": 4.0, "rads_per_sec": 0.03},
                "anomaly": "burner"}, mesh_hint="glowing orb artifact"),
    _i("art_flash", "Flash", C.ARTIFACT, 0.5, 1800, origin="stalker",
       effects={"worn": {"stamina_regen_mult": 1.4, "rads_per_sec": 0.04},
                "anomaly": "electro"}, mesh_hint="electric crystal artifact"),
    _i("art_night_star", "Night Star", C.ARTIFACT, 0.5, 4000, origin="stalker",
       effects={"worn": {"carry_bonus": 12.0, "rads_per_sec": 0.08},
                "anomaly": "springboard"}, mesh_hint="star shaped artifact"),
    _i("art_moonlight", "Moonlight", C.ARTIFACT, 0.5, 5000, origin="stalker",
       effects={"worn": {"psy_resist": 0.5, "rads_per_sec": 0.0},
                "anomaly": "electro"}, mesh_hint="blue orb artifact"),

    # --- Metro ----------------------------------------------------------------
    _i("gas_mask", "GP-5 Gas Mask", C.CLOTHING, 0.9, 150, (2, 2), origin="metro",
       effects={"slot": "mask", "gas_mask": True}, mesh_hint="soviet gas mask"),
    _i("filter", "Gas Mask Filter", C.FILTER, 0.25, 30, origin="metro", stack=5,
       effects={"filter_sec": 300}, mesh_hint="gas mask filter"),
    _i("ammo_545_mil", "Military-Grade 5.45", C.CURRENCY, 0.011, 10, stack=500,
       origin="metro", effects={"also_ammo": "ammo_545", "damage_mult": 1.35},
       mesh_hint="rifle cartridge"),
    _i("ammo_545_dirty", "Dirty 5.45", C.AMMO, 0.011, 2, stack=120,
       origin="metro", mesh_hint="rifle cartridge"),
    _i("bastard_smg", "Bastard SMG", C.WEAPON, 2.8, 120, (4, 2), origin="metro",
       effects={"damage": 24, "dtype": "ballistic", "accuracy": 0.55,
                "ammo": "ammo_545_dirty", "ap_cost": 15, "noise_m": 500,
                "jam_chance": 0.04}, mesh_hint="improvised submachine gun"),
    _i("tikhar", "Tikhar Pneumatic Rifle", C.WEAPON, 3.5, 250, (6, 2),
       origin="metro",
       effects={"damage": 55, "dtype": "ballistic", "accuracy": 0.85,
                "ammo": "ball_bearings", "ap_cost": 25, "noise_m": 25,
                "needs_pump": True}, mesh_hint="air rifle"),
    _i("ball_bearings", "Ball Bearings", C.AMMO, 0.01, 1, stack=100, origin="metro",
       mesh_hint="steel balls"),
    _i("hand_charger", "Hand Charger", C.TOOL, 0.6, 60, (2, 1), origin="metro",
       effects={"charges_flashlight": True}, mesh_hint="dynamo charger"),
    _i("mushroom_tea", "Mushroom Tea", C.DRINK, 0.3, 6, origin="metro",
       effects={"water": 20, "energy": 5}, mesh_hint="metal mug"),
    _i("military_ration", "Military Ration", C.FOOD, 0.5, 20, (2, 1), origin="metro",
       effects={"energy": 45}, mesh_hint="ration pack"),
)}


def get(item_id: str) -> ItemDef:
    try:
        return ITEMS[item_id]
    except KeyError:
        raise KeyError(f"unknown item '{item_id}'") from None


def make(item_id: str, quantity: int = 1, condition: float = 1.0,
         contaminated: bool = False) -> ItemStack:
    item = get(item_id)
    if quantity > item.stack:
        raise ValueError(f"{item_id} stacks to {item.stack}, asked {quantity}")
    return ItemStack(item, quantity, condition, contaminated)
