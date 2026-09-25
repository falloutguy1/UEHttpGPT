"""Factions and reputation, mixing the Zone's groups, the wasteland's and the
Metro's. Also holds the persona prompts NPCs use with HttpGPT for dialogue."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Faction:
    id: str
    name: str
    origin: str
    currency: str                  # item id they prefer to trade in
    home: str                      # POI kind they hold
    persona: str                   # system prompt seed for HttpGPT dialogue
    hostile_by_default: bool = False


FACTIONS = {f.id: f for f in (
    Faction("survivors", "Survivors", "dayz", "bottle_caps", "town",
            "You are a wary survivor in a collapsed post-Soviet country. You "
            "share rumours about loot and infected, but you never trust strangers "
            "with guns drawn."),
    Faction("bandits", "Bandits", "dayz", "bottle_caps", "town",
            "You are a bandit who robs travellers. You speak in threats and "
            "slang, demand gear and caps, and back down if outgunned.", True),
    Faction("duty", "Duty", "stalker", "bottle_caps", "military",
            "You are a disciplined Duty soldier who believes the Zone must be "
            "destroyed. You hate Freedom and mutants, and reward artifact hunters "
            "who help the cause."),
    Faction("freedom", "Freedom", "stalker", "bottle_caps", "industrial",
            "You are a laid-back Freedom stalker who thinks the Zone should be "
            "open to all. You mock Duty and trade artifacts for a fair price."),
    Faction("monolith", "Monolith", "stalker", "bottle_caps", "anomaly_field",
            "You are a Monolith zealot. Speak only in fragments of prayer to the "
            "Monolith and warn intruders to turn back.", True),
    Faction("brotherhood", "Brotherhood of Steel", "fallout", "bottle_caps", "vault",
            "You are a Brotherhood of Steel paladin. You value pre-war technology "
            "above lives and treat outsiders as 'wastelanders'."),
    Faction("raiders", "Raiders", "fallout", "bottle_caps", "crater",
            "You are a chem-addled raider. Be erratic, violent and funny.", True),
    Faction("hansa", "Hansa", "metro", "ammo_545_mil", "metro_station",
            "You are a Hansa customs officer on the Ring Line. Everything has a "
            "price, paid in military-grade rounds. Ask for papers."),
    Faction("red_line", "Red Line", "metro", "ammo_545_mil", "metro_station",
            "You are a Red Line comrade. Speak of the Party, the collective and "
            "suspicion of Reich spies."),
    Faction("reich", "Fourth Reich", "metro", "ammo_545_mil", "metro_station",
            "You are a Reich guard. Be cold and bureaucratic; you hate the Red Line.",
            True),
    Faction("rangers", "Spartan Rangers", "metro", "ammo_545_mil", "metro_station",
            "You are an Order ranger from Polis. Terse, protective of the metro, "
            "and deeply worried about the Dark Ones."),
)}

# Standing between factions: -1 hostile, 0 neutral, 1 allied.
RELATIONS = {
    ("duty", "freedom"): -1, ("duty", "monolith"): -1, ("freedom", "monolith"): -1,
    ("red_line", "reich"): -1, ("hansa", "red_line"): 0, ("rangers", "reich"): -1,
    ("rangers", "hansa"): 1, ("survivors", "bandits"): -1, ("brotherhood", "raiders"): -1,
    ("survivors", "brotherhood"): 0, ("bandits", "raiders"): 1,
}


def relation(a: str, b: str) -> int:
    if a == b:
        return 1
    return RELATIONS.get((a, b), RELATIONS.get((b, a), 0))


def standing_label(rep: int) -> str:
    if rep <= -500:
        return "Hated"
    if rep <= -100:
        return "Disliked"
    if rep < 100:
        return "Neutral"
    if rep < 500:
        return "Liked"
    return "Idolized"


@dataclass
class Reputation:
    values: dict = field(default_factory=lambda: {f: 0 for f in FACTIONS})

    def change(self, faction_id: str, delta: int, ripple: bool = True) -> None:
        """Helping (or hurting) one faction ripples to its allies and enemies."""
        self.values[faction_id] = max(-1000, min(1000, self.values[faction_id] + delta))
        if ripple:
            for other in FACTIONS:
                rel = relation(faction_id, other)
                if other != faction_id and rel:
                    self.change(other, int(delta * 0.5 * rel), ripple=False)

    def is_hostile(self, faction_id: str) -> bool:
        if self.values[faction_id] <= -300:
            return True
        return FACTIONS[faction_id].hostile_by_default and self.values[faction_id] < 200

    def label(self, faction_id: str) -> str:
        return standing_label(self.values[faction_id])

    def price_multiplier(self, faction_id: str) -> float:
        return 1.0 - self.values[faction_id] / 5000.0   # +-20% at the extremes

    def dialogue_prompt(self, faction_id: str, player_name: str,
                        karma_title: str) -> str:
        """System prompt for an HttpGPT chat request when talking to an NPC."""
        f = FACTIONS[faction_id]
        return (f"{f.persona}\nThe player, {player_name}, is {self.label(faction_id)} "
                f"by your faction and is known as a {karma_title}. Stay in "
                f"character, reply in at most three sentences, and never mention "
                f"being an AI.")
