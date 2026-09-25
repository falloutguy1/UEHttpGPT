"""DayZ-style inventory: clothing and bags provide cargo cells, items occupy
cells, and total weight slows the player down instead of hard-capping them."""

from __future__ import annotations

from dataclasses import dataclass, field

from .combat import Resistances
from .items import Category, ItemStack

EQUIP_SLOTS = ("head", "mask", "top", "vest", "suit", "pants", "feet",
               "back", "wrist", "primary", "secondary", "melee", "belt")

HANDS_CELLS = 0   # items in hands don't use cargo space


@dataclass
class Container:
    name: str
    capacity_cells: int
    items: list = field(default_factory=list)

    @property
    def used_cells(self) -> int:
        return sum(stack.item.cells for stack in self.items)

    def fits(self, stack: ItemStack) -> bool:
        return self.used_cells + stack.item.cells <= self.capacity_cells

    def add(self, stack: ItemStack) -> bool:
        # Merge into existing stacks first.
        for existing in self.items:
            if existing.item.id == stack.item.id and \
                    existing.contaminated == stack.contaminated and \
                    existing.quantity < existing.item.stack:
                moved = min(stack.quantity, existing.item.stack - existing.quantity)
                existing.quantity += moved
                stack.quantity -= moved
                if stack.quantity == 0:
                    return True
        if not self.fits(stack):
            return False
        self.items.append(stack)
        return True


@dataclass
class Inventory:
    equipment: dict = field(default_factory=dict)    # slot -> ItemStack
    containers: dict = field(default_factory=dict)   # slot -> Container
    belt: list = field(default_factory=list)         # artifacts (max 5)
    belt_slots: int = 5
    pockets: Container = field(default_factory=lambda: Container("pockets", 4))

    # --- Equipment ----------------------------------------------------------
    def equip(self, stack: ItemStack) -> ItemStack | None:
        """Equip clothing/weapon/tool. Returns whatever was in the slot."""
        eff = stack.item.effects
        if stack.item.category is Category.ARTIFACT:
            if len(self.belt) >= self.belt_slots:
                raise ValueError("artifact belt is full")
            self.belt.append(stack)
            return None
        if stack.item.category is Category.WEAPON:
            slot = "melee" if eff.get("dtype") == "melee" else \
                "primary" if stack.item.size[0] >= 5 else "secondary"
        elif stack.item.category is Category.CONTAINER:
            slot = "back"
        else:
            slot = eff.get("slot")
        if slot not in EQUIP_SLOTS:
            raise ValueError(f"{stack.item.name} cannot be equipped")
        previous = self.equipment.get(slot)
        self.equipment[slot] = stack
        # The old item's cargo drops with it; the new item brings empty cargo.
        self.containers.pop(slot, None)
        cells = int(eff.get("capacity_cells", 0))
        if cells:
            self.containers[slot] = Container(stack.item.name, cells)
        return previous

    def equipped(self, slot: str) -> ItemStack | None:
        return self.equipment.get(slot)

    def pick_up(self, stack: ItemStack) -> bool:
        """DayZ-style pickup: wear it if the matching slot is empty, otherwise
        put it in cargo."""
        cat = stack.item.category
        slot = "back" if cat is Category.CONTAINER else stack.item.effects.get("slot")
        if cat in (Category.CONTAINER, Category.CLOTHING) and slot and \
                slot not in self.equipment:
            self.equip(stack)
            return True
        return self.add(stack)

    # --- Cargo --------------------------------------------------------------
    def all_containers(self) -> list:
        return [self.pockets, *self.containers.values()]

    def add(self, stack: ItemStack) -> bool:
        for container in self.all_containers():
            if container.add(stack):
                return True
        return False

    def iter_stacks(self):
        for container in self.all_containers():
            yield from container.items

    def count(self, item_id: str) -> int:
        return sum(s.quantity for s in self.iter_stacks() if s.item.id == item_id)

    def take(self, item_id: str, quantity: int = 1) -> ItemStack | None:
        """Removes up to ``quantity`` of an item and returns it as one stack."""
        if self.count(item_id) < quantity:
            return None
        taken = None
        for container in self.all_containers():
            for stack in list(container.items):
                if stack.item.id != item_id or quantity == 0:
                    continue
                use = min(stack.quantity, quantity)
                stack.quantity -= use
                quantity -= use
                if taken is None:
                    taken = ItemStack(stack.item, use, stack.condition,
                                      stack.contaminated)
                else:
                    taken.quantity += use
                if stack.quantity == 0:
                    container.items.remove(stack)
        return taken

    # --- Aggregates ---------------------------------------------------------
    @property
    def total_weight(self) -> float:
        worn = sum(s.weight for s in self.equipment.values())
        worn += sum(s.weight for s in self.belt)
        return worn + sum(s.weight for s in self.iter_stacks())

    def armor(self) -> Resistances:
        res = Resistances()
        for stack in self.equipment.values():
            armor = stack.item.effects.get("armor")
            if armor:
                scaled = {k: v * max(0.2, stack.condition) for k, v in armor.items()}
                res = res.combined(Resistances(scaled))
        return res

    def insulation(self) -> float:
        """0 = naked, ~1 = arctic gear."""
        total = sum(s.item.effects.get("insulation", 0.0) * s.condition
                    for s in self.equipment.values())
        return min(1.0, total)

    def waterproofing(self) -> float:
        values = [s.item.effects.get("waterproof", 0.0)
                  for s in self.equipment.values()]
        return max(values, default=0.0)

    def is_sealed(self) -> bool:
        """A sealed suit (SEVA, hazmat) acts as a mask for toxic air."""
        suit = self.equipment.get("suit")
        return bool(suit and suit.item.effects.get("sealed"))

    def artifact_effect(self, key: str, default: float = 0.0,
                        multiplicative: bool = False) -> float:
        value = default
        for stack in self.belt:
            eff = stack.item.effects.get("worn", {})
            if key in eff:
                value = value * eff[key] if multiplicative else value + eff[key]
        return value
