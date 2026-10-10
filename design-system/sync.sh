#!/usr/bin/env bash
# 同步设计系统资源到三个子系统（reportdb / hub / auth）。
# 用法：./sync.sh   —— 在 m-hero/design-system/ 目录下执行，或任意位置直接运行。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SRC/.." && pwd)"

# 目标：1) reportdb 静态资源  2) hub  3) auth 包内（提供 css()/sprite() 读取函数）
TARGETS=(
  "$ROOT/mhero_district_form/reportdb/assets/ds"
  "$ROOT/m-hero-hub/ds"
  "$ROOT/m-hero-auth/mhero_auth/ds"
)

for t in "${TARGETS[@]}"; do
  mkdir -p "$t"
  install -m 644 "$SRC/antd-lite.css" "$t/antd-lite.css"
  install -m 644 "$SRC/sprite.svg" "$t/sprite.svg"
  echo "synced -> $t"
done
