"""DayZ vitals: energy, water, blood, health, shock, stamina, body temperature,
bleeding wounds and diseases."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .config import SURVIVAL

DISEASES = {
    # name: (energy drain mult, water drain mult, health dmg/hour, symptom)
    "cholera": (1.0, 3.0, 4.0, "vomiting"),
    "salmonella": (2.0, 1.5, 2.0, "stomach pain"),
    "food_poisoning": (2.5, 1.0, 1.0, "vomiting"),
    "influenza": (1.3, 1.3, 1.5, "coughing"),
    "wound_infection": (1.0, 1.0, 6.0, "fever"),
}


@dataclass
class Environment:
    """What the world is doing to the player right now. Filled by ``world.py``
    (or by Unreal volumes when running in-engine)."""
    air_temp_c: float = 15.0
    raining: bool = False
    in_water: bool = False
    near_fire: bool = False
    sheltered: bool = False
    rads_per_sec: float = 0.0
    toxic_air: bool = False
    psy_per_sec: float = 0.0


@dataclass
class Vitals:
    health: float = 100.0
    max_health: float = 100.0
    energy: float = 80.0            # %
    water: float = 80.0             # %
    blood: float = SURVIVAL.max_blood
    shock: float = 0.0
    stamina: float = SURVIVAL.stamina_max
    body_temp_c: float = SURVIVAL.comfortable_temp_c
    wetness: float = 0.0            # 0 dry .. 1 soaked
    bleeding_wounds: int = 0
    diseases: set = field(default_factory=set)
    broken_legs: bool = False
    unconscious: bool = False
    status: list = field(default_factory=list)   # HUD icons, rebuilt each tick

    @property
    def alive(self) -> bool:
        return self.health > 0 and self.blood > 0

    # ------------------------------------------------------------------------
    def tick(self, dt: float, env: Environment, activity: str = "walk",
             insulation: float = 0.0, waterproof: float = 0.0,
             hunger_mult: float = 1.0, stamina_regen_mult: float = 1.0,
             blood_regen_mult: float = 1.0, warmth_bonus_c: float = 0.0) -> list:
        """Advance ``dt`` seconds. Returns a list of event strings."""
        if not self.alive:
            return []
        events = []
        hours = dt / 3600.0
        t = SURVIVAL
        act = t.activity_multipliers.get(activity, 1.0)
        if self.broken_legs and activity in ("jog", "sprint"):
            activity, act = "walk", t.activity_multipliers["walk"]

        # --- Diseases -------------------------------------------------------
        e_mult, w_mult, disease_dmg = 1.0, 1.0, 0.0
        for name in self.diseases:
            de, dw, dh, _ = DISEASES[name]
            e_mult, w_mult, disease_dmg = e_mult * de, w_mult * dw, disease_dmg + dh

        # --- Temperature ----------------------------------------------------
        target = self._target_temp(env, insulation, waterproof, act) + warmth_bonus_c
        rate = t.temp_response_per_hour * hours
        self.body_temp_c += max(-rate, min(rate, target - self.body_temp_c))
        hot = max(0.0, self.body_temp_c - 37.2)

        # --- Hunger / thirst ------------------------------------------------
        self.energy = max(0.0, self.energy - t.energy_drain_per_hour * act *
                          e_mult * hunger_mult * hours)
        self.water = max(0.0, self.water - t.water_drain_per_hour * act * w_mult *
                         (1.0 + hot) * hours)

        dmg = disease_dmg * hours
        if self.energy <= 0:
            dmg += t.starvation_damage_per_hour * hours
        if self.water <= 0:
            dmg += t.dehydration_damage_per_hour * hours
        if self.body_temp_c < t.hypothermia_c or self.body_temp_c > t.hyperthermia_c:
            dmg += t.temp_damage_per_hour * hours

        # --- Blood ----------------------------------------------------------
        if self.bleeding_wounds:
            self.blood -= self.bleeding_wounds * t.bleed_rate_per_source_per_sec * dt
        elif self.energy > 40 and self.water > 40:
            self.blood = min(t.max_blood, self.blood +
                             t.blood_regen_per_hour * blood_regen_mult * hours)
        if self.blood < t.low_blood_threshold:
            dmg += (t.low_blood_threshold - self.blood) / 100.0 * hours * 10

        # Health slowly regenerates when well fed, hydrated and not bleeding.
        if not dmg and self.energy > 60 and self.water > 60 and not self.bleeding_wounds:
            self.health = min(self.max_health, self.health + 5.0 * hours)
        self.health = min(self.max_health, self.health - dmg)

        # --- Stamina / shock ------------------------------------------------
        cost = t.stamina_cost_per_sec.get(activity, 0.0)
        if cost:
            self.stamina = max(0.0, self.stamina - cost * dt)
        else:
            self.stamina = min(t.stamina_max, self.stamina +
                               t.stamina_regen_per_sec * stamina_regen_mult * dt)
        self.shock = max(0.0, self.shock - t.shock_recovery_per_sec * dt)
        was_out = self.unconscious
        self.unconscious = self.shock >= t.unconscious_shock
        if self.unconscious and not was_out:
            events.append("You lose consciousness.")
        elif was_out and not self.unconscious:
            events.append("You come to.")

        self.blood = max(0.0, self.blood)
        self.health = max(0.0, self.health)
        if not self.alive:
            events.append("You are dead.")
        self._refresh_status()
        return events

    def _target_temp(self, env: Environment, insulation: float,
                     waterproof: float, activity_mult: float) -> float:
        if env.in_water:
            self.wetness = 1.0
        elif env.raining and not env.sheltered:
            self.wetness = min(1.0, self.wetness + 0.02 * (1.0 - waterproof))
        else:
            self.wetness = max(0.0, self.wetness - (0.03 if env.near_fire else 0.005))
        # How far the ambient pulls us from 36.6: insulation blocks the pull,
        # wetness strips insulation, exertion and fire add heat.
        effective_ins = insulation * (1.0 - 0.7 * self.wetness)
        pull = (env.air_temp_c - 22.0) * 0.15 * (1.0 - effective_ins)
        heat = (activity_mult - 1.0) * 0.6 + (2.0 if env.near_fire else 0.0)
        return SURVIVAL.comfortable_temp_c + pull + heat

    def _refresh_status(self) -> None:
        s = []
        if self.energy < 20:
            s.append("hungry")
        if self.water < 20:
            s.append("thirsty")
        if self.bleeding_wounds:
            s.append(f"bleeding x{self.bleeding_wounds}")
        if self.blood < SURVIVAL.low_blood_threshold:
            s.append("low blood")
        if self.body_temp_c < SURVIVAL.hypothermia_c:
            s.append("freezing")
        elif self.body_temp_c > SURVIVAL.hyperthermia_c:
            s.append("overheating")
        if self.wetness > 0.6:
            s.append("soaked")
        if self.broken_legs:
            s.append("broken legs")
        s.extend(DISEASES[d][3] for d in sorted(self.diseases))
        self.status = s

    # --- Interactions --------------------------------------------------------
    def take_damage(self, amount: float, shock: float = 0.0,
                    wound: bool = False) -> None:
        self.health = max(0.0, self.health - amount)
        self.shock = min(100.0, self.shock + shock)
        if wound:
            self.bleeding_wounds += 1

    def consume(self, effects: dict, rng: random.Random,
                disease_resist: float = 0.0, contaminated: bool = False) -> list:
        events = []
        self.energy = max(0.0, min(100.0, self.energy + effects.get("energy", 0)))
        self.water = max(0.0, min(100.0, self.water + effects.get("water", 0)))
        disease = effects.get("disease") or ("food_poisoning" if contaminated else None)
        chance = effects.get("disease_chance", 0.5 if contaminated else 0.0)
        if disease and rng.random() < chance * (1.0 - disease_resist):
            self.diseases.add(disease)
            events.append(f"You feel sick ({disease.replace('_', ' ')}).")
        return events

    def treat(self, effects: dict, rng: random.Random, heal_mult: float = 1.0) -> list:
        events = []
        stops = int(effects.get("stop_bleed", 0))
        if stops and self.bleeding_wounds:
            self.bleeding_wounds = max(0, self.bleeding_wounds - stops)
            events.append("You bandage a wound.")
            if rng.random() < effects.get("infection_chance", 0.0):
                self.diseases.add("wound_infection")
                events.append("The dirty rag infects the wound.")
        if "heal" in effects:
            self.health = min(self.max_health, self.health + effects["heal"] * heal_mult)
        if "blood" in effects:
            self.blood = min(SURVIVAL.max_blood, self.blood + effects["blood"])
        if "shock" in effects:
            self.shock = max(0.0, self.shock + effects["shock"])
        if effects.get("fix_limbs"):
            self.broken_legs = False
        for cure in effects.get("cure", []):
            if cure in self.diseases:
                self.diseases.discard(cure)
                events.append(f"The {cure.replace('_', ' ')} subsides.")
        return events
