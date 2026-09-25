"""Ties every system together. ``GameSession.tick`` is what Unreal calls each
frame (via ``unreal_tools/pie_bridge.py``) and what the headless simulation
drives from the command line:

    python -m wasteland.game --hours 12 --seed 7
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass, field

from . import items
from .anomalies import Emission
from .combat import DamageType, HitZone, Resistances, resolve_hit, vats_hit_chance
from .creatures import Creature, State, spawn_group
from .economy import default_traders
from .factions import Reputation
from .hazards import GasMask, Radiation
from .inventory import Inventory
from .items import Category
from .special import Progression, Special
from .survival import Vitals
from .world import Clock, Weather, WorldLayout, roll_loot

FISTS = items.ItemDef("fists", "Fists", Category.WEAPON, 0.0, 0,
                      effects={"damage": 6, "dtype": "melee", "accuracy": 0.9,
                               "ap_cost": 10, "noise_m": 5})

NOISE_BY_ACTIVITY = {"idle": 2.0, "crouch": 4.0, "walk": 12.0, "jog": 25.0, "sprint": 40.0}


@dataclass
class Player:
    name: str = "Survivor"
    x: float = 0.0
    y: float = 0.0
    underground: bool = False
    activity: str = "walk"
    progression: Progression = field(default_factory=Progression)
    vitals: Vitals = field(default_factory=Vitals)
    radiation: Radiation = field(default_factory=Radiation)
    mask: GasMask = field(default_factory=GasMask)
    inventory: Inventory = field(default_factory=Inventory)
    reputation: Reputation = field(default_factory=Reputation)

    @property
    def special(self) -> Special:
        return self.progression.special

    def armor(self) -> Resistances:
        return self.inventory.armor()

    def rad_resistance(self) -> float:
        suit = self.armor().get(DamageType.RADIATION) / 1000.0
        return min(0.95, suit + self.progression.effect("rad_resist", 0.0)
                   + self.inventory.artifact_effect("rad_resist"))

    def carry_limit(self) -> float:
        return (self.special.carry_weight_kg + self.progression.effect("carry_bonus", 0.0)
                + self.inventory.artifact_effect("carry_bonus"))

    def overloaded(self) -> bool:
        return self.inventory.total_weight > self.carry_limit()


class GameSession:
    def __init__(self, seed: int = 1986, player: Player | None = None):
        self.rng = random.Random(seed)
        self.world = WorldLayout(seed)
        self.clock = Clock()
        self.weather = Weather(self.rng)
        self.emission = Emission(self.rng)
        self.traders = default_traders()
        self.player = player or self._new_player()
        self.creatures: list[Creature] = []
        self.looted: set = set()
        self.log: list[str] = []
        self.fires: list[list] = []          # [x, y, seconds of fuel left]
        self._spawn_timer = 0.0

    # -- Setup ------------------------------------------------------------------
    def _new_player(self) -> Player:
        # DayZ fresh spawn: coast of the west region, a rag and a light.
        start = min((p for p in self.world.pois if p.kind == "village"),
                    key=lambda p: p.x)
        player = Player(x=start.x, y=start.y)
        player.inventory.equip(items.make("gorka_jacket", condition=0.6))
        player.inventory.add(items.make("rag", 2))
        player.inventory.add(items.make("apple"))
        player.inventory.add(items.make("matches", 5))
        player.inventory.add(items.make("bolt", 10))
        # A nod to Metro: everyone keeps an old GP-5 and one filter for the city.
        player.inventory.equip(items.make("gas_mask", condition=0.5))
        player.inventory.add(items.make("filter", 2))
        player.vitals.max_health = player.special.max_health
        player.vitals.health = player.vitals.max_health
        return player

    def say(self, message: str) -> None:
        self.log.append(f"[{self.clock}] {message}")

    # -- Main loop --------------------------------------------------------------
    def tick(self, dt: float) -> None:
        p, v = self.player, self.player.vitals
        if not v.alive:
            return
        self.clock.advance(dt)
        changed = self.weather.tick(dt)
        if changed:
            self.say(f"The weather turns: {changed.replace('_', ' ')}.")

        env = self.world.environment_at(p.x, p.y, self.clock, self.weather, p.underground)
        env.near_fire = self._near_fire()
        poi = self.world.poi_at(p.x, p.y)
        for fire in self.fires:
            fire[2] -= dt * (3.0 if env.raining else 1.0)
        self.fires = [f for f in self.fires if f[2] > 0]

        # Emission (Blowout)
        for event in self.emission.tick(dt):
            self._on_emission(event)
        sheltered = p.underground or env.sheltered
        emission_dmg = self.emission.damage_per_sec(sheltered) * dt

        # Radiation caps max HP (Fallout); sickness damages.
        p.radiation.tick(dt, env.rads_per_sec + p.inventory.artifact_effect("rads_per_sec"),
                         p.rad_resistance())
        v.max_health = p.radiation.max_health_cap(p.special.max_health)

        # Toxic air (Metro)
        exertion = {"sprint": 2.0, "jog": 1.4}.get(p.activity, 1.0)
        p.mask.equipped = p.inventory.equipped("mask") is not None
        if p.inventory.is_sealed():
            choke, mask_events = 0.0, []
        else:
            choke, mask_events = p.mask.tick(dt, env.toxic_air, exertion,
                                             p.progression.effect("filter_mult", 1.0))
        for event in mask_events:
            self.say(event)
        if p.mask.filter_sec == 0 and env.toxic_air and p.inventory.count("filter"):
            self._swap_filter()

        # DayZ vitals
        for event in v.tick(
                dt, env, p.activity,
                insulation=p.inventory.insulation(),
                waterproof=p.inventory.waterproofing(),
                hunger_mult=p.special.hunger_multiplier,
                stamina_regen_mult=p.special.stamina_regen_bonus *
                p.inventory.artifact_effect("stamina_regen_mult", 1.0, True),
                blood_regen_mult=p.inventory.artifact_effect("blood_regen_mult", 1.0, True),
                warmth_bonus_c=p.inventory.artifact_effect("warmth_c")):
            self.say(event)
        sickness = 10.0 * dt / 3600.0 if p.radiation.sick else 0.0
        v.take_damage(choke + emission_dmg + sickness)

        self._tick_anomalies(dt, poi)
        self._tick_creatures(dt, poi)
        if not v.alive:
            self.say(f"{p.name} died. Everything is lost - fresh spawn on the coast.")

    # -- Subsystems -------------------------------------------------------------
    def _on_emission(self, event: str) -> None:
        if event == "emission_warning":
            self.say("EMISSION INCOMING! Find shelter!")
        elif event == "emission_start":
            self.say("The sky burns red - the emission has begun.")
        elif event == "emission_end":
            self.say("The emission passes. Anomalies have shifted; new artifacts formed.")
            for poi in self.world.pois:
                if poi.anomaly_field:
                    poi.anomaly_field.shuffle(self.rng)

    def _swap_filter(self) -> None:
        stack = self.player.inventory.take("filter")
        if stack:
            self.player.mask.insert_filter(stack.item.effects["filter_sec"])
            self.say("You screw on a fresh filter.")

    def _tick_anomalies(self, dt: float, poi) -> None:
        if not poi or not poi.anomaly_field:
            return
        p = self.player
        for anomaly in poi.anomaly_field.anomalies:
            anomaly.tick(dt)
            if anomaly.contains(p.x, p.y):
                dmg = anomaly.trigger()
                if dmg:
                    hit = resolve_hit(dmg, anomaly.type.dtype, HitZone.TORSO,
                                      p.armor(), self.rng)
                    p.vitals.take_damage(hit.damage, hit.shock)
                    self.say(f"You stumble into a {anomaly.type.name}! (-{hit.damage:.0f} HP)")

    def _tick_creatures(self, dt: float, poi) -> None:
        p = self.player
        self._spawn_timer -= dt
        if poi and self._spawn_timer <= 0:
            self._spawn_timer = 600.0
            nearby = sum(1 for c in self.creatures if c.alive and
                         c.distance_to(p.x, p.y) < poi.radius_m * 2)
            if nearby < 6:
                pool = [c for c in poi.creatures if
                        (not p.underground) or c in ("nosalis", "librarian", "watcher")]
                if pool:
                    kind = self.rng.choice(pool)
                    angle = self.rng.random() * math.tau
                    dist = self.rng.uniform(40, 120)
                    self.creatures += spawn_group(kind, p.x + dist * math.cos(angle),
                                                  p.y + dist * math.sin(angle), self.rng)
        noise = NOISE_BY_ACTIVITY.get(p.activity, 12.0) * \
            p.progression.effect("noise_mult", 1.0)
        stealth = 0.6 if p.activity == "crouch" else 1.0
        for creature in self.creatures:
            dmg = creature.tick(dt, (p.x, p.y), noise, self.clock.is_night,
                                stealth, self.rng)
            if dmg:
                zone = self.rng.choice(list(HitZone))
                hit = resolve_hit(dmg, creature.type.dtype, zone, p.armor(), self.rng)
                p.vitals.take_damage(hit.damage, hit.shock, hit.opened_wound)
                if hit.crippled and zone.value.endswith("leg"):
                    p.vitals.broken_legs = True
                self.say(f"{creature.type.name} hits your {zone.value.replace('_', ' ')} "
                         f"(-{hit.damage:.0f} HP{', bleeding' if hit.opened_wound else ''}).")
        self.creatures = [c for c in self.creatures
                          if c.alive and c.distance_to(p.x, p.y) < 1500]

    # -- Player actions ---------------------------------------------------------
    def use_item(self, item_id: str) -> bool:
        p = self.player
        stack = p.inventory.take(item_id)
        if stack is None:
            return False
        eff, rng, prog = stack.item.effects, self.rng, p.progression
        cat = stack.item.category
        events = []
        if cat in (Category.FOOD, Category.DRINK):
            events += p.vitals.consume(eff, rng, prog.effect("disease_resist", 0.0),
                                       stack.contaminated)
            rads = eff.get("rads", 0) + (15 if stack.contaminated else 0)
            p.radiation.add(rads * prog.effect("food_rad_mult", 1.0) if rads > 0 else rads)
        elif cat is Category.MEDICAL:
            events += p.vitals.treat(eff, rng, prog.effect("heal_mult", 1.0))
            if "rads" in eff:
                p.radiation.add(eff["rads"])
            if "rad_resist_buff" in eff:
                p.radiation.resist_buff = eff["rad_resist_buff"]
                p.radiation.resist_buff_sec = eff["buff_sec"]
        elif cat is Category.FILTER:
            p.mask.insert_filter(eff["filter_sec"])
        else:
            p.inventory.add(stack)
            return False
        self.say(f"Used {stack.item.name}.")
        for event in events:
            self.say(event)
        return True

    def _near_fire(self, reach_m: float = 4.0) -> bool:
        p = self.player
        return any(math.hypot(fx - p.x, fy - p.y) <= reach_m for fx, fy, _ in self.fires)

    def light_fire(self, fuel_sec: float = 3 * 3600.0) -> bool:
        """DayZ fireplace: a match and some sticks. Keeps you warm and dries
        you off; rain makes it burn out faster."""
        p = self.player
        if self._near_fire() or not p.inventory.take("matches"):
            return False
        self.fires.append([p.x, p.y, fuel_sec])
        self.say("You get a fire going.")
        return True

    def search_nearby(self) -> list:
        """Search the closest unlooted spot within 10 m."""
        p = self.player
        poi = self.world.poi_at(p.x, p.y)
        if not poi:
            return []
        for i, (lx, ly) in enumerate(poi.loot_spots):
            key = (poi.name, i)
            if key not in self.looted and math.hypot(lx - p.x, ly - p.y) < 10:
                self.looted.add(key)
                found = roll_loot(poi.loot_table, self.rng,
                                  ammo_mult=p.progression.effect("ammo_loot_mult", 1.0))
                kept = []
                for stack in found:
                    label = f"{stack.quantity}x {stack.item.name} ({stack.condition_label})"
                    if p.inventory.pick_up(stack):
                        kept.append(stack)
                        self.say(f"Found {label}.")
                    else:
                        self.say(f"No room for {label}.")
                return kept
        return []

    def attack(self, creature: Creature, weapon_slot: str = "primary",
               zone: HitZone = HitZone.TORSO, vats: bool = False) -> bool:
        p = self.player
        weapon = p.inventory.equipped(weapon_slot)
        if weapon is None:
            # Bare fists: weak, but DayZ spawns never start with a gun.
            weapon = items.ItemStack(FISTS)
        eff = weapon.item.effects
        ammo_id = eff.get("ammo")
        if ammo_id and not p.inventory.take(ammo_id):
            self.say("*click* - out of ammo.")
            return False
        dist = creature.distance_to(p.x, p.y)
        chance = vats_hit_chance(dist, eff["accuracy"] * max(0.3, weapon.condition),
                                 p.special.perception, zone,
                                 creature.state == State.CHASE) if vats else \
            eff["accuracy"] * max(0.3, weapon.condition) * 0.9
        weapon.condition = max(0.0, weapon.condition - 0.002)
        if self.rng.random() > chance:
            self.say(f"You miss the {creature.type.name}.")
        else:
            crit = self.rng.random() < p.special.crit_chance
            hit = resolve_hit(eff["damage"], DamageType(eff["dtype"]), zone,
                              creature.resistances, self.rng, crit)
            creature.take_hit(hit.damage)
            self.say(f"You hit the {creature.type.name} in the {zone.value} for "
                     f"{hit.damage:.0f}{' (critical)' if crit else ''}.")
            if not creature.alive:
                levels = p.progression.add_xp(creature.type.xp)
                self.say(f"{creature.type.name} killed. +{creature.type.xp} XP")
                for level in levels:
                    self.say(f"LEVEL UP! You are now level {level}.")
        # Gunshots carry: wake up everything within earshot.
        for other in self.creatures:
            if other.alive and other.can_hear(p.x, p.y, eff.get("noise_m", 50)) \
                    and other.state in (State.IDLE, State.WANDER):
                other.state, other.target = State.INVESTIGATE, (p.x, p.y)
        return True

    def move_toward(self, tx: float, ty: float, dt: float) -> None:
        p = self.player
        if p.vitals.unconscious:
            return
        speed = {"crouch": 1.5, "walk": 2.0, "jog": 4.5, "sprint": 7.0}.get(p.activity, 0.0)
        if p.activity in ("jog", "sprint") and (p.vitals.stamina <= 0 or p.overloaded()):
            p.activity, speed = "walk", 2.0
        if p.vitals.broken_legs:
            speed = min(speed, 1.2)
        d = math.hypot(tx - p.x, ty - p.y)
        if d > 0:
            step = min(d, speed * dt)
            p.x += (tx - p.x) / d * step
            p.y += (ty - p.y) / d * step

    def hud(self) -> dict:
        p, v = self.player, self.player.vitals
        env = self.world.environment_at(p.x, p.y, self.clock, self.weather, p.underground)
        poi = self.world.poi_at(p.x, p.y)
        return {
            "time": str(self.clock), "weather": self.weather.state,
            "location": poi.name if poi else self.world.region_at(p.x),
            "health": round(v.health), "max_health": round(v.max_health),
            "blood": round(v.blood), "energy": round(v.energy), "water": round(v.water),
            "temp_c": round(v.body_temp_c, 1), "stamina": round(v.stamina),
            "rads": round(p.radiation.rads),
            "geiger_cps": round(p.radiation.geiger_rate(env.rads_per_sec), 1),
            "filter_sec": round(p.mask.filter_sec) if env.toxic_air else None,
            "status": v.status, "emission": self.emission.state,
            "level": p.progression.level, "karma": p.progression.karma_title,
            "weight_kg": round(p.inventory.total_weight, 1),
        }


# -- Headless demo ---------------------------------------------------------------
def run_demo(hours: float, seed: int, dt: float = 1.0, verbose: bool = True) -> GameSession:
    """An autopilot survivor walks from the coast, through the Metro, into the
    Zone, looting and fighting on the way. Useful for balancing: it's a
    deterministic run for a given seed."""
    s = GameSession(seed)
    route = _plan_route(s.world)
    target = 0
    s.say(f"{s.player.name} wakes up on the coast near {route[0].name}.")
    steps = int(hours * 3600 / dt)
    finished = False
    for _ in range(steps):
        p = s.player
        if not p.vitals.alive:
            break
        _autopilot(s, route, target, dt, finished)
        poi = route[target]
        if not finished and math.hypot(poi.x - p.x, poi.y - p.y) < 15:
            p.underground = poi.underground
            for lx, ly in poi.loot_spots[:4]:
                p.x, p.y = lx, ly
                s.search_nearby()
            if poi.anomaly_field:
                ping = poi.anomaly_field.detector_ping(p.x, p.y, 40, True)
                if ping:
                    s.say(f"Detector beeps: artifact {ping['distance_m']} m away.")
            p.x, p.y = poi.x, poi.y
            p.underground = False
            if target == len(route) - 1:
                finished = True
                s.say(f"Reached {poi.name}. Making camp outside the hot zone.")
            else:
                target += 1
                nxt = route[target]
                # Metro: station to station goes through the tunnels.
                via = " through the tunnels" if poi.kind == nxt.kind == "metro_station" else ""
                s.say(f"Heading for {nxt.name}{via}.")
        s.tick(dt)
    if verbose:
        for line in s.log:
            print(line)
        print("\nFinal HUD:")
        for key, value in s.hud().items():
            print(f"  {key:>11}: {value}")
    return s


def _plan_route(world: WorldLayout) -> list:
    by_kind = lambda k: sorted((p for p in world.pois if p.kind == k), key=lambda p: p.x)
    route = by_kind("village")[:2] + by_kind("military")[:1] + by_kind("metro_station")[:2] \
        + by_kind("vault")[:1] + by_kind("industrial")[:1] + by_kind("anomaly_field")[:1]
    return route


def _autopilot(s: GameSession, route: list, target: int, dt: float,
               finished: bool = False) -> None:
    p, v = s.player, s.player.vitals
    # Survive first, travel second.
    if v.bleeding_wounds:
        for med in ("bandage", "rag", "medkit_army"):
            if s.use_item(med):
                break
    if v.health < v.max_health * 0.4:
        for med in ("stimpak", "medkit_army"):
            if s.use_item(med):
                break
    if v.energy < 35:
        for food in ("military_ration", "canned_beans", "canned_peaches",
                     "cooked_meat", "apple"):
            if s.use_item(food):
                break
    if v.water < 35:
        for drink in ("water_bottle", "mushroom_tea", "nuka_cola", "vodka_cossacks"):
            if s.use_item(drink):
                break
    if p.radiation.rads > 350:
        s.use_item("radaway") or s.use_item("vodka_cossacks")
    for slot_item in ("gas_mask", "hiking_backpack", "plate_carrier", "seva_suit"):
        if p.inventory.count(slot_item):
            p.inventory.equip(p.inventory.take(slot_item))
    for weapon in ("m4a1", "ak74", "mosin", "bastard_smg", "laser_pistol", "fire_axe"):
        if p.inventory.count(weapon) and p.inventory.equipped("primary") is None:
            p.inventory.equip(p.inventory.take(weapon))
    # Fight whatever is attacking.
    threats = [c for c in s.creatures if c.alive and c.state in (State.CHASE, State.ATTACK)]
    if threats:
        nearest = min(threats, key=lambda c: c.distance_to(p.x, p.y))
        slot = "primary" if p.inventory.equipped("primary") else "melee"
        if s.rng.random() < dt:   # ~one attack per second
            s.attack(nearest, slot, vats=True) or s.attack(nearest, "melee")
    if finished:
        # Camp well outside the last POI's radiation, like a sane stalker.
        last = route[target]
        camp = (last.x - last.radius_m - 300, last.y)
        at_camp = math.hypot(camp[0] - p.x, camp[1] - p.y) <= 2
        p.activity = "idle" if at_camp else "walk"
        s.move_toward(*camp, dt)
        if at_camp and (v.body_temp_c < 36.0 or s.clock.is_night):
            s.light_fire()
        return
    prev = route[target - 1] if target else None
    p.underground = bool(prev and prev.kind == route[target].kind == "metro_station")
    p.activity = "jog" if v.stamina > 30 and not threats else "walk"
    s.move_toward(route[target].x, route[target].y, dt)


def main() -> None:
    parser = argparse.ArgumentParser(description="Headless Wasteland simulation")
    parser.add_argument("--hours", type=float, default=6.0)
    parser.add_argument("--seed", type=int, default=1986)
    parser.add_argument("--dt", type=float, default=1.0)
    args = parser.parse_args()
    run_demo(args.hours, args.seed, args.dt)


if __name__ == "__main__":
    main()
