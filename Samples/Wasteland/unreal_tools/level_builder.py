"""Blocks out the Wasteland map in the open Unreal level from ``WorldLayout``.

Everything spawned is a placeholder you can swap for real art later (the
materials come from ``ue_import``): buildings are cubes wearing the right
material instance, anomalies are coloured lights (plus Niagara systems if you
have them), metro stations are underground platforms, and loot/creature spawns
are tagged Target Points your Blueprints can query with
``Get All Actors With Tag``.

Coordinates: world metres (0..size) map to Unreal units centred on the origin,
matching a Landscape imported from ``wasteland.terrain`` with the scale it
prints. Z snaps to that terrain.
"""

from __future__ import annotations

import math

import unreal

from wasteland.terrain import Terrain, landscape_scale
from wasteland.world import POI, WorldLayout

from .ue_import import MAT_ROOT

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
eal = unreal.EditorAssetLibrary

CUBE = "/Engine/BasicShapes/Cube.Cube"
CYLINDER = "/Engine/BasicShapes/Cylinder.Cylinder"
FALLBACK_MAT = "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"
FX_ROOT = "/Game/Wasteland/FX"

# POI kind -> material instance slot for its buildings
KIND_MATERIAL = {
    "village": "Brick", "farm": "WoodPlanks", "town": "Concrete", "military": "ConcreteDirty",
    "ruins": "Concrete", "industrial": "RustMetal", "metro_station": "Tiles",
    "vault": "MetalPlate", "crater": "BurntGround", "reactor": "ConcreteDirty",
    "anomaly_field": "Mud",
}

METRO_DEPTH_UU = 3000.0      # platforms sit 30 m under the surface


