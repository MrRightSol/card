#!/usr/bin/env python3
"""Migrate existing bot.json names from old epoch-ms format to the new compact UTC timestamp format.

Usage:
  scripts/migrate_bot_names.py [--apply]

Without --apply the script will only print proposed changes. With --apply it will update bot.json files in-place.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime
import re


def new_name_from_old(old_name: str, mtime: float, default_model: str = 'gpt-5-mini') -> str:
    # Extract base and model if the old_name contains epoch-like segment
    parts = old_name.split('_')
    src_base_parts = parts
    model = None
    for idx, p in enumerate(parts):
        if p.isdigit() and 10 <= len(p) <= 13:
            src_base_parts = parts[:idx]
            if idx + 1 < len(parts) and 'gpt' in parts[idx+1].lower():
                model = parts[idx+1]
            break
    if not model and len(parts) > 1 and 'gpt' in parts[-1].lower():
        model = parts[-1]
        src_base_parts = parts[:-1]

    src_base = '_'.join(src_base_parts) if src_base_parts else old_name
    src_base = src_base.replace(' ', '_')
    model = model or default_model
    ts = datetime.utcfromtimestamp(mtime).strftime('%b%d%Y_%H%M%S')
    return f"{src_base}_{ts}__{model}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Apply the changes')
    args = parser.parse_args()

    base = Path('data') / 'bots'
    if not base.exists():
        print('No data/bots directory present. Nothing to do.')
        return

    changed = 0
    for p in sorted(base.iterdir()):
        botjson = p / 'bot.json'
        if not botjson.exists():
            continue
        try:
            obj = json.loads(botjson.read_text())
        except Exception:
            print(f'Failed to read {botjson}; skipping')
            continue
        name = obj.get('name')
        if not name:
            continue
        # detect old-style epoch in name
        if re.search(r'_\d{10,13}_', name) or re.search(r'_\d{10,13}$', name):
            mtime = botjson.stat().st_mtime
            new_name = new_name_from_old(name, mtime, obj.get('model') or 'gpt-5-mini')
            print(f'{botjson}:')
            print(f'  old: {name}')
            print(f'  new: {new_name}')
            if args.apply:
                obj['name'] = new_name
                botjson.write_text(json.dumps(obj, indent=2))
                changed += 1

    print(f'Done. {changed} files updated.' if args.apply else 'Dry run complete.')


if __name__ == '__main__':
    main()
