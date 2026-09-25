# Wasteland: a DayZ-style survival sample with Fallout, S.T.A.L.K.E.R. and Metro systems

A Python toolkit for prototyping an open-world survival game in Unreal Engine 5
(written against the 5.3/5.4 editor Python API). It has three parts:

1. **`wasteland/`**: the game rules as pure Python with no dependencies. You can
   test it, balance it and simulate it headless.
2. **`unreal_tools/`**: editor scripts. They download CC0 assets, import them with
   correct PBR settings, block out the whole map, and run the survival sim live
   while you Play-In-Editor.
3. **DataTable export**: CSVs plus a generated C++ `USTRUCT` header, so the numbers
   carry over when you port the systems you keep to C++/Blueprint.

> **Important:** Unreal's Python runs **in the editor only**; it doesn't ship in
> packaged games. Use this sample to prototype, generate content and balance
> the game. For the shipped game, port the gameplay to C++/Blueprint and drive
> it from the exported DataTables.

## What comes from where

| Pillar | Systems |
|---|---|
| **DayZ** | Energy/water, blood, bleeding wounds, shock and unconsciousness, body temperature, wetness, campfires, diseases (cholera, salmonella, wound infection), item condition, cell-based inventory where clothing and backpacks carry cargo, infected hordes drawn by noise, permadeath |
| **Fallout** | S.P.E.C.I.A.L. (point-buy), derived stats, XP curve, perks, karma, rads that cap max HP, RadAway/Rad-X, Stimpaks, bottle caps, Fallout 4 armor curve, V.A.T.S. hit chance and AP cost, vaults, ghouls, Deathclaws |
| **S.T.A.L.K.E.R.** | Anomaly fields (Vortex, Burner, Electro, Springboard, Fruit Punch, Whirligig), bolts, Echo/Bear detectors, artifacts worn on a belt (with radiation trade-offs), Emissions/Blowouts that reshuffle anomalies, Duty/Freedom/Monolith, mutants |
| **Metro** | GP-5 gas masks, 5-minute filter timer, cracked visors that leak, toxic surface in the dead city, metro stations underground, tunnel travel, military-grade 5.45 as currency, Hansa/Red Line/Reich/Rangers, Nosalises, Watchers, Librarians, Demons |

### Map layout (seeded and deterministic)

The map is 16 km × 16 km and split into three bands:

* **West, "Chernarus"**: villages, towns, farms, military camps, infected.
* **Centre, the dead city**: a toxic-air core, metro stations (safe zones and
  traders), vaults, ruins.
* **East, "the Zone"**: industrial sites, anomaly fields, craters, and radiation
  rising toward the reactor.

## Quick start (no Unreal needed)

```bash
cd Samples/Wasteland
python -m wasteland.game --hours 24 --seed 7          # headless autopilot survival run
python -m unittest discover -s tests                  # 21 tests
python -m wasteland.datatables --out Exports          # DT_*.csv + WastelandRows.h
python -m wasteland.terrain --size 1009 --out Exports/heightmap.png
python -m unreal_tools.asset_sources download --res 2k
python -m unreal_tools.asset_sources shopping-list    # writes MANUAL_ASSETS.md
```

The autopilot run loots villages and a military camp, crosses the dead city
wearing a gas mask, takes the metro tunnels, and walks into the Zone. It often
dies on the way, because DayZ.

## Unreal setup

1. Enable the **Python Editor Script Plugin** (on by default in 5.x), plus
   **Niagara** if you add anomaly effects.
2. In the Output Log, switch the input box to **Python** (or use `py ...`) and run:

   ```text
   py "C:/path/to/Samples/Wasteland/setup_wasteland.py" --download --build --pie
   ```

   * `--download` fetches CC0 textures, HDRIs and props from **Poly Haven** and
     **ambientCG**.
   * `--build` imports them, builds `M_Wasteland_Master` and `MI_*` material
     instances, and creates `/Game/Wasteland/Maps/L_Wasteland`. It also spawns
     the sun, sky, fog, clouds, roads, buildings, metro platforms, vault doors,
     anomaly lights, hazard post-process volumes, and tagged loot and creature
     markers.
   * `--pie` arms the survival prototype. Press **Play**.
3. **Terrain.** The build step writes `Exports/heightmap_<seed>_<size>.png` and
   logs the Landscape scale to use. Go to **Landscape Mode → New → Import from
   File**, set Location to `0,0,0`, and enter that scale. Everything the builder
   placed then sits on the terrain.
4. **DataTables (optional).** Copy `Exports/WastelandRows.h` into your game
   module, compile, then run:

   ```text
   py ".../setup_wasteland.py" --datatables MyGame
   ```

### While playing (PIE)

