Coding Standards
================

This project follows these coding standards to improve readability, maintainability and collaboration.

- Use concise, meaningful names for functions and variables.
- Functions should be small and focused; prefer composition over very large functions.
- Include docstrings for all public functions and classes explaining purpose, inputs and outputs.
- Add inline comments where the code intent is not obvious; prefer clear code but document non-trivial logic.
- Logging: emit useful INFO-level messages for important operations and DEBUG-level messages for detailed internal lists. Avoid leaking secrets.
- When interacting with external services (e.g., OpenAI), include robust error handling and explicit logs describing failures.
- Tests: add tests for core parsing and DB logic where possible.

Frontend versioning and compatibility
- This repository targets Angular 20+. When changing Angular or Angular Material versions:
  - Ensure Node.js is at least v20.19 (or use Node 22 LTS).
  - Keep @angular/* packages and @angular/material/@angular/cdk in sync (same major version).
  - Update zone.js to the peer-required version for the target Angular (Angular 20 wants ~0.15.x).
  - Run `npx ng update` in a clean git working tree and resolve any migration output before committing.

Commenting Guidelines
- Provide a short comment at the top of each module describing responsibilities.
- For complex algorithms or fallbacks, add comments describing the strategy.
- Avoid overly verbose comments that restate obvious code behavior.

Formatting
- Follow existing project formatting (Black, ruff, isort when applicable) for Python.
