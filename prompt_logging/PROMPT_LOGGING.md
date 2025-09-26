
# Prompt Logging & Showcase

## Goal
Capture every prompt/response used to build the app and display them in a data grid during the demo.

## Storage Options
1) **DB Table (MSSQL)** – recommended for search/filter.
2) **Flat JSON file** – easy offline fallback: `data/prompts_log.json`.

## MSSQL Table
```sql
CREATE TABLE Prompts (
  id UNIQUEIDENTIFIER DEFAULT NEWID() PRIMARY KEY,
  created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  source NVARCHAR(64) NOT NULL,        -- 'cli','ui','codex','postman','misc'
  role NVARCHAR(16) NOT NULL,          -- 'user','system','assistant'
  title NVARCHAR(200) NULL,
  tags NVARCHAR(200) NULL,             -- comma-separated
  content NVARCHAR(MAX) NOT NULL,
  content_hash CHAR(64) NOT NULL
);
CREATE INDEX IX_Prompts_CreatedAt ON Prompts(created_at);
CREATE INDEX IX_Prompts_Tags ON Prompts(tags);
```

## FastAPI Snippet
```python
# app/routers/prompts.py
from fastapi import APIRouter
from pydantic import BaseModel
import hashlib, json, datetime

router = APIRouter(prefix="/prompts", tags=["prompts"])

class PromptIn(BaseModel):
    source: str
    role: str
    title: str | None = None
    tags: str | None = None
    content: str

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

@router.post("")
def create_prompt(p: PromptIn):
    body = p.model_dump()
    body["content_hash"] = sha256(p.content)
    # TODO: persist to DB; fallback write to ./data/prompts_log.jsonl
    return body

@router.get("")
def list_prompts(limit: int = 100, q: str | None = None):
    # TODO: read from DB or JSON and filter by 'q' in title/content/tags
    return {"items": [], "total": 0}
```

## Angular Snippet (Data Grid)
```ts
// prompts-table.component.ts
@Component({ selector:'app-prompts-table', standalone:true, templateUrl:'./prompts-table.component.html' })
export class PromptsTableComponent {
  prompts = signal<any[]>([]);
  async ngOnInit() {
    const res = await fetch(`${(import.meta as any).env.VITE_API_URL}/prompts`);
    const data = await res.json();
    this.prompts.set(data.items ?? []);
  }
}
```
```html
<!-- prompts-table.component.html -->
<div class="toolbar">
  <input placeholder="Search prompts..." />
</div>
<table>
  <thead><tr><th>When</th><th>Source</th><th>Role</th><th>Title</th><th>Tags</th></tr></thead>
  <tbody>
    <tr *ngFor="let p of prompts()">
      <td>{{ p.created_at || '-' }}</td>
      <td>{{ p.source }}</td>
      <td>{{ p.role }}</td>
      <td>{{ p.title }}</td>
      <td>{{ p.tags }}</td>
    </tr>
  </tbody>
</table>
```
