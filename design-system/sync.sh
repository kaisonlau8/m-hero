#!/usr/bin/env bash
# 同步设计系统资源到各子系统（含事故车；区域控制台复用 reportdb 副本）。
# 用法：./sync.sh   —— 在 m-hero/design-system/ 目录下执行，或任意位置直接运行。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SRC/.." && pwd)"

# 目标：1) reportdb 静态资源  2) hub  3) auth 包内（提供 css()/sprite() 读取函数）
#       4) NSS 问卷提醒  5) VIP 保养提醒  6) 超时机器人统计  7) 事故车（Jinja 全局读取）
TARGETS=(
  "$ROOT/mhero_district_form/reportdb/assets/ds"
  "$ROOT/m-hero-hub/ds"
  "$ROOT/m-hero-auth/mhero_auth/ds"
  "$ROOT/NSS_Questionnaire_Reminder/ds"
  "$ROOT/m-hero-vip-custom-alert/ds"
  "$ROOT/store-timeout-cleaner/ds"
  "$ROOT/accident-vehicle-reminder/static/ds"
)

BRAND_FILES="logo-white.png logo-white@2x.png logo-blue.png logo-blue@2x.png favicon.ico icon-16.png icon-32.png icon-48.png icon-180.png icon-192.png icon-512.png"

for t in "${TARGETS[@]}"; do
  mkdir -p "$t/brand"
  install -m 644 "$SRC/antd-lite.css" "$t/antd-lite.css"
  install -m 644 "$SRC/cards.js" "$t/cards.js"
  # linebreak.py 只给 Python 侧使用；auth 不需要，避免静态目录多一个可访问文件。
  case "$t" in
    */m-hero-auth/*) ;;
    *) install -m 644 "$SRC/linebreak.py" "$t/linebreak.py" ;;
  esac
  install -m 644 "$SRC/feedback.js" "$t/feedback.js"
  install -m 644 "$SRC/sprite.svg" "$t/sprite.svg"
  for f in $BRAND_FILES; do
    install -m 644 "$SRC/brand/$f" "$t/brand/$f"
  done
  echo "synced -> $t"
done
