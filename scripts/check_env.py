"""Quick environment checker for required Python packages.

Run: python3 scripts/check_env.py
It will print which packages are importable and which are missing.
"""
reqs = [
    'fastapi', 'uvicorn', 'pydantic', 'pandas', 'numpy', 'scikit_learn',
    'openai', 'python_multipart', 'openpyxl'
]

# Map to import names where they differ
mapping = {
    'scikit_learn': 'sklearn',
    'python_multipart': 'multipart',
}

missing = []
for pkg in reqs:
    name = mapping.get(pkg, pkg)
    try:
        __import__(name)
        print(f'OK:   {pkg} (import {name})')
    except Exception as e:
        print(f'MISS: {pkg} (import {name}) -> {e.__class__.__name__}: {e}')
        missing.append(pkg)

if missing:
    print('\nMissing packages detected. Install with:')
    print('  python -m pip install -r requirements.txt')
else:
    print('\nAll required packages appear installed.')
