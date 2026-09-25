"""One-shot Unreal Editor setup for the Wasteland sample.

Run from the editor's Output Log (Cmd: py) or File -> Execute Python Script:

    py "<path>/Samples/Wasteland/setup_wasteland.py" --download --build --pie

Steps (each optional, in order):
    --download        fetch CC0 textures/HDRIs/models (Poly Haven, ambientCG)
    --import          import Downloads/ (+ Downloads/Manual/ drops) into /Game/Wasteland
    --datatables MOD  export CSVs + WastelandRows.h and import them as DataTables
                      (MOD = your C++ game module that compiled WastelandRows.h)
    --build           create /Game/Wasteland/Maps/L_Wasteland and build the map with the
                      Fab assets you added to the project (placeholders where none fit)
    --fab-roots ...   content folders to scan for Fab assets (default /Game/Fab,
                      /Game/Megascans and the rest of /Game)
    --no-fab          ignore Fab assets, placeholders only
    --pie             arm the Play-In-Editor survival prototype
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unreal  # noqa: E402

from unreal_tools import asset_sources  # noqa: E402

MAP_PATH = "/Game/Wasteland/Maps/L_Wasteland"


def main(argv: list) -> None:
    parser = argparse.ArgumentParser(prog="setup_wasteland")
    parser.add_argument("--seed", type=int, default=1986)
    parser.add_argument("--res", default="2k", choices=("1k", "2k", "4k", "8k"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--import", dest="do_import", action="store_true")
    parser.add_argument("--datatables", metavar="MODULE")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--landscape-size", type=int, default=1009)
    parser.add_argument("--height-range", type=float, default=400.0)
    parser.add_argument("--rebuild", action="store_true",
                        help="Delete previously built Wasteland actors first")
    parser.add_argument("--fab-roots", nargs="*", default=None)
    parser.add_argument("--no-fab", action="store_true")
    parser.add_argument("--pie", action="store_true")
    args = parser.parse_args(argv)

    if args.download:
        unreal.log("Wasteland: downloading CC0 assets ...")
        asset_sources.download_plan(args.res)
        asset_sources.ensure_manual_folders()
        (ROOT / "MANUAL_ASSETS.md").write_text(asset_sources.shopping_list(), encoding="utf-8")

    imported = {}
    if args.do_import:
        from unreal_tools import ue_import
        imported = ue_import.import_manifest()
        manual = ue_import.import_manual_drops()
        unreal.log(f"Wasteland: {len(imported.get('materials', {}))} materials, "
                   f"{len(imported.get('meshes', {}))} meshes, "
                   f"{len(manual.get('meshes', []))} manual assets, "
                   f"{len(manual.get('characters', {}))} Mixamo characters imported.")

    if args.datatables:
        from wasteland.datatables import export_all
        from unreal_tools import ue_import
        out = ROOT / "Exports"
        export_all(out, f"{args.datatables.upper()}_API")
        tables = ue_import.import_datatables(out, args.datatables)
        unreal.log(f"Wasteland: imported {len(tables)} DataTables "
                   f"(header at {out / 'WastelandRows.h'})")

    if args.build:
        from unreal_tools.level_builder import LevelBuilder, clear_wasteland_actors
        from wasteland.terrain import generate, landscape_scale, write_png16
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
            les.load_level(MAP_PATH)
        else:
            les.new_level(MAP_PATH)
        if args.rebuild:
            unreal.log(f"Wasteland: removed {clear_wasteland_actors()} old actors")
        fab = None
        if not args.no_fab:
            from unreal_tools.fab_library import DEFAULT_ROOTS, FabLibrary
            fab = FabLibrary.scan(tuple(args.fab_roots or DEFAULT_ROOTS), args.seed)
            fab.write_report(ROOT / "Exports" / "fab_library.json")
            if not fab.by_role:
                unreal.log_warning("Wasteland: no Fab assets found. Add them from Window -> "
                                   "Fab (My Library -> Add to Project) and rebuild.")
                fab = None
        builder = LevelBuilder(args.seed, args.height_range, args.landscape_size, fab=fab)
        heightmap = ROOT / "Exports" / f"heightmap_{args.seed}_{args.landscape_size}.png"
        if not heightmap.exists():
            write_png16(heightmap, generate(builder.world, args.landscape_size))
        sky = imported.get("hdris", {}).get("SkyOvercast")
        builder.build(sky_cubemap=sky)
        les.save_current_level()
        scale = landscape_scale(builder.world, args.landscape_size, args.height_range)
        unreal.log_warning(
            "Wasteland: map blocked out. Now add the terrain: Landscape Mode -> New -> "
            f"Import from File -> {heightmap}  | Location 0,0,0 | Scale {scale}")

    if args.pie:
        from unreal_tools import pie_bridge
        pie_bridge.start(args.seed, args.landscape_size, args.height_range)


if __name__ == "__main__":
    main(sys.argv[1:])
