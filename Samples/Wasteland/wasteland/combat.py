"""Damage model: typed damage, armor, hit zones, and a V.A.T.S.-style targeting
helper. Ballistics are resolved by Unreal line traces in-game; this module only
turns a confirmed hit into numbers."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum


class DamageType(str, Enum):
    BALLISTIC = "ballistic"
    ENERGY = "energy"          # Fallout lasers/plasma
    FIRE = "fire"              # Burner anomaly, molotovs
    ELECTRIC = "electric"      # Electro anomaly
    CHEMICAL = "chemical"      # Fruit Punch anomaly, acid rain
    RADIATION = "radiation"
    PSY = "psy"                # Brain Scorcher, Controllers, the Dark Ones
    MELEE = "melee"
    GRAVITY = "gravity"        # Vortex / Springboard anomalies


class HitZone(str, Enum):
    HEAD = "head"
    TORSO = "torso"
    LEFT_ARM = "left_arm"
    RIGHT_ARM = "right_arm"
    LEFT_LEG = "left_leg"
    RIGHT_LEG = "right_leg"


ZONE_MULTIPLIER = {
    HitZone.HEAD: 3.0,
    HitZone.TORSO: 1.0,
    HitZone.LEFT_ARM: 0.6, HitZone.RIGHT_ARM: 0.6,
    HitZone.LEFT_LEG: 0.7, HitZone.RIGHT_LEG: 0.7,
}

# How hard each zone is to hit in V.A.T.S. (1.0 = torso baseline).
ZONE_DIFFICULTY = {
    HitZone.HEAD: 0.45,
    HitZone.TORSO: 1.0,
    HitZone.LEFT_ARM: 0.65, HitZone.RIGHT_ARM: 0.65,
    HitZone.LEFT_LEG: 0.7, HitZone.RIGHT_LEG: 0.7,
}

# Chance that a hit on this zone opens a bleeding wound (DayZ).
ZONE_BLEED_CHANCE = {
    HitZone.HEAD: 0.5, HitZone.TORSO: 0.6,
    HitZone.LEFT_ARM: 0.35, HitZone.RIGHT_ARM: 0.35,
    HitZone.LEFT_LEG: 0.4, HitZone.RIGHT_LEG: 0.4,
}


@dataclass
class Resistances:
    values: dict = field(default_factory=dict)

    def get(self, dtype: DamageType) -> float:
        return float(self.values.get(DamageType(dtype), 0.0))

    def combined(self, other: "Resistances") -> "Resistances":
        merged = dict(self.values)
        for key, value in other.values.items():
            merged[key] = merged.get(key, 0.0) + value
        return Resistances(merged)


def mitigate(damage: float, resistance: float) -> float:
    """Fallout 4's armor curve: damage * (damage / resist)^0.365 / 2, clamped.

    Big hits punch through armor, small hits are mostly absorbed, and armor can
    never reduce damage below 1% or above 99%."""
    if damage <= 0:
        return 0.0
    if resistance <= 0:
        return damage
    factor = 0.5 * (damage / resistance) ** 0.365
    return damage * max(0.01, min(0.99, factor))


@dataclass
class HitResult:
    damage: float
    zone: HitZone
    dtype: DamageType
    opened_wound: bool
    shock: float
    crippled: bool = False


def resolve_hit(base_damage: float, dtype: DamageType, zone: HitZone,
                armor: Resistances, rng: random.Random,
                crit: bool = False) -> HitResult:
    raw = base_damage * ZONE_MULTIPLIER[zone] * (2.0 if crit else 1.0)
    dealt = mitigate(raw, armor.get(dtype))
    wound = dtype in (DamageType.BALLISTIC, DamageType.MELEE) and \
        rng.random() < ZONE_BLEED_CHANCE[zone] * min(1.0, dealt / 20.0)
    # DayZ shock: blunt force and headshots knock people out.
    shock = dealt * (1.5 if zone is HitZone.HEAD else 0.6)
    crippled = zone not in (HitZone.HEAD, HitZone.TORSO) and dealt >= 35
    return HitResult(dealt, zone, dtype, wound, shock, crippled)


def vats_hit_chance(distance_m: float, weapon_accuracy: float, perception: int,
                    zone: HitZone, target_moving: bool = False) -> float:
    """Probability (0-0.95) of a V.A.T.S. shot connecting."""
    base = 0.95 * weapon_accuracy * ZONE_DIFFICULTY[zone]
    effective_range = 20.0 + 4.0 * perception
    falloff = math.exp(-max(0.0, distance_m - effective_range) / effective_range)
    moving = 0.8 if target_moving else 1.0
    return round(max(0.0, min(0.95, base * falloff * moving)), 3)


def vats_ap_cost(weapon_ap_cost: float, agility: int) -> float:
    return max(5.0, weapon_ap_cost * (1.0 - 0.03 * (agility - 5)))
