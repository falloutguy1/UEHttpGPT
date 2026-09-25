"""Imports downloaded assets into the open Unreal project (UE 5.3+ editor Python).

* Texture sets -> textures with correct sRGB/compression + a Material Instance
  of ``M_Wasteland_Master`` per set (``/Game/Wasteland/Materials/MI_<Slot>``).
* HDRIs        -> TextureCubes for the Sky Light.
* Models       -> Static meshes (Poly Haven, manual drops).
* Mixamo       -> Skeletal meshes + animations retargeted onto the same skeleton.
* DataTables   -> CSVs from ``wasteland.datatables`` (needs the C++ row structs).
"""

from __future__ import annotations

import json
from pathlib import Path

import unreal

from .asset_sources import DOWNLOADS, MANUAL

GAME_ROOT = "/Game/Wasteland"
TEX_ROOT = f"{GAME_ROOT}/Textures"
MAT_ROOT = f"{GAME_ROOT}/Materials"
MESH_ROOT = f"{GAME_ROOT}/Meshes"
CHAR_ROOT = f"{GAME_ROOT}/Characters"
DATA_ROOT = f"{GAME_ROOT}/Data"
MASTER = f"{MAT_ROOT}/M_Wasteland_Master"

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary

# Map name -> (sRGB, compression)
TEXTURE_SETTINGS = {
    "BaseColor": (True, unreal.TextureCompressionSettings.TC_DEFAULT),
    "Normal": (False, unreal.TextureCompressionSettings.TC_NORMALMAP),
    "Roughness": (False, unreal.TextureCompressionSettings.TC_MASKS),
    "AO": (False, unreal.TextureCompressionSettings.TC_MASKS),
    "Metallic": (False, unreal.TextureCompressionSettings.TC_MASKS),
    "Height": (False, unreal.TextureCompressionSettings.TC_GRAYSCALE),
    "Opacity": (False, unreal.TextureCompressionSettings.TC_MASKS),
}


def _task(filename: str, dest: str, name: str | None = None, options=None) -> unreal.AssetImportTask:
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", filename)
    task.set_editor_property("destination_path", dest)
    if name:
        task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    if options is not None:
        task.set_editor_property("options", options)
    return task


def _run(tasks: list) -> list:
    if not tasks:
        return []
    asset_tools.import_asset_tasks(tasks)
    paths = []
    for task in tasks:
        paths += list(task.get_editor_property("imported_object_paths"))
    return paths


# -- Textures & materials ----------------------------------------------------------------
def import_texture_set(slot: str, maps: dict) -> dict:
    """Import one PBR set. Returns {map name: Texture2D}."""
    dest = f"{TEX_ROOT}/{slot}"
    tasks, order = [], []
    for map_name, file in maps.items():
        if map_name not in TEXTURE_SETTINGS or not Path(file).exists():
            continue
        tasks.append(_task(file, dest, f"T_{slot}_{map_name}"))
        order.append(map_name)
    _run(tasks)
    textures = {}
    for map_name in order:
        tex = eal.load_asset(f"{dest}/T_{slot}_{map_name}")
        if tex is None:
            continue
        srgb, compression = TEXTURE_SETTINGS[map_name]
        tex.set_editor_property("srgb", srgb)
        tex.set_editor_property("compression_settings", compression)
        eal.save_loaded_asset(tex)
        textures[map_name] = tex
    return textures


