#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cargo test --workspace
cargo build --release -p infinite-red-worldgen
mkdir -p runtime/godot/bin
cp target/release/worldgen runtime/godot/bin/worldgen
chmod +x runtime/godot/bin/worldgen

echo "Core and Godot bridge are ready. Open runtime/godot/project.godot in Godot 4.7.2+."
