# Survivor Spectator

An Unreal Engine 5.4 game where you don't play: you **watch**. An AI squad leader and their team of
survivors try to last five nights in a zombie apocalypse. They gather food, wood and scrap, patch the camp's
barricade, craft better weapons, cover each other in fights and drag downed teammates back to their feet.

Everything is built at runtime from the engine's basic shapes, so the project has no content assets and runs
on an empty map.

## How the AI works

- **Every survivor** runs a utility AI (`SurvivorAIController`). Twice a second it scores every possible task
  (gather, haul, eat, rest, repair, craft, fight, flee, revive, defend) from their needs, personality
  (bravery, cooperation, diligence), the camp stockpile, the time of day and what teammates are already doing.
  Survivors claim resource nodes and downed allies so they spread the work out instead of piling onto the same job.
- **The leader** (`LeaderBrainComponent`) sets a squad directive (stockpile food, fortify, regroup, protect each
  other...) that biases everyone's choices. It shouts orders and has private thoughts you can read on the HUD.
  If the leader dies, the bravest, most cooperative survivor takes over.
- **GPT (optional):** with an OpenAI API key set in *Project Settings > Plugins > HttpGPT*, the leader thinks with
  GPT through this repository's HttpGPT plugin: it reads a situation report and answers with a directive, a line
  to shout and a thought. Without a key, or if requests fail, it uses a built-in rule-based planner. The HUD shows
  which brain is active.

## Requirements

- Unreal Engine **5.4** (Epic Games Launcher)
- Windows: Visual Studio 2022 with the **Game development with C++** workload
  (macOS: Xcode; Linux: the toolchain bundled with the engine)

## Running it

1. Clone this repository (the project uses the HttpGPT plugin from the repository root, found through
   `AdditionalPluginDirectories` in the `.uproject`, so keep the folder layout as is).
2. Right-click `SurvivorSpectator.uproject` and choose **Generate Visual Studio project files**.
3. Double-click `SurvivorSpectator.uproject` and accept the prompt to build the modules.
4. Press **Play**. The game mode builds the arena on the startup map (`/Engine/Maps/Entry`).
   If you'd rather use your own map, create an empty level and set its GameMode Override to `SurvivalGameMode`.

If the plugin isn't picked up, copy the repository's root (the folder containing `HttpGPT.uplugin`) to
`Examples/SurvivorSpectator/Plugins/HttpGPT` and delete the `AdditionalPluginDirectories` entry.

## Spectator controls

| Key | Action |
| --- | --- |
| Mouse | Look around |
| Tab / arrow keys | Watch next / previous survivor |
| 1-8 | Watch a specific survivor |
| L | Follow the leader, even through a change of leader (default) |
| C / T / F | Follow cam / tactical overview / free fly (WASD, Q/E, Shift) |
| Mouse wheel | Zoom |
| [ and ] | Slow down / speed up (x0.25 to x8) |
| Space or P | Pause |
| H / F1 | Hide HUD / hide help line |
| R | Restart after the game ends |

## Tuning

- `SurvivalGameMode`: squad size (1-8), resource layout, wave sizes.
- `SurvivalGameState`: day length, nights to survive, starting stockpile.
- Survivor names and personalities are in the `Profiles` table at the top of `SurvivalGameMode.cpp`.
