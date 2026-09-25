"""Infected, mutants and ghouls with a small perception + state-machine AI.

In Unreal this logic belongs in a Behavior Tree / StateTree; the Python version
is the reference implementation used for balancing and the PIE prototype."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .combat import DamageType, Resistances


@dataclass(frozen=True)
class CreatureType:
    id: str
    name: str
    origin: str
    health: float
    damage: float
    dtype: DamageType
    speed_mps: float
    sight_m: float
    hearing_mult: float
    attack_range_m: float
    attack_cooldown: float
    resist: dict = field(default_factory=dict)
    nocturnal: bool = False         # more aggressive / invisible at night
    underground: bool = False       # Metro tunnels
    pack: tuple = (1, 1)
    xp: int = 10
    mesh_hint: str = ""


CREATURES = {c.id: c for c in (
    CreatureType("infected", "Infected", "dayz", 90, 12, DamageType.MELEE, 5.5, 35, 1.2,
                 1.6, 1.2, {"ballistic": 5}, pack=(2, 6), xp=10,
                 mesh_hint="zombie"),
    CreatureType("feral_ghoul", "Feral Ghoul", "fallout", 70, 10, DamageType.MELEE, 6.5,
                 30, 1.0, 1.5, 0.9, {"radiation": 1000}, pack=(3, 8), xp=15,
                 mesh_hint="ghoul zombie"),
    CreatureType("deathclaw", "Deathclaw", "fallout", 900, 60, DamageType.MELEE, 9.0, 60,
                 0.8, 3.0, 1.6, {"ballistic": 90, "energy": 90}, xp=300,
                 mesh_hint="horned monster"),
    CreatureType("bloodsucker", "Bloodsucker", "stalker", 350, 35, DamageType.MELEE, 8.0,
                 45, 1.0, 2.0, 1.2, {"ballistic": 20}, nocturnal=True, xp=120,
                 mesh_hint="tentacle mouth mutant"),
    CreatureType("pseudodog", "Blind Dog", "stalker", 60, 8, DamageType.MELEE, 10.0, 5,
                 2.0, 1.4, 0.8, pack=(3, 7), xp=12, mesh_hint="mutant dog"),
    CreatureType("snork", "Snork", "stalker", 120, 18, DamageType.MELEE, 7.5, 35, 1.3,
                 2.5, 1.5, {"ballistic": 10}, pack=(1, 3), xp=40,
                 mesh_hint="gas mask mutant"),
    CreatureType("nosalis", "Nosalis", "metro", 150, 20, DamageType.MELEE, 7.0, 25, 1.5,
                 1.8, 1.1, {"ballistic": 15}, underground=True, pack=(2, 6), xp=35,
                 mesh_hint="mole rat mutant"),
    CreatureType("watcher", "Watcher", "metro", 80, 12, DamageType.MELEE, 8.5, 40, 1.4,
                 1.6, 1.0, pack=(3, 6), xp=20, mesh_hint="mutant wolf"),
    CreatureType("librarian", "Librarian", "metro", 700, 45, DamageType.MELEE, 6.0, 50, 1.0,
                 2.2, 2.0, {"ballistic": 60}, underground=True, xp=250,
                 mesh_hint="ape monster"),
    CreatureType("demon", "Demon", "metro", 400, 30, DamageType.MELEE, 14.0, 120, 0.7,
                 2.5, 2.5, {"ballistic": 40}, xp=180, mesh_hint="winged monster"),
)}


class State:
    IDLE = "idle"
    WANDER = "wander"
    INVESTIGATE = "investigate"
    CHASE = "chase"
    ATTACK = "attack"
    FLEE = "flee"
    DEAD = "dead"


@dataclass
class Creature:
    type: CreatureType
    x: float
    y: float
    health: float = 0.0
    state: str = State.IDLE
    target: tuple | None = None
    cooldown: float = 0.0
    home: tuple = (0.0, 0.0)
    _think: float = 0.0

    def __post_init__(self) -> None:
        if not self.health:
            self.health = self.type.health
        self.home = (self.x, self.y)

    @property
    def alive(self) -> bool:
        return self.health > 0

    @property
    def resistances(self) -> Resistances:
        return Resistances({DamageType(k): v for k, v in self.type.resist.items()})

    def distance_to(self, x: float, y: float) -> float:
        return math.hypot(self.x - x, self.y - y)

    def can_see(self, px: float, py: float, is_night: bool, stealth: float) -> bool:
        sight = self.type.sight_m * (0.5 if is_night and not self.type.nocturnal else 1.0)
        return self.distance_to(px, py) <= sight * stealth

    def can_hear(self, px: float, py: float, noise_m: float) -> bool:
        return self.distance_to(px, py) <= noise_m * self.type.hearing_mult

    def _move_toward(self, tx: float, ty: float, speed: float, dt: float) -> None:
        d = self.distance_to(tx, ty)
        if d < 1e-6:
            return
        step = min(d, speed * dt)
        self.x += (tx - self.x) / d * step
        self.y += (ty - self.y) / d * step

    def take_hit(self, damage: float) -> None:
        self.health = max(0.0, self.health - damage)
        if not self.alive:
            self.state = State.DEAD
        elif self.health < self.type.health * 0.15 and self.type.id in (
                "pseudodog", "watcher"):
            self.state = State.FLEE          # dogs break off when badly hurt
        elif self.state in (State.IDLE, State.WANDER, State.INVESTIGATE):
            self.state = State.CHASE

    def tick(self, dt: float, player_xy: tuple, noise_m: float, is_night: bool,
             stealth: float, rng: random.Random) -> float:
        """Advance AI. Returns damage dealt to the player this tick."""
        if not self.alive:
            return 0.0
        self.cooldown = max(0.0, self.cooldown - dt)
        px, py = player_xy
        dist = self.distance_to(px, py)
        speed = self.type.speed_mps * (1.3 if is_night and self.type.nocturnal else 1.0)

        if self.state != State.FLEE:
            if self.can_see(px, py, is_night, stealth):
                self.state = State.ATTACK if dist <= self.type.attack_range_m else State.CHASE
                self.target = (px, py)
            elif self.can_hear(px, py, noise_m) and self.state not in (State.CHASE, State.ATTACK):
                self.state = State.INVESTIGATE
                self.target = (px + rng.uniform(-8, 8), py + rng.uniform(-8, 8))
            elif self.state in (State.CHASE, State.ATTACK) and dist > self.type.sight_m * 1.5:
                self.state = State.INVESTIGATE   # lost the player, search last spot

        dealt = 0.0
        if self.state == State.ATTACK:
            if dist > self.type.attack_range_m:
                self.state = State.CHASE
            elif self.cooldown == 0:
                self.cooldown = self.type.attack_cooldown
                dealt = self.type.damage
        if self.state == State.CHASE:
            self._move_toward(px, py, speed, dt)
        elif self.state == State.INVESTIGATE and self.target:
            self._move_toward(*self.target, speed * 0.5, dt)
            if self.distance_to(*self.target) < 1.0:
                self.state, self.target = State.WANDER, None
        elif self.state == State.FLEE:
            self._move_toward(2 * self.x - px, 2 * self.y - py, speed, dt)
            if dist > self.type.sight_m * 2:
                self.state = State.WANDER
        elif self.state in (State.IDLE, State.WANDER):
            self._think -= dt
            if self._think <= 0:
                self._think = rng.uniform(4, 12)
                self.state = rng.choice((State.IDLE, State.WANDER))
                self.target = (self.home[0] + rng.uniform(-30, 30),
                               self.home[1] + rng.uniform(-30, 30))
            if self.state == State.WANDER and self.target:
                self._move_toward(*self.target, speed * 0.25, dt)
        return dealt


def spawn_group(type_id: str, x: float, y: float, rng: random.Random) -> list:
    ctype = CREATURES[type_id]
    count = rng.randint(*ctype.pack)
    return [Creature(ctype, x + rng.uniform(-10, 10), y + rng.uniform(-10, 10))
            for _ in range(count)]