The HUD shows vitals, rads, Geiger rate, filter time, weather, emission state,
level and karma. The toxic, radiation, emission and underground post-process
volumes fade in automatically, the sun follows the in-game clock, and metro
lamps flicker. You drive player actions from the Python console:

```python
import unreal_tools.pie_bridge as pie
pie.give("gas_mask"); pie.give("filter", 3)
pie.use("bandage"); pie.search(); pie.fire()
pie.bolt(); pie.detector(); pie.pickup_artifact()
pie.status()
```

### Blueprint hooks

Everything the builder spawns is tagged, so Blueprints can find it with
**Get All Actors With Tag**:

`Wasteland.Loot.<table>`, `Wasteland.Spawn.<creature>`, `Wasteland.Anomaly.<type>`,
`Wasteland.Artifact.<item>`, `Wasteland.Metro`, `Wasteland.SafeZone`,
`Wasteland.Trader.<faction>`, `Wasteland.Vault.Door`, `Wasteland.PP.*`,
`Wasteland.Sun`, `Wasteland.Flicker`.

### NPC dialogue with HttpGPT

Each faction has an in-character persona (exported in `DT_Factions.Persona`).
`pie.talk("hansa")` returns the complete system prompt, including the player's
standing and karma title. In Blueprint, call HttpGPT's **Send Messages with
Default Options** with that prompt as a `System` message, followed by the
player's line as a `User` message. Python can't call that node directly
because HttpGPT marks it `BlueprintInternalUseOnly`.

## Assets: which tool for which job

The automated pipeline handles the CC0 sources. For everything else,
`MANUAL_ASSETS.md` is a checklist generated from the game data: one search link
per creature, item and animation. Drop downloads into
`Downloads/Manual/<Source>/...` and `--build` (or `--import`) picks them up.

| Need | Recommended source | How |
|---|---|---|
| Ground, concrete, rust, tiles | Poly Haven, ambientCG (then ShareTextures, CGBookcase, 3DTextures) | Automatic (`ASSET_PLAN` in `asset_sources.py`) |
| Skies / lighting | Poly Haven HDRIs | Automatic, becomes the Sky Light cubemap |
| Hero environment scans | Fab (free Megascans) | Add to project from Fab, then place |
| Detailed props, weapons | BlenderKit, Sketchfab, CGTrader, TurboSquid | `Manual/<Source>/` → static meshes |
| Creatures | Sketchfab, Fab, Quaternius | `Manual/<Source>/Creatures/` → skeletal meshes |
| Humanoids + animation | Mixamo (+ Rokoko, ActorCore mocap) | `Manual/Mixamo/<who>/`: one *With Skin* FBX plus clips *Without Skin*, all bound to one skeleton |
| Blockout / UI | Kenney, Quaternius | `Manual/Kenney/` |
| Audio (Geiger, ambience) | OpenGameArt | Manual |

**License notes:** Poly Haven, ambientCG, ShareTextures, CGBookcase, 3DTextures
and Kenney are CC0. FreePBR requires a **paid license for commercial use**.
Sketchfab, OpenGameArt, CGTrader and TurboSquid licenses vary per asset, so check
each one (CC-BY requires credit, and some assets are non-commercial). Mixamo is
royalty-free with an Adobe ID. Quaternius allows commercial use but not
redistribution of the raw assets. `Downloads/` is git-ignored, so don't commit
third-party assets.

## Layout

```text
wasteland/          game rules (pure Python)
  survival.py         DayZ vitals, temperature, disease, bleeding
  hazards.py          Fallout radiation, Metro gas mask/filters
  anomalies.py        STALKER anomalies, bolts, detectors, artifacts, emissions
  special.py          SPECIAL, perks, XP, karma
  combat.py           damage types, armor curve, hit zones, V.A.T.S.
  items.py            57 items across all four games
  inventory.py        cargo cells, equipment slots, artifact belt
  creatures.py        infected + mutants with perception/state-machine AI
  factions.py         reputation, relations, HttpGPT personas
  economy.py          traders; caps vs. military-grade ammo
  world.py            procedural layout, loot tables, clock, weather
  terrain.py          16-bit heightmap PNG + height sampling
  game.py             GameSession tying it together + headless autopilot
  datatables.py       CSV + C++ USTRUCT export
unreal_tools/
  asset_sources.py    Poly Haven / ambientCG downloaders + manual shopping list
  ue_import.py        textures, master material, MIs, FBX/Mixamo, DataTables
  level_builder.py    blocks out the map in the editor
  pie_bridge.py       live survival sim during Play-In-Editor
setup_wasteland.py  one-shot editor entry point
tests/              unit tests + mocked-unreal smoke tests
```

The Unreal scripts were smoke-tested against a mocked `unreal` module, not a
live editor. If a property name differs in your engine version, the Output Log
names it.
