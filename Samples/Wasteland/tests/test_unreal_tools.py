"""Smoke-tests the Unreal tooling against a mocked ``unreal`` module, so Python
mistakes (typos, bad arithmetic, wrong arguments to our own code) surface
without an editor. It cannot validate the real Unreal API - run it in-editor
for that."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeVector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __add__(self, other):
        return FakeVector(self.x + other.x, self.y + other.y, self.z + other.z)

    def length(self):
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5


def fake_unreal():
    ue = mock.MagicMock(name="unreal")
    ue.Vector = FakeVector
    spawned = []

    def spawn(cls, loc, rot=None):
        actor = mock.MagicMock(name=f"actor:{cls}")
        actor.location = loc
        spawned.append(actor)
        return actor

    ue.get_editor_subsystem.return_value.spawn_actor_from_class.side_effect = spawn
    ue.EditorAssetLibrary.does_asset_exist.return_value = False
    ue.ScopedSlowTask.return_value.__enter__.return_value.should_cancel.return_value = False
    return ue, spawned


class LevelBuilderSmokeTest(unittest.TestCase):
    def test_build_spawns_every_poi(self):
        ue, spawned = fake_unreal()
        with mock.patch.dict(sys.modules, {"unreal": ue}):
            for name in [m for m in sys.modules if m.startswith("unreal_tools")]:
                del sys.modules[name]
            from unreal_tools.level_builder import LevelBuilder, METRO_DEPTH_UU
            builder = LevelBuilder(seed=7, landscape_size=505)
            count = builder.build()
        self.assertEqual(count, len(spawned))
        self.assertGreater(count, 1000)
        # Metro platforms sit underground relative to the terrain.
        floors = [a for a in spawned
                  if any("_Floor" in str(c) for c in a.set_actor_label.call_args_list)]
        self.assertTrue(floors)
        half = builder.world.size_m / 2
        for floor in floors:
            loc = floor.location
            surface = builder.terrain.height_uu(loc.x / 100 + half, loc.y / 100 + half,
                                                builder.z_scale)
            self.assertAlmostEqual(loc.z, surface - METRO_DEPTH_UU, places=3)


class PieBridgeSmokeTest(unittest.TestCase):
    def test_tick_moves_simulation(self):
        ue, _ = fake_unreal()
        pawn = mock.MagicMock()
        pawn.get_actor_location.return_value = FakeVector(-700000, 0, 0)
        pawn.get_velocity.return_value = FakeVector(300, 0, 0)
        pawn.get_editor_property.return_value = False       # not crouched
        ue.GameplayStatics.get_player_pawn.return_value = pawn
        ue.GameplayStatics.get_all_actors_with_tag.return_value = [mock.MagicMock()]
        with mock.patch.dict(sys.modules, {"unreal": ue}):
            for name in [m for m in sys.modules if m.startswith("unreal_tools")]:
                del sys.modules[name]
            from unreal_tools import pie_bridge
            bridge = pie_bridge._bridge = pie_bridge.Bridge(seed=3)
            for _ in range(50):
                bridge._tick(0.05)
            self.assertIsNotNone(bridge.session)
            self.assertEqual(bridge.session.player.activity, "jog")
            self.assertGreater(bridge.session.clock.seconds, 8 * 3600)
            self.assertIn("Hansa", pie_bridge.talk("hansa"))
            self.assertTrue(ue.SystemLibrary.print_string.called)


class FabLibraryTests(unittest.TestCase):
    def test_classify_typical_fab_names(self):
        from unreal_tools.fab_library import classify
        cases = {
            ("SM_Soviet_Apartment_Block_01", "StaticMesh"): "building.town",
            ("SM_Abandoned_Warehouse", "StaticMesh"): "building.industrial",
            ("SM_Rusty_Barrel_A", "StaticMesh"): "container",
            ("SM_Lada_Wreck", "StaticMesh"): "vehicle",
            ("SM_Birch_Tree_02", "StaticMesh"): "tree",
            ("S_Mossy_Rock_uhrmbd_LOD0", "StaticMesh"): "rock",
            ("SK_Zombie_Male", "SkeletalMesh"): "creature.infected",
            ("SK_MutantDog", "SkeletalMesh"): "creature.pseudodog",
            ("MI_Old_Asphalt_Road", "MaterialInstanceConstant"): "material.Asphalt",
            ("MI_Concrete_Wall_Worn", "MaterialInstanceConstant"): "material.Concrete",
        }
        for (name, cls), role in cases.items():
            self.assertEqual(classify(name, f"/Game/Fab/Pack/{name}", cls), role, name)

    def test_builder_uses_fab_meshes(self):
        ue, spawned = fake_unreal()
        with mock.patch.dict(sys.modules, {"unreal": ue}):
            for name in [m for m in sys.modules if m.startswith("unreal_tools")]:
                del sys.modules[name]
            from unreal_tools.fab_library import FabLibrary
            from unreal_tools.level_builder import LevelBuilder
            fab = FabLibrary()
            for path, cls in (("/Game/Fab/A/SM_Apartment_Building", "StaticMesh"),
                              ("/Game/Fab/A/SM_Old_House", "StaticMesh"),
                              ("/Game/Fab/A/SM_Wooden_Crate", "StaticMesh"),
                              ("/Game/Fab/A/SM_Pine_Tree", "StaticMesh"),
                              ("/Game/Fab/A/SK_Zombie", "SkeletalMesh")):
                fab.add(f"{path}.{path.rsplit('/', 1)[1]}", path.rsplit("/", 1)[1], cls)
            mesh = mock.MagicMock()
            box = mesh.get_bounding_box.return_value
            box.min, box.max = FakeVector(-500, -500, 0), FakeVector(500, 500, 800)
            mesh.get_path_name.return_value = "mesh"
            ue.load_asset.return_value = mesh
            builder = LevelBuilder(seed=7, landscape_size=505, fab=fab)
            builder.build()
            meshes = [c.args[0] for a in spawned
                      for c in a.static_mesh_component.set_static_mesh.call_args_list]
            self.assertIn(mesh, meshes)
            skeletal = [a for a in spawned
                        if a.skeletal_mesh_component.set_skeletal_mesh_asset.called]
            self.assertTrue(skeletal)


if __name__ == "__main__":
    unittest.main()
