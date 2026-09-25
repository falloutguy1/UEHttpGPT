"""Traders and currencies: bottle caps on the surface, military-grade ammo in the
Metro (which you can also fire, at a loss), and barter everywhere."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import items
from .factions import FACTIONS, Reputation
from .inventory import Inventory

# Value of one unit of each currency, in bottle caps.
CURRENCY_VALUE = {"bottle_caps": 1.0, "ammo_545_mil": 10.0}


@dataclass
class Trader:
    name: str
    faction: str
    stock: dict = field(default_factory=dict)   # item id -> quantity
    markup: float = 1.3                          # sells at value * markup
    buyback: float = 0.45                        # buys at value * buyback
    wants: tuple = ()                            # categories paid at a premium

    @property
    def currency(self) -> str:
        return FACTIONS[self.faction].currency

    def _unit(self) -> float:
        return CURRENCY_VALUE[self.currency]

    def sell_price(self, item_id: str, barter_mod: float, rep: Reputation) -> int:
        """What the player pays, in the trader's currency."""
        caps = items.get(item_id).value * self.markup * barter_mod * \
            rep.price_multiplier(self.faction)
        return max(1, round(caps / self._unit()))

    def buy_price(self, stack: items.ItemStack, barter_mod: float,
                  rep: Reputation) -> int:
        """What the trader pays the player for a stack."""
        premium = 1.5 if stack.item.category.value in self.wants else 1.0
        caps = stack.item.value * stack.quantity * self.buyback * premium * \
            stack.condition * (2.0 - barter_mod) * (2.0 - rep.price_multiplier(self.faction))
        return int(caps / self._unit())

    def buy_from(self, inv: Inventory, item_id: str, barter_mod: float,
                 rep: Reputation) -> bool:
        if self.stock.get(item_id, 0) <= 0 or rep.is_hostile(self.faction):
            return False
        price = self.sell_price(item_id, barter_mod, rep)
        if inv.count(self.currency) < price:
            return False
        bought = items.make(item_id)
        if not inv.add(bought):
            return False
        inv.take(self.currency, price)
        self.stock[item_id] -= 1
        return True

    def sell_to(self, inv: Inventory, item_id: str, barter_mod: float,
                rep: Reputation) -> int:
        stack = inv.take(item_id, inv.count(item_id))
        if stack is None:
            return 0
        price = self.buy_price(stack, barter_mod, rep)
        if price and inv.add(items.make(self.currency, price)):
            self.stock[item_id] = self.stock.get(item_id, 0) + stack.quantity
            return price
        inv.add(stack)   # couldn't pay out: give the goods back
        return 0

    def restock(self, rng: random.Random) -> None:
        for item_id in list(self.stock):
            self.stock[item_id] = max(self.stock[item_id], rng.randint(1, 4))


def default_traders() -> list:
    return [
        Trader("Sidorovich", "survivors",
               {"bandage": 5, "canned_beans": 6, "vodka_cossacks": 4,
                "detector_echo": 1, "ammo_545_dirty": 3, "bolt": 3},
               wants=("artifact",)),
        Trader("Knight Quartermaster", "brotherhood",
               {"stimpak": 3, "radaway": 2, "rad_x": 3, "microfusion_cell": 4,
                "laser_pistol": 1}, markup=1.6, wants=("junk",)),
        Trader("Hansa Supply", "hansa",
               {"filter": 6, "gas_mask": 2, "military_ration": 4,
                "ammo_545_dirty": 5, "bastard_smg": 1, "mushroom_tea": 8},
               wants=("filter", "weapon")),
    ]
