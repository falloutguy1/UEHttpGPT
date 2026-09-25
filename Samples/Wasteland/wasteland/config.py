"""Global tunables. Everything balance-related lives here so designers can tweak
numbers without touching system code (and so DataTables can be regenerated)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SurvivalTuning:
    # DayZ-style resources, expressed as percentages (0-100) for readability.
    energy_drain_per_hour: float = 4.0          # at rest
    water_drain_per_hour: float = 6.0           # at rest
    activity_multipliers: dict = field(default_factory=lambda: {
        "idle": 0.6, "walk": 1.0, "jog": 1.8, "sprint": 3.0, "crouch": 0.9,
    })
    starvation_damage_per_hour: float = 12.0
    dehydration_damage_per_hour: float = 20.0

    max_blood: float = 5000.0
    blood_regen_per_hour: float = 300.0         # only while fed and hydrated
    bleed_rate_per_source_per_sec: float = 1.6  # ml/s per open wound
    low_blood_threshold: float = 3000.0         # desaturated vision, health loss
    unconscious_shock: float = 90.0
    shock_recovery_per_sec: float = 2.0

    comfortable_temp_c: float = 36.6
    hypothermia_c: float = 35.0
    hyperthermia_c: float = 38.5
    temp_damage_per_hour: float = 15.0
    temp_response_per_hour: float = 3.0         # how quickly body temp chases target

    stamina_max: float = 100.0
    stamina_regen_per_sec: float = 12.0
    stamina_cost_per_sec: dict = field(default_factory=lambda: {
        "sprint": 10.0, "jog": 2.0,
    })


@dataclass(frozen=True)
class RadiationTuning:
    max_rads: float = 1000.0
    # Fallout 4: every 10 rads removes 1% max HP. We keep a floor so rads can't
    # delete the player outright; radiation sickness does the killing instead.
    max_hp_loss_per_rad: float = 0.1
    min_max_hp_fraction: float = 0.05
    sickness_threshold: float = 600.0
    sickness_damage_per_hour: float = 10.0
    natural_decay_per_hour: float = 0.0         # rads don't wear off on their own


@dataclass(frozen=True)
class GasMaskTuning:
    filter_duration_sec: float = 300.0          # Metro's classic five-minute filter
    suffocation_damage_per_sec: float = 4.0
    visor_crack_threshold: float = 0.35         # integrity below this leaks
    leak_multiplier: float = 3.0                # filter burn rate when cracked


@dataclass(frozen=True)
class WorldTuning:
    day_length_minutes: float = 120.0           # real minutes per in-game day
    emission_interval_hours: tuple = (36.0, 72.0)
    emission_warning_sec: float = 120.0
    emission_duration_sec: float = 90.0
    emission_damage_per_sec: float = 25.0
    map_size_km: float = 16.0                   # Chernarus-ish footprint
    cell_size_m: float = 500.0


SURVIVAL = SurvivalTuning()
RADIATION = RadiationTuning()
GAS_MASK = GasMaskTuning()
WORLD = WorldTuning()
