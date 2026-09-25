"""Fallout-style character progression: S.P.E.C.I.A.L., derived stats, XP,
perks and karma."""

from __future__ import annotations

from dataclasses import dataclass, field

STAT_NAMES = ("strength", "perception", "endurance", "charisma",
              "intelligence", "agility", "luck")


@dataclass
class Special:
    strength: int = 5
    perception: int = 5
    endurance: int = 5
    charisma: int = 5
    intelligence: int = 5
    agility: int = 5
    luck: int = 5

    def __post_init__(self) -> None:
        for name in STAT_NAMES:
            value = getattr(self, name)
            if not 1 <= value <= 10:
                raise ValueError(f"{name} must be 1-10, got {value}")

    @classmethod
    def build(cls, points: dict, budget: int = 28) -> "Special":
        """Create a character from a point-buy (Fallout 4: 21 extra points on
        top of 1 in each stat = 28 total)."""
        stats = {name: int(points.get(name, 1)) for name in STAT_NAMES}
        spent = sum(stats.values())
        if spent > budget:
            raise ValueError(f"spent {spent} points, budget is {budget}")
        return cls(**stats)

    # Derived stats ---------------------------------------------------------
    @property
    def max_health(self) -> float:
        return 80.0 + self.endurance * 5.0

    @property
    def carry_weight_kg(self) -> float:
        # DayZ has no hard cap, but stamina suffers above this.
        return 25.0 + self.strength * 3.0

    @property
    def action_points(self) -> float:
        return 60.0 + self.agility * 10.0

    @property
    def barter_modifier(self) -> float:
        """Multiplier on trader prices (lower is better for the buyer)."""
        return 1.25 - self.charisma * 0.035

    @property
    def crit_chance(self) -> float:
        return 0.01 + self.luck * 0.01

    @property
    def stamina_regen_bonus(self) -> float:
        return 1.0 + (self.endurance - 5) * 0.05

    @property
    def hunger_multiplier(self) -> float:
        return 1.0 - (self.endurance - 5) * 0.03

    @property
    def xp_multiplier(self) -> float:
        return 1.0 + self.intelligence * 0.03


@dataclass(frozen=True)
class Perk:
    id: str
    name: str
    stat: str
    required_rank: int
    min_level: int
    description: str
    effects: dict = field(default_factory=dict)


# Effects are generic keys consumed by the systems that care about them.
PERKS = {p.id: p for p in (
    Perk("iron_stomach", "Iron Stomach", "endurance", 3, 1,
         "Raw meat and dirty water are 70% less likely to make you sick.",
         {"disease_resist": 0.7}),
    Perk("rad_resistant", "Rad Resistant", "endurance", 6, 4,
         "+25% radiation resistance.", {"rad_resist": 0.25}),
    Perk("lead_belly", "Lead Belly", "endurance", 2, 1,
         "Contaminated food gives 50% fewer rads.", {"food_rad_mult": 0.5}),
    Perk("pack_mule", "Pack Mule", "strength", 4, 2,
         "+15 kg carry weight.", {"carry_bonus": 15.0}),
    Perk("stalker_sense", "Zone Sense", "perception", 5, 3,
         "Detect anomalies within 8 m without a detector.",
         {"anomaly_sense_m": 8.0}),
    Perk("bolt_thrower", "Bolt Thrower", "agility", 3, 1,
         "Thrown bolts travel further and reveal anomalies longer.",
         {"bolt_range_mult": 1.5}),
    Perk("mask_discipline", "Mask Discipline", "endurance", 5, 2,
         "Filters last 25% longer.", {"filter_mult": 1.25}),
    Perk("metro_trader", "Hansa Contacts", "charisma", 5, 3,
         "Better prices with station traders.", {"barter_mult": 0.9}),
    Perk("scrounger", "Scrounger", "luck", 4, 2,
         "Find more ammo in containers.", {"ammo_loot_mult": 1.5}),
    Perk("medic", "Field Medic", "intelligence", 4, 1,
         "Bandages stop bleeding twice as fast; stimpaks heal 40% more.",
         {"heal_mult": 1.4}),
    Perk("sneak", "Sneak", "agility", 4, 1,
         "Infected and mutants are 25% less likely to notice you.",
         {"noise_mult": 0.75}),
    Perk("gunslinger", "Gunslinger", "agility", 6, 5,
         "V.A.T.S. costs 20% less AP.", {"vats_ap_mult": 0.8}),
)}


def xp_for_level(level: int) -> int:
    """Total XP needed to *reach* ``level`` (Fallout 4 curve)."""
    if level <= 1:
        return 0
    n = level - 1
    return int(75 * n * n + 125 * n)


@dataclass
class Progression:
    special: Special = field(default_factory=Special)
    xp: int = 0
    level: int = 1
    perk_points: int = 0
    perks: dict = field(default_factory=dict)   # perk id -> rank
    karma: int = 0                              # -1000..1000

    def add_xp(self, amount: float) -> list:
        """Adds XP (scaled by Intelligence). Returns the list of new levels."""
        self.xp += int(round(amount * self.special.xp_multiplier))
        gained = []
        while self.xp >= xp_for_level(self.level + 1):
            self.level += 1
            self.perk_points += 1
            gained.append(self.level)
        return gained

    def can_take(self, perk_id: str) -> tuple:
        perk = PERKS.get(perk_id)
        if perk is None:
            return False, "unknown perk"
        if self.perk_points <= 0:
            return False, "no perk points"
        if getattr(self.special, perk.stat) < perk.required_rank:
            return False, f"needs {perk.stat} {perk.required_rank}"
        if self.level < perk.min_level:
            return False, f"needs level {perk.min_level}"
        if perk_id in self.perks:
            return False, "already known"
        return True, ""

    def take_perk(self, perk_id: str) -> None:
        ok, reason = self.can_take(perk_id)
        if not ok:
            raise ValueError(f"cannot take {perk_id}: {reason}")
        self.perk_points -= 1
        self.perks[perk_id] = 1

    def effect(self, key: str, default: float) -> float:
        """Combine a perk effect across owned perks (multiplicative for *_mult,
        additive otherwise)."""
        value = default
        for perk_id in self.perks:
            eff = PERKS[perk_id].effects
            if key in eff:
                value = value * eff[key] if key.endswith("_mult") else value + eff[key]
        return value

    def adjust_karma(self, delta: int) -> None:
        self.karma = max(-1000, min(1000, self.karma + delta))

    @property
    def karma_title(self) -> str:
        k = self.karma
        if k >= 750:
            return "Messiah"
        if k >= 250:
            return "Guardian"
        if k > -250:
            return "Wanderer"
        if k > -750:
            return "Marauder"
        return "Devil"
