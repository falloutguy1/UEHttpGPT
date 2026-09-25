"""Play-In-Editor prototype: runs the Python survival simulation against your
pawn while you playtest, drives the sun/fog/hazard post-process, and prints
a DayZ/Pip-Boy style HUD.

Editor Python does not ship in packaged games. Use this to prototype and
balance; port the systems you keep to C++/Blueprint (the DataTables from
``wasteland.datatables`` carry the numbers across).

From the editor's Python console (Output Log -> Python):

    import unreal_tools.pie_bridge as pie
    pie.start()            # then press Play
    pie.use("bandage")     # player actions while playing
    pie.search(); pie.bolt(); pie.detector(); pie.fire(); pie.talk()
    pie.stop()
"""

from __future__ import annotations

import math

import unreal

from wasteland import items
from wasteland.factions import FACTIONS
from wasteland.game import GameSession
from wasteland.terrain import Terrain, landscape_scale

from .level_builder import METRO_DEPTH_UU

# One in-game day per 120 real minutes, like DayZ's default server settings.
TIME_SCALE = 12.0
HUD_INTERVAL = 0.25


class Bridge:
    def __init__(self, seed: int = 1986, time_scale: float = TIME_SCALE,
                 landscape_size: int = 1009, height_range_m: float = 400.0):
        # Must match the LevelBuilder / terrain settings the map was built with.
        self.seed = seed
        self.landscape_size = landscape_size
        self.height_range_m = height_range_m
        self.terrain: Terrain | None = None
        self.z_scale = 0.0
        self.time_scale = time_scale
        self.session: GameSession | None = None
        self.handle = None
        self._hud_timer = 0.0
        self._log_seen = 0
        self._cache = {}

    # -- Lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        if self.handle is None:
            self.handle = unreal.register_slate_post_tick_callback(self._tick)
            unreal.log("Wasteland PIE bridge armed - press Play.")

    def stop(self) -> None:
        if self.handle is not None:
            unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        self.session = None

    # -- Frame --------------------------------------------------------------------------
    def _game_world(self):
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()

    def _tick(self, delta: float) -> None:
        world = self._game_world()
        if world is None:
            if self.session is not None:          # PIE ended: reset for next run
                self.session, self._cache = None, {}
            return
        pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
        if pawn is None:
            return
        if self.session is None:
            self.session = GameSession(self.seed)
            self.terrain = Terrain(self.session.world)
            self.z_scale = landscape_scale(self.session.world, self.landscape_size,
                                           self.height_range_m)[2]
            self._log_seen = 0
            self._cache = {}
            self._say(world, "You wake up on the coast. Find water. Trust no one.", 6.0)

        s, p = self.session, self.session.player
        half = s.world.size_m / 2
        loc = pawn.get_actor_location()
        p.x, p.y = loc.x / 100.0 + half, loc.y / 100.0 + half
        surface = self.terrain.height_uu(p.x, p.y, self.z_scale)
        p.underground = loc.z < surface - METRO_DEPTH_UU * 0.5
        speed = pawn.get_velocity().length() / 100.0
        try:
            crouched = bool(pawn.get_editor_property("is_crouched"))
        except Exception:     # not a Character
            crouched = False
        p.activity = ("idle" if speed < 0.2 else "crouch" if crouched else
                      "walk" if speed < 2.5 else "jog" if speed < 5.0 else "sprint")

        s.tick(min(delta, 0.1) * self.time_scale)
        self._apply_world_state(world)

        for line in s.log[self._log_seen:]:
            self._say(world, line.split("] ", 1)[-1], 5.0, unreal.LinearColor(1.0, 0.8, 0.3, 1.0))
        self._log_seen = len(s.log)

        self._hud_timer -= delta
        if self._hud_timer <= 0:
            self._hud_timer = HUD_INTERVAL
            self._draw_hud(world)

        if not p.vitals.alive:
            self._say(world, "YOU ARE DEAD", 5.0, unreal.LinearColor(1, 0, 0, 1))
            unreal.SystemLibrary.execute_console_command(world, "RestartLevel")
            self.session = None

    def _actors(self, world, tag: str) -> list:
        if tag not in self._cache:
            self._cache[tag] = list(unreal.GameplayStatics.get_all_actors_with_tag(world, tag))
        return self._cache[tag]

    def _apply_world_state(self, world) -> None:
        s, p = self.session, self.session.player
        for sun in self._actors(world, "Wasteland.Sun"):
            sun.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=s.clock.sun_pitch_deg,
                                                  yaw=40.0), False)
        for fog in self._actors(world, "Wasteland.Fog"):
            fog.component.set_fog_density(s.weather.fog_density)

        env = s.world.environment_at(p.x, p.y, s.clock, s.weather, p.underground)
        weights = {
            "Wasteland.PP.Toxic": 1.0 if env.toxic_air and not p.mask.protecting else
            0.35 if env.toxic_air else 0.0,
            "Wasteland.PP.Radiation": min(1.0, env.rads_per_sec / 2.0 + p.radiation.rads / 1000.0),
            "Wasteland.PP.Emission": {"idle": 0.0, "warning": 0.4, "active": 1.0}[s.emission.state],
            "Wasteland.PP.Underground": 1.0 if p.underground else 0.0,
        }
        for tag, weight in weights.items():
            for ppv in self._actors(world, tag):
                ppv.set_editor_property("blend_weight", weight)

        # Metro lamps flicker, more so during an emission.
        chance = 0.02 if s.emission.state == "idle" else 0.25
        for lamp in self._actors(world, "Wasteland.Flicker"):
            lamp.light_component.set_visibility(s.rng.random() > chance, False)

    def _draw_hud(self, world) -> None:
        h = self.session.hud()
        bars = (f"HP {h['health']}/{h['max_health']}  BLOOD {h['blood']}  "
                f"FOOD {h['energy']}%  WATER {h['water']}%  TEMP {h['temp_c']}C  "
                f"STAM {h['stamina']}")
        rads = f"RADS {h['rads']}  GEIGER {h['geiger_cps']}/s"
        mask = f"  FILTER {h['filter_sec']}s" if h["filter_sec"] is not None else ""
        where = f"{h['time']}  {h['weather']}  {h['location']}  LVL {h['level']} {h['karma']}"
        status = ("  [" + ", ".join(h["status"]) + "]") if h["status"] else ""
        emission = "  !! EMISSION !!" if h["emission"] != "idle" else ""
        text = f"{where}\n{bars}\n{rads}{mask}{status}{emission}"
        self._say(world, text, HUD_INTERVAL + 0.05, unreal.LinearColor(0.3, 1.0, 0.4, 1.0),
                  key="WastelandHUD")

    @staticmethod
    def _say(world, text: str, duration: float,
             color: unreal.LinearColor = unreal.LinearColor(1, 1, 1, 1), key: str = "") -> None:
        kwargs = dict(print_to_screen=True, print_to_log=not key, text_color=color,
                      duration=duration)
        if key:
            kwargs["key"] = key     # replaces the previous HUD line (UE 5.x)
        try:
            unreal.SystemLibrary.print_string(world, text, **kwargs)
        except TypeError:
            kwargs.pop("key", None)
            unreal.SystemLibrary.print_string(world, text, **kwargs)