def ensure_master_material(defaults: dict) -> unreal.Material:
    """Builds a parameterised PBR master material. ``defaults`` must hold one
    imported texture set; its textures become the parameter defaults so every
    sampler type matches its texture's compression."""
    if eal.does_asset_exist(MASTER):
        return eal.load_asset(MASTER)
    eal.make_directory(MAT_ROOT)
    mat = asset_tools.create_asset("M_Wasteland_Master", MAT_ROOT, unreal.Material,
                                   unreal.MaterialFactoryNew())

    uv = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -1100, 0)
    tiling = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1100, 150)
    tiling.set_editor_property("parameter_name", "Tiling")
    tiling.set_editor_property("default_value", 1.0)
    tiled_uv = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -900, 50)
    mel.connect_material_expressions(uv, "", tiled_uv, "A")
    mel.connect_material_expressions(tiling, "", tiled_uv, "B")

    sampler_types = {
        "BaseColor": unreal.MaterialSamplerType.SAMPLERTYPE_COLOR,
        "Normal": unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
        "Roughness": unreal.MaterialSamplerType.SAMPLERTYPE_MASKS,
        "AO": unreal.MaterialSamplerType.SAMPLERTYPE_MASKS,
    }
    y = -300
    samplers = {}
    for name, sampler_type in sampler_types.items():
        if name not in defaults:
            continue
        node = mel.create_material_expression(
            mat, unreal.MaterialExpressionTextureSampleParameter2D, -600, y)
        node.set_editor_property("parameter_name", name)
        node.set_editor_property("texture", defaults[name])
        node.set_editor_property("sampler_type", sampler_type)
        mel.connect_material_expressions(tiled_uv, "", node, "UVs")
        samplers[name] = node
        y += 250

    # Wasteland grime: tint base colour toward rust/soot with one scalar.
    tint = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -600, y)
    tint.set_editor_property("parameter_name", "GrimeTint")
    tint.set_editor_property("default_value", unreal.LinearColor(0.42, 0.33, 0.24, 1.0))
    grime = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -600, y + 150)
    grime.set_editor_property("parameter_name", "Grime")
    grime.set_editor_property("default_value", 0.15)
    lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -250, -300)
    if "BaseColor" in samplers:
        mel.connect_material_expressions(samplers["BaseColor"], "RGB", lerp, "A")
    mel.connect_material_expressions(tint, "", lerp, "B")
    mel.connect_material_expressions(grime, "", lerp, "Alpha")
    mel.connect_material_property(lerp, "", unreal.MaterialProperty.MP_BASE_COLOR)

    if "Normal" in samplers:
        mel.connect_material_property(samplers["Normal"], "RGB", unreal.MaterialProperty.MP_NORMAL)
    if "Roughness" in samplers:
        mel.connect_material_property(samplers["Roughness"], "R", unreal.MaterialProperty.MP_ROUGHNESS)
    if "AO" in samplers:
        mel.connect_material_property(samplers["AO"], "R",
                                      unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    metallic = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -250, 300)
    metallic.set_editor_property("parameter_name", "Metallic")
    metallic.set_editor_property("default_value", 0.0)
    mel.connect_material_property(metallic, "", unreal.MaterialProperty.MP_METALLIC)

    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)
    return mat


def create_material_instance(slot: str, textures: dict, master: unreal.Material,
                             tiling: float = 1.0, metallic: float = 0.0,
                             grime: float = 0.15) -> unreal.MaterialInstanceConstant:
    path = f"{MAT_ROOT}/MI_{slot}"
    if eal.does_asset_exist(path):
        mi = eal.load_asset(path)
    else:
        mi = asset_tools.create_asset(f"MI_{slot}", MAT_ROOT, unreal.MaterialInstanceConstant,
                                      unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, master)
    for name, tex in textures.items():
        if name in ("BaseColor", "Normal", "Roughness", "AO"):
            mel.set_material_instance_texture_parameter_value(mi, name, tex)
    mel.set_material_instance_scalar_parameter_value(mi, "Tiling", tiling)
    mel.set_material_instance_scalar_parameter_value(mi, "Metallic", metallic)
    mel.set_material_instance_scalar_parameter_value(mi, "Grime", grime)
    eal.save_loaded_asset(mi)
    return mi


METALLIC_SLOTS = {"RustMetal": 0.8, "MetalPlate": 1.0, "PaintedMetal": 0.4}


def import_manifest() -> dict:
    """Import everything ``asset_sources.download_plan`` fetched."""
    manifest_path = DOWNLOADS / "manifest.json"
    if not manifest_path.exists():
        unreal.log_warning("No Downloads/manifest.json - run asset_sources download first.")
        return {}
    manifest = json.loads(manifest_path.read_text())
    result = {"materials": {}, "hdris": {}, "meshes": {}}
    master = None
    with unreal.ScopedSlowTask(len(manifest), "Importing Wasteland assets") as task:
        task.make_dialog(True)
        for slot, entry in manifest.items():
            if task.should_cancel():
                break
            task.enter_progress_frame(1, f"Importing {slot}")
            kind = entry.get("kind")
            if kind == "texture":
                textures = import_texture_set(slot, entry["maps"])
                if not textures:
                    continue
                if master is None:
                    master = ensure_master_material(textures)
                result["materials"][slot] = create_material_instance(
                    slot, textures, master, tiling=4.0,
                    metallic=METALLIC_SLOTS.get(slot, 0.0))
            elif kind == "hdri":
                paths = _run([_task(entry["file"], f"{TEX_ROOT}/HDRI", f"HDR_{slot}")])
                if paths:
                    result["hdris"][slot] = eal.load_asset(paths[0])
            elif kind == "model":
                result["meshes"][slot] = import_static_mesh(entry["file"], f"{MESH_ROOT}/{slot}")
    return result


