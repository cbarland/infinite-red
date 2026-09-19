from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pokered_native import (
    BLOCK_TILES,
    TILES_PER_BLOCK,
    assert_pallet_town,
    expand_blocks,
    load_blockset,
    load_map,
    generate_first_route,
    generate_location_names,
    generate_route1_variant,
    write_first_geography,
    write_roundtrip,
)

REPO = os.environ.get("POKERED_REPO")


@unittest.skipUnless(REPO, "POKERED_REPO must point to a pinned pret/pokered checkout")
class NativePalletTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(REPO)

    def test_pallet_contract(self) -> None:
        pallet = assert_pallet_town(self.repo)
        self.assertEqual((pallet.width, pallet.height), (10, 9))
        self.assertEqual(pallet.block_count, 90)

    def test_block_expansion_shape(self) -> None:
        pallet = load_map(self.repo, "PalletTown")
        blockset = load_blockset(self.repo, pallet.tileset)
        self.assertEqual(len(blockset) % TILES_PER_BLOCK, 0)
        grid = expand_blocks(pallet, blockset)
        self.assertEqual(len(grid), pallet.height * BLOCK_TILES)
        self.assertTrue(
            all(len(row) == pallet.width * BLOCK_TILES for row in grid)
        )

    def test_roundtrip_is_byte_exact(self) -> None:
        pallet = load_map(self.repo, "PalletTown")
        with tempfile.TemporaryDirectory() as td:
            block_path, manifest_path = write_roundtrip(pallet, Path(td))
            self.assertEqual(
                block_path.read_bytes(),
                (self.repo / "maps" / "PalletTown.blk").read_bytes(),
            )
            self.assertTrue(manifest_path.exists())

    def test_route1_variant_is_native_and_collision_equivalent(self) -> None:
        route, generated, manifest = generate_route1_variant(self.repo, 42)
        self.assertEqual(len(generated), route.width * route.height)
        self.assertNotEqual(generated, route.block_bytes)
        self.assertGreater(manifest["changed_blocks"], 0)

        width = route.width
        height = route.height
        for x in range(width):
            self.assertEqual(generated[x], route.block_bytes[x])
            bottom = (height - 1) * width + x
            self.assertEqual(generated[bottom], route.block_bytes[bottom])
        for y in range(height):
            left = y * width
            right = left + width - 1
            self.assertEqual(generated[left], route.block_bytes[left])
            self.assertEqual(generated[right], route.block_bytes[right])

    def test_route1_variant_is_deterministic(self) -> None:
        _, first, _ = generate_route1_variant(self.repo, 42)
        _, second, _ = generate_route1_variant(self.repo, 42)
        self.assertEqual(first, second)

    def test_first_route_is_new_geography_with_only_pallet_seam_preserved(self) -> None:
        slot, generated, manifest = generate_first_route(self.repo, 42)
        width = slot.width
        height = slot.height
        self.assertEqual(len(generated), width * height)
        self.assertLessEqual(manifest["source_same_cells"], 70)
        self.assertEqual(
            generated[(height - 1) * width :],
            slot.block_bytes[(height - 1) * width :],
        )
        self.assertNotEqual(
            generated[: (height - 1) * width],
            slot.block_bytes[: (height - 1) * width],
        )

    def test_location_names_are_generated_and_deterministic(self) -> None:
        first = generate_location_names(42)
        second = generate_location_names(42)
        other = generate_location_names(43)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotIn(first["route"], {"ROUTE 1", "PALLET TOWN"})
        self.assertNotIn(first["settlement"], {"VIRIDIAN CITY", "PALLET TOWN"})
        self.assertLessEqual(len(first["route"]), 18)
        self.assertLessEqual(len(first["settlement"]), 18)

    def test_first_geography_patch_removes_player_facing_slot_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest = write_first_geography(self.repo, 42, Path(td))
            root = Path(td) / "patch"
            names = (root / "data" / "maps" / "names.asm").read_text(encoding="utf-8")
            route_text = (root / "text" / "Route1.asm").read_text(encoding="utf-8")
            objects = (
                root / "data" / "maps" / "objects" / "Route1.asm"
            ).read_text(encoding="utf-8")
            self.assertIn(f'Route1Name: db "{manifest["route_name"]}@"', names)
            self.assertIn(
                f'ViridianCityName: db "{manifest["north_settlement_name"]}@"',
                names,
            )
            self.assertNotIn("VIRIDIAN CITY", route_text)
            self.assertNotIn("ROUTE 1", route_text)
            self.assertIn(manifest["route_name"], route_text)
            self.assertIn(manifest["north_settlement_name"], route_text)
            self.assertIn("TEXT_ROUTE1_SIGN", objects)


if __name__ == "__main__":
    unittest.main()
