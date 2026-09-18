$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

cargo test --workspace
cargo build --release -p infinite-red-worldgen
New-Item -ItemType Directory -Force -Path "runtime/godot/bin" | Out-Null
Copy-Item "target/release/worldgen.exe" "runtime/godot/bin/worldgen.exe" -Force

Write-Host "Core and Godot bridge are ready. Open runtime/godot/project.godot in Godot 4.7.2+."
