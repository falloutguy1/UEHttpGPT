"""Free asset pipeline.

Automated (public APIs, CC0, no account needed):
    * Poly Haven  - PBR textures, HDRIs, photoscanned models
    * ambientCG   - PBR materials

Manual (need a login, a launcher, or a per-asset license check):
    Fab/Megascans, BlenderKit, Sketchfab, Mixamo, Rokoko, ActorCore,
    Quaternius, Kenney, OpenGameArt, CGTrader, TurboSquid, ShareTextures,
    CGBookcase, 3DTextures.me, FreePBR, Textures.com, Unity Asset Store and
    Epic's free content. For these we generate a shopping list from the game
    data and import whatever you drop into ``Downloads/Manual/<Source>/``.

This module does not import ``unreal``; run it from a normal terminal:

    python -m unreal_tools.asset_sources download --res 2k
    python -m unreal_tools.asset_sources shopping-list
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "Downloads"
MANUAL = DOWNLOADS / "Manual"
USER_AGENT = "WastelandSample-UEHttpGPT/0.1 (asset pipeline)"

sys.path.insert(0, str(ROOT))


# -- What the game needs ------------------------------------------------------------
@dataclass(frozen=True)
class Want:
    slot: str               # material slot the level builder uses (M_<slot>)
    source: str             # polyhaven | ambientcg
    kind: str               # texture | hdri | model
    query: tuple            # keywords, all must match tags/name/category
    note: str = ""


ASSET_PLAN = (
    # Surfaces
    Want("Concrete", "polyhaven", "texture", ("concrete",), "Soviet panel blocks"),
    Want("ConcreteDirty", "ambientcg", "texture", ("concrete", "dirty"), "Metro tunnels"),
    Want("Brick", "polyhaven", "texture", ("brick",), "Village houses"),
    Want("Asphalt", "polyhaven", "texture", ("asphalt",), "Roads"),
    Want("RustMetal", "polyhaven", "texture", ("rust",), "Industrial / vault doors"),
    Want("MetalPlate", "ambientcg", "texture", ("metal", "plate"), "Vault interiors"),
    Want("PaintedMetal", "ambientcg", "texture", ("painted", "metal"), "Metro trains"),
    Want("WoodPlanks", "polyhaven", "texture", ("wood", "planks"), "Barns, shacks"),
    Want("Tiles", "ambientcg", "texture", ("tiles",), "Metro station walls"),
    Want("Mud", "polyhaven", "texture", ("mud",), "Swamps, anomaly fields"),
    Want("ForestGround", "polyhaven", "texture", ("forest", "ground"), "Chernarus forest"),
    Want("Grass", "ambientcg", "texture", ("grass",), "Fields"),
    Want("Gravel", "ambientcg", "texture", ("gravel",), "Rail beds"),
    Want("BurntGround", "ambientcg", "texture", ("ground", "burned"), "Craters"),
    # Skies
    Want("SkyOvercast", "polyhaven", "hdri", ("overcast",), "Default Zone sky"),
    Want("SkyIndustrial", "polyhaven", "hdri", ("industrial",), "Dead city"),
    Want("SkyNight", "polyhaven", "hdri", ("night",), "Night"),
    # Props (Poly Haven's photoscans are CC0 and game-ready)
    Want("PropBarrel", "polyhaven", "model", ("barrel",), "Loot containers"),
    Want("PropCrate", "polyhaven", "model", ("crate",), "Loot containers"),
    Want("PropChair", "polyhaven", "model", ("chair",), "Interiors"),
    Want("PropRock", "polyhaven", "model", ("rock",), "Anomaly fields"),
)


# -- HTTP helpers --------------------------------------------------------------------
def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _json(url: str):
    return json.loads(_get(url))


def _download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)
    return dest


# -- Poly Haven --------------------------------------------------------------------
class PolyHaven:
    """https://api.polyhaven.com - CC0. Please keep the User-Agent descriptive."""
    API = "https://api.polyhaven.com"
    TYPE = {"texture": "textures", "hdri": "hdris", "model": "models"}
    # Poly Haven map key -> our map name. nor_dx because Unreal uses DirectX normals.
    MAPS = {"Diffuse": "BaseColor", "nor_dx": "Normal", "Rough": "Roughness",
            "AO": "AO", "Displacement": "Height", "Metal": "Metallic"}

    def __init__(self):
        self._catalog = {}

    def search(self, kind: str, keywords: tuple, limit: int = 1) -> list:
        if kind not in self._catalog:
            self._catalog[kind] = _json(f"{self.API}/assets?t={self.TYPE[kind]}")
        hits = []
        for asset_id, info in self._catalog[kind].items():
            haystack = " ".join([asset_id, info.get("name", ""),
                                 *info.get("tags", []), *info.get("categories", [])]).lower()
            if all(k.lower() in haystack for k in keywords):
                hits.append((info.get("download_count", 0), asset_id))
        return [asset_id for _, asset_id in sorted(hits, reverse=True)[:limit]]

    def download(self, want: Want, asset_id: str, res: str) -> dict:
        files = _json(f"{self.API}/files/{asset_id}")
        out = DOWNLOADS / "PolyHaven" / want.slot
        if want.kind == "texture":
            maps = {}
            for key, name in self.MAPS.items():
                variants = files.get(key, {}).get(res, {})
                entry = variants.get("png") or variants.get("jpg")
                if entry:
                    ext = Path(urllib.parse.urlparse(entry["url"]).path).suffix
                    maps[name] = str(_download(entry["url"], out / f"{want.slot}_{name}{ext}"))
            return {"kind": "texture", "maps": maps}
        if want.kind == "hdri":
            entry = files["hdri"].get(res, files["hdri"].get("2k"))["hdr"]
            return {"kind": "hdri", "file": str(_download(entry["url"], out / f"{want.slot}.hdr"))}
        # Models: prefer FBX (legacy importer), fall back to glTF (Interchange).
        for fmt in ("fbx", "gltf"):
            entry = files.get(fmt, {}).get(res, {}).get(fmt)
            if entry:
                main = _download(entry["url"], out / Path(urllib.parse.urlparse(entry["url"]).path).name)
                for rel, inc in entry.get("include", {}).items():
                    _download(inc["url"], out / rel)       # textures next to the mesh
                return {"kind": "model", "file": str(main)}
        return {}