# -- Meshes & characters -----------------------------------------------------------------
def _fbx_options(skeletal: bool, animation_only: bool = False,
                 skeleton: unreal.Skeleton | None = None) -> unreal.FbxImportUI:
    """Options for the legacy FBX importer. If your project has the Interchange
    FBX importer enabled (default in UE 5.5+), these are ignored and the
    Interchange pipeline settings apply instead."""
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", not animation_only)
    ui.set_editor_property("import_textures", True)
    ui.set_editor_property("import_materials", True)
    ui.set_editor_property("import_as_skeletal", skeletal)
    ui.set_editor_property("import_animations", skeletal)
    if animation_only:
        ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
    elif skeletal:
        ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    else:
        ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
        mesh_data = ui.get_editor_property("static_mesh_import_data")
        mesh_data.set_editor_property("combine_meshes", True)
        mesh_data.set_editor_property("generate_lightmap_u_vs", True)
        mesh_data.set_editor_property("auto_generate_collision", True)
    if skeleton is not None:
        ui.set_editor_property("skeleton", skeleton)
    return ui


def import_static_mesh(file: str, dest: str):
    options = _fbx_options(False) if file.lower().endswith(".fbx") else None
    paths = _run([_task(file, dest, options=options)])
    meshes = [eal.load_asset(p) for p in paths]
    return next((m for m in meshes if isinstance(m, unreal.StaticMesh)), None)


def import_mixamo(folder: Path, name: str) -> dict:
    """``folder`` holds one character FBX exported *With Skin* (named
    ``<name>.fbx`` or ``character.fbx``) and any number of clips exported
    *Without Skin*. All clips are bound to the character's skeleton."""
    fbx = sorted(folder.glob("*.fbx"))
    if not fbx:
        return {}
    skin = next((f for f in fbx if f.stem.lower() in (name.lower(), "character")), fbx[0])
    dest = f"{CHAR_ROOT}/{name}"
    paths = _run([_task(str(skin), dest, f"SK_{name}", _fbx_options(True))])
    skel_mesh = next((eal.load_asset(p) for p in paths
                      if isinstance(eal.load_asset(p), unreal.SkeletalMesh)), None)
    if skel_mesh is None:
        unreal.log_warning(f"{skin} did not import as a skeletal mesh")
        return {}
    skeleton = skel_mesh.get_editor_property("skeleton")
    clips = [f for f in fbx if f != skin]
    anim_paths = _run([_task(str(c), f"{dest}/Animations", f"A_{name}_{c.stem.replace(' ', '_')}",
                             _fbx_options(True, animation_only=True, skeleton=skeleton))
                       for c in clips])
    return {"mesh": skel_mesh, "skeleton": skeleton, "animations": anim_paths}


def import_manual_drops() -> dict:
    """Imports everything under Downloads/Manual/<Source>/...

    * ``Manual/Mixamo/<who>/``  -> skeletal character + animations
    * ``Manual/*/Creatures/``   -> skeletal meshes named after the creature id
    * anything else (.fbx/.gltf/.glb/.obj) -> static meshes, keeping folders
    """
    result = {"characters": {}, "meshes": []}
    if not MANUAL.exists():
        return result
    mixamo = MANUAL / "Mixamo"
    if mixamo.exists():
        for who in (d for d in mixamo.iterdir() if d.is_dir()):
            result["characters"][who.name] = import_mixamo(who, who.name)
    for source in (d for d in MANUAL.iterdir() if d.is_dir() and d.name != "Mixamo"):
        for file in source.rglob("*"):
            if file.suffix.lower() not in (".fbx", ".gltf", ".glb", ".obj"):
                continue
            rel = file.parent.relative_to(source)
            skeletal = "Creatures" in rel.parts or "Characters" in rel.parts
            dest = f"{MESH_ROOT}/{source.name}/{rel.as_posix()}".rstrip("/.")
            options = _fbx_options(skeletal) if file.suffix.lower() == ".fbx" else None
            result["meshes"] += _run([_task(str(file), dest, options=options)])
    return result


# -- DataTables -------------------------------------------------------------------------
def import_datatables(export_dir: Path, module_name: str) -> list:
    """Import the CSVs from ``wasteland.datatables``. The row structs must be
    compiled into ``module_name`` first (copy WastelandRows.h into it)."""
    from wasteland.datatables import TABLES
    imported = []
    for struct, (asset_name, _) in TABLES.items():
        csv = export_dir / f"{asset_name}.csv"
        row_struct = unreal.load_object(None, f"/Script/{module_name}.{struct[1:]}")
        if row_struct is None or not csv.exists():
            unreal.log_warning(f"Skipping {asset_name}: row struct /Script/{module_name}."
                               f"{struct[1:]} not found (compile WastelandRows.h) or CSV missing")
            continue
        factory = unreal.CSVImportFactory()
        settings = factory.get_editor_property("automated_import_settings")
        settings.set_editor_property("import_type", unreal.CSVImportType.ECSV_DATA_TABLE)
        settings.set_editor_property("import_row_struct", row_struct)
        factory.set_editor_property("automated_import_settings", settings)   # struct copy
        task = _task(str(csv), DATA_ROOT, asset_name)
        task.set_editor_property("factory", factory)
        imported += _run([task])
    return imported
