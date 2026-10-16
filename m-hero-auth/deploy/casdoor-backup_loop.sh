#!/bin/bash
# daily consistent sqlite backup at ~03:10 local, keep 14 days
D=$HOME/m-hero-run/data/casdoor; B=$HOME/m-hero-run/data/casdoor-backup
umask 077
while true; do
  now=$(date +%s); next=$(date -d "today 03:10" +%s); [ $next -le $now ] && next=$(date -d "tomorrow 03:10" +%s)
  sleep $((next-now))
  python3 -c "
import sqlite3,datetime,sys
s=sqlite3.connect('$D/casdoor.db'); d=sqlite3.connect('$B/casdoor-%s.db'%datetime.date.today()); s.backup(d); d.close()
print('backup ok',datetime.datetime.now())" || echo "backup FAILED"
  find $B -name 'casdoor-*.db' -mtime +14 -delete
  sleep 60
done
