#!/usr/bin/env python3
"""Quick test: simulate POST /bots using the create_bot handler.

This script injects a lightweight dummy 'fastapi' module so the routers file
can be imported in this environment without installing FastAPI. It then calls
create_bot(...) with the contents of assets/travel_expense_policy.txt.

This is non-destructive except it will write the new bot files under data/bots/.
"""
from __future__ import annotations

import sys
import types
import asyncio
from pathlib import Path
import json

# Provide minimal fastapi shim so import in routers works in this test env
if 'fastapi' not in sys.modules:
    fake_fastapi = types.SimpleNamespace()
    # Minimal HTTPException class used by the router
    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str = ''):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:
        def __init__(self):
            self.headers = {}

    class APIRouter:
        def __init__(self):
            pass
        def post(self, *a, **k):
            def _dec(f):
                return f
            return _dec
        def get(self, *a, **k):
            def _dec(f):
                return f
            return _dec
        def delete(self, *a, **k):
            def _dec(f):
                return f
            return _dec

    fake_fastapi.HTTPException = HTTPException
    fake_fastapi.APIRouter = APIRouter
    fake_fastapi.Request = Request
    sys.modules['fastapi'] = fake_fastapi


async def main():
    # Ensure repo root is on sys.path so 'api' package can be imported
    import sys, os
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    # Import the module under test
    # Import the body-based helper so we can call it directly in this test
    from api.app.routers.bots import _create_bot_from_body as create_bot

    txtp = Path('assets') / 'travel_expense_policy.txt'
    if not txtp.exists():
        print('Policy text not found at', txtp); return
    content = txtp.read_text()

    body = {
        'source_filename': txtp.name,
        'text': content,
        'model': 'gpt-5-mini'
    }

    print('Calling create_bot with source_filename=', body['source_filename'])
    res = await create_bot(body)
    print('Result:')
    print(json.dumps(res, indent=2))
    # Show persisted bot.json
    bid = res.get('id')
    if bid:
        p = Path('data') / 'bots' / bid / 'bot.json'
        if p.exists():
            print('\nPersisted bot.json:')
            print(p.read_text())

if __name__ == '__main__':
    asyncio.run(main())