# -- ambientCG ---------------------------------------------------------------------
class AmbientCG:
    """https://ambientcg.com/api/v2 - CC0."""
    API = "https://ambientcg.com/api/v2/full_json"
    MAPS = {"_Color": "BaseColor", "_NormalDX": "Normal", "_Roughness": "Roughness",
            "_AmbientOcclusion": "AO", "_Displacement": "Height", "_Metalness": "Metallic",
            "_Opacity": "Opacity"}

    def search(self, kind: str, keywords: tuple, limit: int = 1) -> list:
        query = urllib.parse.urlencode({"type": "Material", "q": " ".join(keywords),
                                        "sort": "Popular", "limit": limit,
                                        "include": "downloadData"})
        data = _json(f"{self.API}?{query}")
        return data.get("foundAssets", [])

    def download(self, want: Want, asset: dict, res: str) -> dict:
        attribute = f"{res.upper()}-JPG"
        downloads = asset["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
        entry = next((d for d in downloads if d["attribute"] == attribute), downloads[0])
        out = DOWNLOADS / "AmbientCG" / want.slot
        archive = _download(entry["downloadLink"], out / entry["fileName"])
        maps = {}
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                for suffix, name in self.MAPS.items():
                    if Path(member).stem.endswith(suffix):
                        target = out / f"{want.slot}_{name}{Path(member).suffix}"
                        if not target.exists():
                            target.write_bytes(zf.read(member))
                        maps[name] = str(target)
        return {"kind": "texture", "maps": maps, "asset_id": asset["assetId"]}


def download_plan(res: str = "2k", only: tuple = ()) -> dict:
    """Fetch every automated asset in ``ASSET_PLAN``. Writes a manifest the
    Unreal importer reads. Returns the manifest."""
    ph, acg = PolyHaven(), AmbientCG()
    manifest_path = DOWNLOADS / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for want in ASSET_PLAN:
        if only and want.slot not in only:
            continue
        try:
            if want.source == "polyhaven":
                ids = ph.search(want.kind, want.query)
                if not ids:
                    print(f"  [skip] {want.slot}: nothing on Poly Haven for {want.query}")
                    continue
                entry = ph.download(want, ids[0], res)
                entry["asset_id"] = ids[0]
            else:
                assets = acg.search(want.kind, want.query)
                if not assets:
                    print(f"  [skip] {want.slot}: nothing on ambientCG for {want.query}")
                    continue
                entry = acg.download(want, assets[0], res)
            entry.update(source=want.source, license="CC0", note=want.note)
            manifest[want.slot] = entry
            print(f"  [ok]   {want.slot:<14} {want.source}:{entry.get('asset_id')}")
        except Exception as exc:          # keep going; one bad asset shouldn't stop the run
            print(f"  [fail] {want.slot}: {exc}")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


# -- Manual sources ------------------------------------------------------------------
@dataclass(frozen=True)
class ManualSource:
    name: str
    url: str
    good_for: str
    license: str
    search_url: str = ""           # "{q}" gets the search phrase
    formats: tuple = ("fbx",)
    use_for: tuple = field(default_factory=tuple)   # props | creatures | animations | ...


MANUAL_SOURCES = (
    ManualSource("Fab", "https://www.fab.com", "Megascans surfaces/3D scans, environments, "
                 "characters, VFX (filter Price -> Free)",
                 "Fab Standard License; free Megascans for Unreal projects",
                 "https://www.fab.com/search?q={q}&is_free=1", ("uasset", "fbx"),
                 ("props", "environment", "vfx")),
    ManualSource("BlenderKit", "https://www.blenderkit.com", "Detailed props inside Blender",
                 "Royalty Free / CC0 per asset", "https://www.blenderkit.com/asset-gallery?query={q}",
                 ("blend -> fbx",), ("props",)),
    ManualSource("Sketchfab", "https://sketchfab.com", "Community props, weapons, creatures",
                 "CHECK EACH MODEL (CC0, CC-BY need credit, some NC)",
                 "https://sketchfab.com/search?q={q}&type=models&features=downloadable",
                 ("fbx", "gltf"), ("props", "creatures", "weapons")),
    ManualSource("Mixamo", "https://www.mixamo.com", "Humanoid characters, auto-rig, animations",
                 "Royalty free for personal and commercial use (Adobe ID)",
                 "https://www.mixamo.com/#/?query={q}", ("fbx",), ("animations", "characters")),
    ManualSource("Rokoko", "https://www.rokoko.com/resources/motion-library",
                 "Pro mocap clips (free tier)", "See clip license", "", ("fbx",),
                 ("animations",)),
    ManualSource("ActorCore", "https://actorcore.reallusion.com/free",
                 "Free characters and mocap", "See ActorCore free license", "", ("fbx",),
                 ("animations", "characters")),
    ManualSource("Quaternius", "https://quaternius.com", "Stylised characters, buildings, "
                 "vehicles; great for blockout", "Free personal + commercial, no redistribution",
                 "", ("fbx", "gltf"), ("props", "creatures", "vehicles")),
    ManualSource("Kenney", "https://kenney.nl/assets", "CC0 buildings, props, UI",
                 "CC0", "https://kenney.nl/assets?q={q}", ("fbx", "gltf"), ("ui", "props")),
    ManualSource("OpenGameArt", "https://opengameart.org", "Models, audio, textures, VFX",
                 "Mixed (CC0/CC-BY/GPL) - check each", "https://opengameart.org/art-search?keys={q}",
                 ("fbx", "wav", "ogg"), ("audio", "props")),
    ManualSource("CGTrader", "https://www.cgtrader.com/free-3d-models", "Buildings, vehicles, props",
                 "Royalty Free / Editorial - check each",
                 "https://www.cgtrader.com/free-3d-models?keywords={q}", ("fbx",), ("props",)),
    ManualSource("TurboSquid", "https://www.turbosquid.com/Search/3D-Models/free",
                 "Broad model library", "TurboSquid license - check each",
                 "https://www.turbosquid.com/Search/3D-Models/free/{q}", ("fbx",), ("props",)),
    ManualSource("ShareTextures", "https://www.sharetextures.com", "4K PBR + scans",
                 "CC0", "https://www.sharetextures.com/?s={q}", ("jpg",), ("textures",)),
    ManualSource("CGBookcase", "https://www.cgbookcase.com", "Photoreal PBR textures",
                 "CC0", "https://www.cgbookcase.com/textures?search={q}", ("jpg",), ("textures",)),
    ManualSource("3DTextures", "https://3dtextures.me", "Free PBR materials",
                 "CC0", "https://3dtextures.me/?s={q}", ("jpg",), ("textures",)),
    ManualSource("FreePBR", "https://freepbr.com", "Hundreds of PBR surfaces",
                 "Free download, PAID LICENSE REQUIRED for commercial use", "",
                 ("png",), ("textures",)),
    ManualSource("Textures.com", "https://www.textures.com", "Textures, scans, decals",
                 "Textures.com license - free tier has limits", "", ("jpg",),
                 ("textures", "decals")),
    ManualSource("UnityAssetStore", "https://assetstore.unity.com/?free=true",
                 "Free packs (export FBX/textures; Unity-only licenses excluded)",
                 "Unity Asset Store EULA - check it permits other engines", "",
                 ("fbx",), ("props",)),
    ManualSource("EpicContent", "https://www.unrealengine.com/marketplace",
                 "Epic's legacy free projects (Paragon, City Sample, Matrix)",
                 "Unreal Engine EULA (Unreal projects only)", "", ("uasset",),
                 ("environment", "characters")),
)

# Mixamo clip names per gameplay state (search these on mixamo.com).
MIXAMO_ANIMATIONS = {
    "player": ["Rifle Idle", "Rifle Walk", "Rifle Run", "Crouch Walk", "Crouching Idle",
               "Drinking", "Eating", "Picking Up", "Hit Reaction", "Dying",
               "Throw", "Injured Walk", "Standing Torch Light Torch"],
    "infected": ["Zombie Idle", "Zombie Walk", "Zombie Running", "Zombie Attack",
                 "Zombie Scream", "Zombie Dying", "Zombie Crawl"],
    "feral_ghoul": ["Mutant Run", "Mutant Swiping", "Mutant Dying", "Zombie Scream"],
    "npc": ["Sitting Idle", "Talking", "Warming Hands", "Guitar Playing", "Standing Guard"],
}


def shopping_list() -> str:
    """Markdown checklist of what to fetch manually, generated from the data."""
    from wasteland.creatures import CREATURES
    from wasteland.items import ITEMS

    def search(src: ManualSource, phrase: str) -> str:
        return src.search_url.format(q=urllib.parse.quote_plus(phrase)) if src.search_url else src.url

    by_name = {s.name: s for s in MANUAL_SOURCES}
    lines = ["# Wasteland asset shopping list", "",
             "Drop downloads into `Downloads/Manual/<Source>/<Category>/`; "
             "`setup_wasteland.py` imports them.", "",
             "## Sources and licenses", "",
             "| Source | Good for | License |", "|---|---|---|"]
    lines += [f"| [{s.name}]({s.url}) | {s.good_for} | {s.license} |" for s in MANUAL_SOURCES]

    lines += ["", "## Creatures (Sketchfab / Fab / Quaternius, animate with Mixamo)", ""]
    for c in CREATURES.values():
        lines.append(f"- [ ] **{c.name}** ({c.origin}) - "
                     f"[Sketchfab]({search(by_name['Sketchfab'], c.mesh_hint)}) · "
                     f"[Fab]({search(by_name['Fab'], c.mesh_hint)}) -> "
                     f"`Manual/Sketchfab/Creatures/{c.id}.fbx`")

    lines += ["", "## Items and weapons (BlenderKit / Sketchfab / CGTrader)", ""]
    seen = set()
    for item in ITEMS.values():
        if item.mesh_hint in seen:
            continue
        seen.add(item.mesh_hint)
        lines.append(f"- [ ] `{item.mesh_hint}` (e.g. {item.name}) - "
                     f"[BlenderKit]({search(by_name['BlenderKit'], item.mesh_hint)}) · "
                     f"[Sketchfab]({search(by_name['Sketchfab'], item.mesh_hint)}) · "
                     f"[CGTrader]({search(by_name['CGTrader'], item.mesh_hint)})")

    lines += ["", "## Animations (Mixamo: characters *With Skin*, clips *Without Skin*, "
              "FBX, 30 fps)", ""]
    for who, clips in MIXAMO_ANIMATIONS.items():
        lines.append(f"- **{who}**: " + ", ".join(clips) + f" -> `Manual/Mixamo/{who}/`")

    lines += ["", "## Environment (Fab / Megascans)", "",
              "- [ ] Soviet apartment block kit, rusted car wrecks, rail tracks, "
              "metro platform kit, bunker door, dead trees, debris decals",
              "- [ ] Megascans: forest floor, birch trees, rocks, mud, concrete debris",
              "", "Reminder: FreePBR needs a paid license for commercial use; "
              "Sketchfab/OpenGameArt/CGTrader/TurboSquid licenses vary per asset.", ""]
    return "\n".join(lines)


def ensure_manual_folders() -> None:
    for src in MANUAL_SOURCES:
        (MANUAL / src.name).mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wasteland free-asset pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    dl = sub.add_parser("download", help="Download CC0 assets from Poly Haven + ambientCG")
    dl.add_argument("--res", default="2k", choices=("1k", "2k", "4k", "8k"))
    dl.add_argument("--only", nargs="*", default=(), help="Slots to fetch, e.g. Concrete Mud")
    sub.add_parser("shopping-list", help="Write MANUAL_ASSETS.md for the manual sources")
    args = parser.parse_args()

    if args.cmd == "download":
        print(f"Downloading to {DOWNLOADS} at {args.res} ...")
        download_plan(args.res, tuple(args.only))
    else:
        ensure_manual_folders()
        out = ROOT / "MANUAL_ASSETS.md"
        out.write_text(shopping_list(), encoding="utf-8")
        print(f"Wrote {out} and created {MANUAL}/<Source>/ folders.")


if __name__ == "__main__":
    main()
