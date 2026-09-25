"""Environmental hazards that aren't anomalies: radiation (Fallout) and toxic
air + gas masks (Metro)."""

from __future__ import annotations

from dataclasses import dataclass

from .config import GAS_MASK, RADIATION


@dataclass
class Radiation:
    rads: float = 0.0
    resist_buff: float = 0.0          # Rad-X
    resist_buff_sec: float = 0.0

    def tick(self, dt: float, rads_per_sec: float, resistance: float) -> float:
        """Accumulate radiation. ``resistance`` is 0..1 from gear/perks.
        Returns rads gained this tick."""
        if self.resist_buff_sec > 0:
            self.resist_buff_sec = max(0.0, self.resist_buff_sec - dt)
            if self.resist_buff_sec == 0:
                self.resist_buff = 0.0
        total_resist = min(0.95, resistance + self.resist_buff)
        gained = max(0.0, rads_per_sec) * (1.0 - total_resist) * dt
        self.rads = min(RADIATION.max_rads, self.rads + gained)
        self.rads = max(0.0, self.rads - RADIATION.natural_decay_per_hour * dt / 3600.0)
        return gained

    def add(self, amount: float) -> None:
        self.rads = max(0.0, min(RADIATION.max_rads, self.rads + amount))

    def max_health_cap(self, base_max: float) -> float:
        lost = base_max * self.rads * RADIATION.max_hp_loss_per_rad / 100.0
        return max(base_max * RADIATION.min_max_hp_fraction, base_max - lost)

    @property
    def sick(self) -> bool:
        return self.rads >= RADIATION.sickness_threshold

    @staticmethod
    def geiger_rate(rads_per_sec: float) -> float:
        """Clicks/sec for the Geiger counter audio: background clicks plus a
        rate that saturates at ~40 clicks/sec."""
        return 0.3 + 40.0 * (1.0 - 1.0 / (1.0 + rads_per_sec * 2.0))


@dataclass
class GasMask:
    """Metro's GP-5: a mask, a filter timer and a visor that cracks."""
    equipped: bool = False
    integrity: float = 1.0            # visor; replace the mask when it's gone
    filter_sec: float = 0.0
    fogged: float = 0.0               # condensation, wipe to clear

    def insert_filter(self, seconds: float = GAS_MASK.filter_duration_sec) -> None:
        # Swapping filters discards what's left of the old one, like Metro.
        self.filter_sec = seconds

    def damage(self, amount: float) -> None:
        self.integrity = max(0.0, self.integrity - amount)

    def wipe(self) -> None:
        self.fogged = 0.0

    @property
    def cracked(self) -> bool:
        return self.integrity < GAS_MASK.visor_crack_threshold

    @property
    def protecting(self) -> bool:
        return self.equipped and self.integrity > 0 and self.filter_sec > 0

    def tick(self, dt: float, toxic: bool, exertion: float = 1.0,
             filter_mult: float = 1.0) -> tuple:
        """Returns (suffocation_damage, events)."""
        events = []
        if not toxic:
            return 0.0, events
        if self.equipped and self.integrity > 0 and self.filter_sec > 0:
            burn = dt * exertion / filter_mult
            if self.cracked:
                burn *= GAS_MASK.leak_multiplier
            before = self.filter_sec
            self.filter_sec = max(0.0, self.filter_sec - burn)
            self.fogged = min(1.0, self.fogged + 0.002 * dt * exertion)
            for mark in (60.0, 30.0):
                if before > mark >= self.filter_sec:
                    events.append(f"Filter: {int(mark)} seconds left.")
            if self.filter_sec == 0:
                events.append("Your filter is spent - you start to choke!")
            return 0.0, events
        return GAS_MASK.suffocation_damage_per_sec * dt, events
