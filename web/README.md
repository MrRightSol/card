# Frontend (Angular 20) – Quickstart

Prereqs
- Node.js 20.19+ (or Node 22 LTS)
- npm 10+
- Angular CLI v20: npm i -g @angular/cli@20

Important compatibility note
- This project targets Angular 20 and Angular Material 20. Always ensure the Angular core packages, Angular Material/CDK and zone.js versions are compatible before installing/upgrading. Mismatched Angular and Material versions are a common cause of runtime/schema errors.

Quick checklist before running npm install or ng update
- Confirm Node.js version: node -v (must be >= v20.19 or >= v22.12)
- Check package.json in web/ for @angular/core and @angular/material versions — they should both be ^20.x
- Check zone.js version in web/package.json — Angular 20 requires zone.js ~0.15.x (we use ^0.15.1)
- If you change Angular versions, run the Angular migration schematics: npx ng update @angular/core@20 @angular/cli@20 --force
- If npm fails on peer deps, consider npm install --legacy-peer-deps (temporary) or update package versions to match Angular 20

Install and run (Angular 18 scaffold due to registry constraints)
- cd web
- npm install   # first time; generates package-lock.json (npm ci needs a lock file)
- npm start
- Open http://localhost:5173

Configure API URL
- The app uses localStorage key VITE_API_URL to point to the backend (default http://localhost:8080)
- In browser devtools console, you can set:
  - localStorage.setItem('VITE_API_URL','http://localhost:8080'); location.reload();

What’s included
- Minimal Angular 20 standalone app using bootstrapApplication
- Simple 4-step flow:
  1. Generate synthetic data
  2. Parse policy (text or file)
  3. Train
  4. Score + table view
- Logs panel fetching GET /logs
- Dark theme with small animations/transitions

Notes
- This scaffold avoids Material to keep deps small. We can add Angular Material or Tailwind next.
- The app uses fetch() and no state library; easy to replace with HttpClient later.
