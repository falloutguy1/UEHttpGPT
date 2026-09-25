"""Heightmap generator for an Unreal Landscape, matched to ``WorldLayout``.

Writes a 16-bit grayscale PNG (no third-party libraries): rolling hills in the
west, a flattened city basin in the centre, and scarred terrain with craters
in the east. Towns are flattened so buildings sit level.

In Unreal: Landscape Mode -> Manage -> New -> Import from File -> pick the PNG.
Use the printed scale so 1 pixel matches the world layout.

    python -m wasteland.terrain --seed 1986 --size 505 --out Exports/heightmap.png
"""

from __future__ import annotations

import argparse
import math
import random
import struct
import zlib
from pathlib import Path

from .world import WorldLayout

VALID_SIZES = (127, 253, 505, 1009, 2017, 4033, 8129)   # UE-recommended


class ValueNoise:
    def __init__(self, seed: int, grid: int = 256):
        rng = random.Random(seed)
        self.grid = grid
        self.values = [rng.random() for _ in range(grid * grid)]

    def _v(self, x: int, y: int) -> float:
        return self.values[(y % self.grid) * self.grid + (x % self.grid)]

    def sample(self, x: float, y: float) -> float:
        xi, yi = math.floor(x), math.floor(y)
        tx, ty = x - xi, y - yi
        sx, sy = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        a = self._v(xi, yi) + (self._v(xi + 1, yi) - self._v(xi, yi)) * sx
        b = self._v(xi, yi + 1) + (self._v(xi + 1, yi + 1) - self._v(xi, yi + 1)) * sx
        return a + (b - a) * sy

    def fbm(self, x: float, y: float, octaves: int = 5) -> float:
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += self.sample(x * freq, y * freq) * amp
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return total / norm


class Terrain:
    """Height field in 0..1 for any world position (metres)."""

    def __init__(self, world: WorldLayout):
        self.world = world
        self.noise = ValueNoise(world.seed)
        self.flatten = [(p.x, p.y, p.radius_m * 1.2, self._base(p.x, p.y))
                        for p in world.pois if p.kind not in ("crater", "anomaly_field")]
        self.craters = [(p.x, p.y, p.radius_m) for p in world.pois if p.kind == "crater"]

    def _base(self, wx: float, wy: float) -> float:
        size = self.world.size_m
        return 0.35 + 0.45 * self.noise.fbm(wx / size * 8.0, wy / size * 8.0)

    def height_at(self, wx: float, wy: float) -> float:
        size = self.world.size_m
        u, v = wx / size * 8.0, wy / size * 8.0
        h = self._base(wx, wy)
        # East: sharper, eroded ridges.
        east = max(0.0, wx / size - 0.6) / 0.4
        h += east * 0.15 * (abs(self.noise.fbm(u * 3 + 17, v * 3 + 5, 3) - 0.5) * 2)
        # Centre: the city sits in a wide basin.
        cx, cy, cr = self.world.dead_city
        d = math.hypot(wx - cx, wy - cy)
        if d < cr * 1.8:
            t = 1.0 - d / (cr * 1.8)
            h = h * (1 - t) + 0.3 * t
        # Settlements are flattened toward their local height.
        for fx, fy, fr, base in self.flatten:
            d = math.hypot(wx - fx, wy - fy)
            if d < fr:
                t = (1.0 - d / fr) ** 2
                h = h * (1 - t) + base * t
        # Bomb craters: bowl with a raised rim.
        for kx, ky, kr in self.craters:
            d = math.hypot(wx - kx, wy - ky) / kr
            if d < 1.4:
                h += -0.12 * math.cos(min(d, 1.0) * math.pi / 2) \
                     + 0.04 * math.exp(-((d - 1.0) ** 2) / 0.02)
        return max(0.0, min(1.0, h))

    def height_uu(self, wx: float, wy: float, z_scale: float) -> float:
        """World Z in Unreal units for a Landscape imported with ``z_scale``
        (16-bit value 32768 sits at the actor's Z, 128 steps per unit scale)."""
        return (self.height_at(wx, wy) * 65535 - 32768) / 128.0 * z_scale


def generate(world: WorldLayout, size: int = 505) -> list:
    """Returns rows of heights in 0..1."""
    terrain = Terrain(world)
    m_per_px = world.size_m / (size - 1)
    return [[terrain.height_at(px * m_per_px, py * m_per_px) for px in range(size)]
            for py in range(size)]


def write_png16(path: Path, rows: list) -> None:
    height, width = len(rows), len(rows[0])
    raw = bytearray()
    for row in rows:
        raw.append(0)   # filter type: none
        for value in row:
            raw += struct.pack(">H", int(value * 65535))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + \
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def landscape_scale(world: WorldLayout, size: int, height_range_m: float = 400.0) -> tuple:
    """Landscape actor scale (X, Y, Z) in Unreal units for the import dialog.
    Z scale 100 = 512 m of range, so scale to the height range we want."""
    xy = world.size_m * 100.0 / (size - 1)
    z = height_range_m / 512.0 * 100.0
    return round(xy, 3), round(xy, 3), round(z, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a landscape heightmap")
    parser.add_argument("--seed", type=int, default=1986)
    parser.add_argument("--size", type=int, default=505, choices=VALID_SIZES)
    parser.add_argument("--out", default="Exports/heightmap.png")
    args = parser.parse_args()
    world = WorldLayout(args.seed)
    write_png16(Path(args.out), generate(world, args.size))
    print(f"Wrote {args.out}. Landscape scale (X, Y, Z): "
          f"{landscape_scale(world, args.size)}")


if __name__ == "__main__":
    main()