class LevelBuilder:
    def __init__(self, seed: int = 1986, height_range_m: float = 400.0,
                 landscape_size: int = 1009):
        self.world = WorldLayout(seed)
        self.terrain = Terrain(self.world)
        self.z_scale = landscape_scale(self.world, landscape_size, height_range_m)[2]
        self.cube = eal.load_asset(CUBE)
        self.cylinder = eal.load_asset(CYLINDER)
        self._materials = {}
        self.spawned = 0

    # -- Helpers ------------------------------------------------------------------------
    def to_uu(self, x: float, y: float, z_offset_uu: float = 0.0) -> unreal.Vector:
        half = self.world.size_m / 2
        z = self.terrain.height_uu(x, y, self.z_scale) + z_offset_uu
        return unreal.Vector((x - half) * 100.0, (y - half) * 100.0, z)

    def material(self, slot: str):
        if slot not in self._materials:
            path = f"{MAT_ROOT}/MI_{slot}"
            self._materials[slot] = eal.load_asset(path) if eal.does_asset_exist(path) \
                else eal.load_asset(FALLBACK_MAT)
        return self._materials[slot]

    def _finish(self, actor, label: str, folder: str, tags: list) -> None:
        actor.set_actor_label(label)
        actor.set_folder_path(f"Wasteland/{folder}")
        actor.set_editor_property("tags", [unreal.Name(t) for t in tags])
        self.spawned += 1

    def box(self, loc: unreal.Vector, size_m: tuple, yaw: float, slot: str, label: str,
            folder: str, tags: list, mesh=None, pitch: float = 0.0):
        actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, loc,
                                           unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw))
        comp = actor.static_mesh_component
        comp.set_static_mesh(mesh or self.cube)
        comp.set_material(0, self.material(slot))
        comp.set_mobility(unreal.ComponentMobility.STATIC)
        # Basic shapes are 100 UU cubes pivoted at their centre.
        actor.set_actor_scale3d(unreal.Vector(size_m[0], size_m[1], size_m[2]))
        self._finish(actor, label, folder, tags)
        return actor

    def light(self, loc: unreal.Vector, rgb: tuple, intensity: float, radius_m: float,
              label: str, folder: str, tags: list):
        actor = eas.spawn_actor_from_class(unreal.PointLight, loc)
        comp = actor.light_component
        comp.set_light_color(unreal.LinearColor(*rgb, 1.0))
        comp.set_intensity(intensity)
        comp.set_attenuation_radius(radius_m * 100.0)
        self._finish(actor, label, folder, tags)
        return actor

    def marker(self, loc: unreal.Vector, label: str, folder: str, tags: list):
        actor = eas.spawn_actor_from_class(unreal.TargetPoint, loc)
        self._finish(actor, label, folder, tags)
        return actor

    # -- Build steps --------------------------------------------------------------------
    def build(self, lighting: bool = True, sky_cubemap=None) -> int:
        with unreal.ScopedEditorTransaction("Build Wasteland"):
            with unreal.ScopedSlowTask(len(self.world.pois) + 3, "Building Wasteland") as task:
                task.make_dialog(True)
                if lighting:
                    task.enter_progress_frame(1, "Sky, sun and fog")
                    self.build_lighting(sky_cubemap)
                task.enter_progress_frame(1, "Hazard post-process")
                self.build_hazard_volumes()
                task.enter_progress_frame(1, "Roads")
                self.build_roads()
                for poi in self.world.pois:
                    if task.should_cancel():
                        break
                    task.enter_progress_frame(1, f"{poi.kind}: {poi.name}")
                    self.build_poi(poi)
                self.build_player_start()
        unreal.log(f"Wasteland: spawned {self.spawned} actors for seed {self.world.seed}")
        return self.spawned

    def build_lighting(self, sky_cubemap=None) -> None:
        sun = eas.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 50000),
                                         unreal.Rotator(roll=0.0, pitch=-35.0, yaw=40.0))
        sun_comp = sun.light_component
        sun_comp.set_editor_property("atmosphere_sun_light", True)
        sun_comp.set_intensity(6.0)
        sun_comp.set_light_color(unreal.LinearColor(1.0, 0.93, 0.82, 1.0))
        sun_comp.set_mobility(unreal.ComponentMobility.MOVABLE)
        self._finish(sun, "Sun", "Lighting", ["Wasteland.Sun"])

        atmo = eas.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
        self._finish(atmo, "SkyAtmosphere", "Lighting", [])

        sky = eas.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 60000))
        sky_comp = sky.light_component
        sky_comp.set_mobility(unreal.ComponentMobility.MOVABLE)
        if sky_cubemap is not None:
            sky_comp.set_editor_property("source_type",
                                         unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
            sky_comp.set_editor_property("cubemap", sky_cubemap)
        else:
            sky_comp.set_editor_property("real_time_capture", True)
        self._finish(sky, "SkyLight", "Lighting", ["Wasteland.SkyLight"])

        fog = eas.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
        fog_comp = fog.component
        fog_comp.set_editor_property("fog_density", 0.03)
        fog_comp.set_editor_property("fog_inscattering_luminance",
                                     unreal.LinearColor(0.35, 0.38, 0.36, 1.0))
        fog_comp.set_editor_property("enable_volumetric_fog", True)
        self._finish(fog, "HeightFog", "Lighting", ["Wasteland.Fog"])

        cloud = eas.spawn_actor_from_class(unreal.VolumetricCloud, unreal.Vector(0, 0, 0))
        self._finish(cloud, "VolumetricCloud", "Lighting", [])

    def _ppv(self, label: str, tag: str, **overrides) -> None:
        """Unbound post-process volumes at blend weight 0. The PIE bridge (or
        your Blueprint) raises the weight when the hazard applies."""
        ppv = eas.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0))
        settings = ppv.get_editor_property("settings")
        for prop, value in overrides.items():
            settings.set_editor_property(f"override_{prop}", True)
            settings.set_editor_property(prop, value)
        ppv.set_editor_property("settings", settings)
        ppv.set_editor_property("unbound", True)
        ppv.set_editor_property("blend_weight", 0.0)
        self._finish(ppv, label, "Hazards", [tag])

    def build_hazard_volumes(self) -> None:
        self._ppv("PP_ToxicAir", "Wasteland.PP.Toxic",
                  color_saturation=unreal.Vector4(0.6, 0.75, 0.55, 1.0),
                  scene_color_tint=unreal.LinearColor(0.85, 1.0, 0.75, 1.0),
                  vignette_intensity=0.9)
        self._ppv("PP_Radiation", "Wasteland.PP.Radiation",
                  film_grain_intensity=0.8, vignette_intensity=0.7,
                  scene_color_tint=unreal.LinearColor(1.0, 1.0, 0.8, 1.0))
        self._ppv("PP_Emission", "Wasteland.PP.Emission",
                  scene_color_tint=unreal.LinearColor(1.0, 0.45, 0.35, 1.0),
                  color_contrast=unreal.Vector4(1.3, 1.1, 1.1, 1.0),
                  film_grain_intensity=0.5)
        self._ppv("PP_Underground", "Wasteland.PP.Underground",
                  auto_exposure_bias=1.5,
                  scene_color_tint=unreal.LinearColor(1.0, 0.9, 0.75, 1.0))

    def build_roads(self, piece_m: float = 150.0) -> None:
        for i, ((x1, y1), (x2, y2)) in enumerate(self.world.roads):
            length = math.hypot(x2 - x1, y2 - y1)
            yaw = math.degrees(math.atan2(y2 - y1, x2 - x1))
            pieces = max(1, int(length // piece_m))
            for j in range(pieces):
                t0, t1 = j / pieces, (j + 1) / pieces
                ax, ay = x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0
                bx, by = x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1
                za = self.terrain.height_uu(ax, ay, self.z_scale)
                zb = self.terrain.height_uu(bx, by, self.z_scale)
                seg = length / pieces
                pitch = math.degrees(math.atan2(zb - za, seg * 100.0))
                mid = self.to_uu((ax + bx) / 2, (ay + by) / 2, 10.0)
                self.box(mid, (seg * 1.02, 7.0, 0.2), yaw, "Asphalt",
                         f"Road_{i:03d}_{j:02d}", "Roads", ["Wasteland.Road"], pitch=pitch)

    def build_poi(self, poi: POI) -> None:
        folder = f"POI/{poi.kind}/{poi.name}"
        base_tags = [f"Wasteland.POI.{poi.kind}", f"Wasteland.Name.{poi.name}"]
        centre = self.to_uu(poi.x, poi.y, 200.0)

        label = eas.spawn_actor_from_class(unreal.TextRenderActor, centre + unreal.Vector(0, 0, 3000))
        label.text_render.set_editor_property("text", f"{poi.name} ({poi.kind})")
        label.text_render.set_editor_property("world_size", 800.0)
        label.text_render.set_editor_property("horizontal_alignment",
                                              unreal.HorizTextAligment.EHTA_CENTER)
        label.set_actor_hidden_in_game(True)
        self._finish(label, f"Label_{poi.name}", folder, base_tags)

        slot = KIND_MATERIAL.get(poi.kind, "Concrete")
        for i, (bx, by, w, d, h, rot) in enumerate(poi.buildings):
            # Sink 1 m into the ground so slopes don't leave gaps.
            loc = self.to_uu(bx, by, (h / 2 - 1.0) * 100.0)
            self.box(loc, (w, d, h), rot, slot, f"{poi.name}_Bldg_{i:02d}", folder,
                     base_tags + ["Wasteland.Building"])

        for i, (lx, ly) in enumerate(poi.loot_spots):
            self.marker(self.to_uu(lx, ly, 100.0), f"{poi.name}_Loot_{i:02d}", folder,
                        base_tags + ["Wasteland.Loot", f"Wasteland.Loot.{poi.loot_table}"])

        for i, creature in enumerate(poi.creatures):
            angle = i / max(1, len(poi.creatures)) * math.tau
            sx = poi.x + math.cos(angle) * poi.radius_m * 0.6
            sy = poi.y + math.sin(angle) * poi.radius_m * 0.6
            z = -METRO_DEPTH_UU + 150 if poi.underground and creature in ("nosalis", "librarian") \
                else 150.0
            self.marker(self.to_uu(sx, sy, z), f"{poi.name}_Spawn_{creature}", folder,
                        base_tags + ["Wasteland.Spawn", f"Wasteland.Spawn.{creature}"])

        if poi.faction:
            self.marker(centre, f"{poi.name}_Faction_{poi.faction}", folder,
                        base_tags + [f"Wasteland.Faction.{poi.faction}"])

        if poi.kind == "metro_station":
            self.build_metro_station(poi, folder, base_tags)
        elif poi.kind == "vault":
            self.build_vault(poi, folder, base_tags)
        if poi.anomaly_field:
            self.build_anomalies(poi, folder, base_tags)

    def build_metro_station(self, poi: POI, folder: str, tags: list) -> None:
        """Surface pavilion + a platform hall 30 m down + tunnel mouths."""
        tags = tags + ["Wasteland.Metro"]
        self.box(self.to_uu(poi.x, poi.y, 250.0), (10, 10, 5), 0, "Concrete",
                 f"{poi.name}_Entrance", folder, tags + ["Wasteland.Metro.Entrance"])
        depth = -METRO_DEPTH_UU
        hall = (80.0, 20.0, 7.0)
        floor = self.to_uu(poi.x, poi.y, depth)
        self.box(floor, (hall[0], hall[1], 0.5), 0, "Tiles", f"{poi.name}_Floor", folder, tags)
        self.box(floor + unreal.Vector(0, 0, hall[2] * 100), (hall[0], hall[1], 0.5), 0,
                 "ConcreteDirty", f"{poi.name}_Ceiling", folder, tags)
        for side in (-1, 1):
            wall = floor + unreal.Vector(0, side * hall[1] * 50, hall[2] * 50)
            self.box(wall, (hall[0], 0.5, hall[2]), 0, "Tiles", f"{poi.name}_Wall_{side}",
                     folder, tags)
            # Tunnels leave from both ends of the platform.
            mouth = floor + unreal.Vector(side * (hall[0] * 50 + 5000), 0, 0)
            self.box(mouth, (100.0, 6.0, 0.4), 0, "Gravel", f"{poi.name}_Tunnel_{side}",
                     folder, tags + ["Wasteland.Metro.Tunnel"])
        for i in range(6):   # warm, flickery Metro lamps
            x_off = (i - 2.5) * hall[0] * 100 / 6
            self.light(floor + unreal.Vector(x_off, 0, hall[2] * 90), (1.0, 0.7, 0.4), 2500.0,
                       14.0, f"{poi.name}_Lamp_{i}", folder, tags + ["Wasteland.Flicker"])
        self.marker(floor + unreal.Vector(0, 0, 150), f"{poi.name}_SafeZone", folder,
                    tags + ["Wasteland.SafeZone", f"Wasteland.Trader.{poi.faction}"])

    def build_vault(self, poi: POI, folder: str, tags: list) -> None:
        tags = tags + ["Wasteland.Vault"]
        door = self.to_uu(poi.x, poi.y, 500.0)
        self.box(door, (10, 10, 1.5), 0, "MetalPlate", f"{poi.name}_GearDoor", folder,
                 tags + ["Wasteland.Vault.Door"], mesh=self.cylinder, pitch=90.0)
        atrium = self.to_uu(poi.x, poi.y, -2000.0)
        self.box(atrium, (40, 40, 0.5), 0, "MetalPlate", f"{poi.name}_Atrium", folder, tags)
        self.light(atrium + unreal.Vector(0, 0, 500), (0.75, 0.9, 1.0), 5000.0, 30.0,
                   f"{poi.name}_Light", folder, tags)

    def build_anomalies(self, poi: POI, folder: str, tags: list) -> None:
        for i, anomaly in enumerate(poi.anomaly_field.anomalies):
            atype = anomaly.type
            loc = self.to_uu(anomaly.x, anomaly.y, 100.0)
            a_tags = tags + ["Wasteland.Anomaly", f"Wasteland.Anomaly.{atype.id}"]
            self.light(loc, atype.light_rgb, 800.0 + 2000.0 * atype.visible,
                       atype.radius_m * 2, f"{poi.name}_{atype.name}_{i:02d}", folder, a_tags)
            fx_path = f"{FX_ROOT}/{atype.vfx_hint}"
            if eal.does_asset_exist(fx_path):
                fx = eas.spawn_actor_from_class(unreal.NiagaraActor, loc)
                fx.niagara_component.set_asset(eal.load_asset(fx_path))
                self._finish(fx, f"{poi.name}_{atype.name}_FX_{i:02d}", folder, a_tags)
        for i, art in enumerate(poi.anomaly_field.artifacts):
            self.marker(self.to_uu(art.x, art.y, 30.0), f"{poi.name}_Artifact_{i}", folder,
                        tags + ["Wasteland.Artifact", f"Wasteland.Artifact.{art.item_id}"])

    def build_player_start(self) -> None:
        coast = min((p for p in self.world.pois if p.kind == "village"), key=lambda p: p.x)
        start = eas.spawn_actor_from_class(unreal.PlayerStart, self.to_uu(coast.x - 150, coast.y, 300))
        self._finish(start, "PlayerStart_Coast", "Gameplay", ["Wasteland.Start"])


def clear_wasteland_actors() -> int:
    """Deletes everything this builder spawned (actors in the Wasteland folders)."""
    doomed = [a for a in eas.get_all_level_actors()
              if str(a.get_folder_path()).startswith("Wasteland")]
    for actor in doomed:
        eas.destroy_actor(actor)
    return len(doomed)