_bridge = Bridge()


def start(seed: int = 1986, landscape_size: int = 1009, height_range_m: float = 400.0) -> None:
    _bridge.seed = seed
    _bridge.landscape_size = landscape_size
    _bridge.height_range_m = height_range_m
    _bridge.start()


def stop() -> None:
    _bridge.stop()


def _session() -> GameSession:
    if _bridge.session is None:
        raise RuntimeError("Not playing - run pie.start() and press Play first.")
    return _bridge.session


def use(item_id: str) -> bool:
    return _session().use_item(item_id)


def give(item_id: str, quantity: int = 1) -> bool:
    """Debug: spawn an item into the inventory (wearing it if the slot is free)."""
    return _session().player.inventory.pick_up(items.make(item_id, quantity))


def search() -> list:
    return [f"{st.quantity}x {st.item.name}" for st in _session().search_nearby()]


def fire() -> bool:
    return _session().light_fire()


def bolt(distance_m: float = 8.0) -> list:
    """Throw a bolt straight ahead of the camera and report what it triggered."""
    s = _session()
    world = _bridge._game_world()
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    yaw = math.radians(pawn.get_control_rotation().yaw) if pawn else 0.0
    p = s.player
    if not p.inventory.take("bolt"):
        return ["No bolts left."]
    target = (p.x + math.cos(yaw) * distance_m, p.y + math.sin(yaw) * distance_m)
    poi = s.world.poi_at(*target)
    hits = poi.anomaly_field.throw_bolt((p.x, p.y), target) if poi and poi.anomaly_field else []
    return [f"The bolt sets off a {a.type.name}!" for a in hits] or ["The bolt lands quietly."]


def detector() -> dict | None:
    s = _session()
    p = s.player
    poi = s.world.poi_at(p.x, p.y)
    tool = "detector_bear" if p.inventory.count("detector_bear") else \
        "detector_echo" if p.inventory.count("detector_echo") else None
    if not tool or not poi or not poi.anomaly_field:
        return None
    eff = items.get(tool).effects
    return poi.anomaly_field.detector_ping(p.x, p.y, eff["artifact_range_m"],
                                           eff["shows_direction"])


def pickup_artifact() -> str | None:
    s = _session()
    p = s.player
    poi = s.world.poi_at(p.x, p.y)
    if not poi or not poi.anomaly_field:
        return None
    art = poi.anomaly_field.pick_up(p.x, p.y)
    if art:
        p.inventory.equip(items.make(art))
        p.progression.add_xp(50)
    return art


def talk(faction_id: str | None = None) -> str:
    """Returns the system prompt for an NPC of the nearest POI's faction. Feed it
    to HttpGPT's "Send Messages with Default Options" Blueprint node as the
    System message, followed by the player's line as a User message."""
    s = _session()
    p = s.player
    poi = s.world.poi_at(p.x, p.y)
    faction_id = faction_id or (poi.faction if poi else None) or "survivors"
    if faction_id not in FACTIONS:
        raise KeyError(f"unknown faction {faction_id}")
    return p.reputation.dialogue_prompt(faction_id, p.name, p.progression.karma_title)


def status() -> dict:
    return _session().hud()
