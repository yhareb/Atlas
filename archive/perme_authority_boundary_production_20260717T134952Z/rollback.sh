#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for f in atlas_engine.py atlas_macro_context_v1.py atlas_manage.py atlas_portfolio.py; do t="/Users/yasser/scripts/.${f}.rollback.$$"; cp -p "$D/$f" "$t"; mv -f "$t" "/Users/yasser/scripts/$f"; done
rm -f /Users/yasser/scripts/__pycache__/atlas_engine.*.pyc /Users/yasser/scripts/__pycache__/atlas_macro_context_v1.*.pyc /Users/yasser/scripts/__pycache__/atlas_manage.*.pyc /Users/yasser/scripts/__pycache__/atlas_portfolio.*.pyc
