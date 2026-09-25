"""
Wasteland: a DayZ-style open-world survival core with Fallout, S.T.A.L.K.E.R.
and Metro systems layered on top.

The ``wasteland`` package is pure Python with no Unreal dependency, so it can be
unit-tested, balanced and simulated headless. The ``unreal_tools`` package next
to it uses the simulation from inside the Unreal Editor (asset import, level
building and a Play-In-Editor prototype bridge).

Pillars
-------
* DayZ     - vitals (energy, water, blood, shock, temperature), bleeding,
             diseases, infected hordes, persistent loot, permadeath.
* Fallout  - S.P.E.C.I.A.L., perks, XP/levels, karma, rads that cap max HP,
             bottle caps, V.A.T.S.-style targeting.
* STALKER  - anomalies, bolts, detectors, artifacts, emissions (blowouts),
             faction reputation, mutants.
* Metro    - gas masks with filter timers and cracked visors, toxic surface,
             military-grade ammo as currency, metro station hubs.
"""

__version__ = "0.1.0"
