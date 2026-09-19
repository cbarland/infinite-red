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


if __name__ == "__main__":
    unittest.main()
