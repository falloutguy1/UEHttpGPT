"""S.T.A.L.K.E.R. anomalies, bolts, detectors, artifacts and emissions."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .combat import DamageType
from .config import WORLD
from .items import ITEMS, Category


@dataclass(frozen=True)
class AnomalyType:
    id: str
    name: str
    dtype: DamageType
    radius_m: float
    damage: float              # per trigger
    cooldown_sec: float
    visible: float             # 0 = invisible without bolt/detector, 1 = obvious
    vfx_hint: str              # Niagara system name to spawn in UE
    light_rgb: tuple           # point light colour for the placeholder


ANOMALY_TYPES = {a.id: a for a in (
    AnomalyType("vortex", "Vortex", DamageType.GRAVITY, 4.0, 120, 6.0, 0.2,
                "NS_Anomaly_Vortex", (0.6, 0.6, 0.9)),
    AnomalyType("springboard", "Springboard", DamageType.GRAVITY, 2.5, 35, 2.0, 0.3,
                "NS_Anomaly_Springboard", (0.7, 0.7, 1.0)),
    AnomalyType("burner", "Burner", DamageType.FIRE, 2.0, 45, 3.0, 0.1,
                "NS_Anomaly_Burner", (1.0, 0.45, 0.1)),
    AnomalyType("electro", "Electro", DamageType.ELECTRIC, 3.5, 50, 2.5, 0.8,
                "NS_Anomaly_Electro", (0.4, 0.7, 1.0)),
    AnomalyType("fruit_punch", "Fruit Punch", DamageType.CHEMICAL, 2.0, 20, 1.0, 0.9,
                "NS_Anomaly_FruitPunch", (0.4, 1.0, 0.2)),
    AnomalyType("whirligig", "Whirligig", DamageType.GRAVITY, 3.0, 60, 4.0, 0.4,
                "NS_Anomaly_Whirligig", (0.8, 0.8, 0.8)),
)}


@dataclass
class Anomaly:
    type: AnomalyType
    x: float
    y: float
    cooldown: float = 0.0
    revealed_sec: float = 0.0     # bolts reveal anomalies for a while

    def distance(self, x: float, y: float) -> float:
        return math.hypot(self.x - x, self.y - y)

    def contains(self, x: float, y: float) -> bool:
        return self.distance(x, y) <= self.type.radius_m

    def tick(self, dt: float) -> None:
        self.cooldown = max(0.0, self.cooldown - dt)
        self.revealed_sec = max(0.0, self.revealed_sec - dt)

    def trigger(self) -> float:
        """Fire the anomaly. Returns damage dealt (0 if still recharging)."""
        if self.cooldown > 0:
            return 0.0
        self.cooldown = self.type.cooldown_sec
        return self.type.damage


@dataclass
class ArtifactSpawn:
    item_id: str
    x: float
    y: float


@dataclass
class AnomalyField:
    """A cluster of anomalies of mostly one type, with artifacts inside."""
    name: str
    center: tuple
    radius_m: float
    anomalies: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)

    @classmethod
    def generate(cls, name: str, center: tuple, radius_m: float,
                 rng: random.Random, density: float = 0.004) -> "AnomalyField":
        area = math.pi * radius_m ** 2
        count = max(3, int(area * density))
        dominant = rng.choice(list(ANOMALY_TYPES.values()))
        fld = cls(name, center, radius_m)
        for _ in range(count):
            atype = dominant if rng.random() < 0.7 else \
                rng.choice(list(ANOMALY_TYPES.values()))
            fld.anomalies.append(Anomaly(atype, *fld._random_point(rng)))
        fld.respawn_artifacts(rng)
        return fld

    def _random_point(self, rng: random.Random) -> tuple:
        r = self.radius_m * math.sqrt(rng.random())
        a = rng.random() * math.tau
        return self.center[0] + r * math.cos(a), self.center[1] + r * math.sin(a)

    def respawn_artifacts(self, rng: random.Random, max_count: int = 3) -> None:
        """Artifacts form next to the anomaly type that 'grows' them."""
        by_anomaly = {}
        for item in ITEMS.values():
            if item.category is Category.ARTIFACT:
                by_anomaly.setdefault(item.effects.get("anomaly"), []).append(item.id)
        self.artifacts.clear()
        for anomaly in rng.sample(self.anomalies, min(max_count, len(self.anomalies))):
            candidates = by_anomaly.get(anomaly.type.id)
            if candidates:
                offset = anomaly.type.radius_m * 0.6
                self.artifacts.append(ArtifactSpawn(
                    rng.choice(candidates), anomaly.x + offset, anomaly.y))

    def shuffle(self, rng: random.Random) -> None:
        """After an emission, anomalies drift and artifacts regrow."""
        for anomaly in self.anomalies:
            anomaly.x, anomaly.y = self._random_point(rng)
        self.respawn_artifacts(rng)

    def throw_bolt(self, from_xy: tuple, to_xy: tuple, reveal_sec: float = 20.0) -> list:
        """A bolt lands at ``to_xy``; anomalies it lands in trigger (harmlessly)
        and become visible."""
        hit = [a for a in self.anomalies if a.contains(*to_xy)]
        for anomaly in hit:
            anomaly.trigger()
            anomaly.revealed_sec = reveal_sec
        return hit

    def detector_ping(self, x: float, y: float, range_m: float,
                      directional: bool) -> dict | None:
        """What a handheld detector shows: nearest artifact distance, and a
        bearing if the detector supports it."""
        best = None
        for art in self.artifacts:
            d = math.hypot(art.x - x, art.y - y)
            if d <= range_m and (best is None or d < best[0]):
                best = (d, art)
        if best is None:
            return None
        d, art = best
        result = {"distance_m": round(d, 1), "beep_hz": round(1.0 + 9.0 * (1 - d / range_m), 2)}
        if directional:
            result["bearing_deg"] = round(math.degrees(math.atan2(art.y - y, art.x - x)) % 360, 1)
        return result

    def pick_up(self, x: float, y: float, reach_m: float = 1.5) -> str | None:
        for art in self.artifacts:
            if math.hypot(art.x - x, art.y - y) <= reach_m:
                self.artifacts.remove(art)
                return art.item_id
        return None


class Emission:
    """The Blowout: periodic psy-storm that kills anyone not under a roof,
    then reshuffles the anomaly fields."""

    IDLE, WARNING, ACTIVE = "idle", "warning", "active"

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.state = self.IDLE
        self.timer = self._next_interval()

    def _next_interval(self) -> float:
        lo, hi = WORLD.emission_interval_hours
        return self.rng.uniform(lo, hi) * 3600.0

    def tick(self, dt: float) -> list:
        events = []
        self.timer -= dt
        while self.timer <= 0:
            if self.state == self.IDLE:
                self.state = self.WARNING
                self.timer += WORLD.emission_warning_sec
                events.append("emission_warning")
            elif self.state == self.WARNING:
                self.state = self.ACTIVE
                self.timer += WORLD.emission_duration_sec
                events.append("emission_start")
            else:
                self.state = self.IDLE
                self.timer += self._next_interval()
                events.append("emission_end")
        return events

    def damage_per_sec(self, sheltered: bool) -> float:
        if self.state == self.ACTIVE and not sheltered:
            return WORLD.emission_damage_per_sec
        return 0.0
