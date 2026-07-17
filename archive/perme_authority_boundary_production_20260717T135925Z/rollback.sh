#!/bin/bash
set -e
for f in atlas_engine.py atlas_macro_context_v1.py atlas_manage.py atlas_portfolio.py; do cp -p "/Users/yasser/scripts/archive/perme_authority_boundary_production_20260717T135925Z/$f" "/Users/yasser/scripts/.$f.rollback.$$"; mv -f "/Users/yasser/scripts/.$f.rollback.$$" "/Users/yasser/scripts/$f"; done
