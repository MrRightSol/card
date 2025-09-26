from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from ..services.clawback import (
    create_clawback_job,
    get_clawback_job,
    update_clawback_item,
    simulate_send,
    ensure_clawback_schema,
)
from ..services.clawback import validate_txn_selection

router = APIRouter()


class InitiateBody(BaseModel):
    name: Optional[str] = None
    created_by: Optional[str] = None
    selected_txn_ids: Optional[List[str]] = None
    template_text: Optional[str] = None
    filters_json: Optional[Dict[str, Any]] = None


@router.post('/clawback/initiate')
def initiate(body: InitiateBody) -> Any:
    # Require selected_txn_ids for this endpoint: fetch transaction details
    # directly from the DB so rendered emails contain authoritative data.
    if not body.selected_txn_ids:
        raise HTTPException(status_code=400, detail='selected_txn_ids is required')
    # Ensure DB configured
    from ..services.db import sqlalchemy_url_from_env

    if not sqlalchemy_url_from_env():
        raise HTTPException(status_code=400, detail='database_not_configured')
    try:
        res = create_clawback_job(
            name=body.name,
            created_by=body.created_by,
            selected_txn_ids=body.selected_txn_ids,
            template_text=body.template_text,
            filters_json=body.filters_json,
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/clawback/job/{job_id}')
def get_job(job_id: str) -> Any:
    j = get_clawback_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail='job_not_found')
    return j


@router.get('/clawback/job/{job_id}/item/{item_id}')
def get_item(job_id: str, item_id: str) -> Any:
    j = get_clawback_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail='job_not_found')
    items = j.get('items', [])
    for it in items:
        if it.get('item_id') == item_id:
            return it
    raise HTTPException(status_code=404, detail='item_not_found')


@router.get('/clawback/jobs')
def get_jobs() -> Any:
    try:
        from ..services.clawback import list_clawback_jobs

        return list_clawback_jobs()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ItemPatch(BaseModel):
    rendered_email: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None


@router.patch('/clawback/job/{job_id}/item/{item_id}')
def patch_item(job_id: str, item_id: str, body: ItemPatch) -> Any:
    updates = {}
    if body.rendered_email is not None:
        updates['rendered_email'] = body.rendered_email
    if body.status is not None:
        updates['status'] = body.status
    if body.note is not None:
        updates['note'] = body.note
    out = update_clawback_item(job_id, item_id, updates)
    if not out:
        raise HTTPException(status_code=404, detail='item_not_found')
    return out



class SimulateBody(BaseModel):
    item_ids: Optional[List[str]] = None


@router.post('/clawback/job/{job_id}/simulate-send')
def simulate(job_id: str, body: SimulateBody) -> Any:
    res = simulate_send(job_id, item_ids=body.item_ids)
    return {'results': res}


@router.post('/clawback/init_schema')
def init_schema() -> Any:
    try:
        ensure_clawback_schema()
        return {'status': 'ok'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/clawback/validate-selection')
def validate_selection(body: Dict[str, Any]) -> Any:
    """Validate a list of selected transaction IDs.

    Request body: { "selected_txn_ids": ["T1","T2"] }
    Returns: { missing_txn_ids: [...], employees_count: N, transactions_count: M }
    """
    ids = body.get('selected_txn_ids') if isinstance(body, dict) else None
    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=400, detail='selected_txn_ids is required')
    try:
        res = validate_txn_selection(ids)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class InitiateFromSelectionBody(BaseModel):
    name: Optional[str] = None
    created_by: Optional[str] = None
    selected_txn_ids: Optional[List[str]] = None
    template_text: Optional[str] = None
    filters_json: Optional[Dict[str, Any]] = None
    allow_missing: Optional[bool] = False


@router.post('/clawback/initiate-from-selection')
def initiate_from_selection(body: InitiateFromSelectionBody) -> Any:
    # Require txn ids for this convenience endpoint
    ids = body.selected_txn_ids or []
    if not ids:
        raise HTTPException(status_code=400, detail='selected_txn_ids is required')
    try:
        # Validate selection
        validation = validate_txn_selection(ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'validation_failed: {e}')

    missing = validation.get('missing_txn_ids', [])
    if missing and not bool(body.allow_missing):
        return {
            'status': 'validation_failed',
            'missing_txn_ids': missing,
            'employees_count': validation.get('employees_count', 0),
            'transactions_count': validation.get('transactions_count', 0),
        }

    # Create job (this will raise if DB is required and absent)
    try:
        job = create_clawback_job(
            name=body.name,
            created_by=body.created_by,
            selected_txn_ids=ids,
            template_text=body.template_text,
            filters_json=body.filters_json,
        )
        # Return the created job payload as well so frontends can render
        # immediately without needing a subsequent GET (helps when DB/file
        # access may be inconsistent during redirects).
        return {
            'status': 'created',
            'job_id': job.get('job_id'),
            'items': job.get('items', []),
            'employees_count': job.get('employees_count', len(job.get('items', []))),
            'transactions_count': job.get('transactions_count', 0),
            'job': job,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/clawback/ui')
def clawback_ui(request: Request) -> Any:
    # Improved single-page UI: job listing, per-item email editor with save and simulate
    html = """
<!doctype html>
<html>
<head><meta charset='utf-8'><title>Claw Back Simulator</title></head>
<body>
<h2>Claw Back Simulator</h2>
Job ID: <input id='job' style='width:300px' /> <button onclick='window.loadJob()'>Load</button>
<div id='summary'></div>
<div>
  <button id='prev' onclick='window.prev()' disabled>&lt;&lt;</button>
  <button id='next' onclick='window.next()' disabled>&gt;&gt;</button>
  <button id='notify' onclick='window.notifyAll()' disabled>Notify Employees (simulate)</button>
  <button id='save' onclick='window.saveCurrent()' disabled>Save Email</button>
</div>
<div style='display:flex;gap:20px;margin-top:10px'>
  <div style='min-width:260px'>
    <h4>Jobs</h4>
    <div id='jobs'></div>
  </div>
  <div style='flex:1'>
    <textarea id='email' style='width:100%;height:320px;border:1px solid #ccc;padding:10px'></textarea>
  </div>
</div>
<script>
let job=null; let idx=0; let edited=false; let debounceTimer=null;
window.loadJobsList = async function(){
  const r=await fetch('/clawback/jobs');
  if(!r.ok) return document.getElementById('jobs').innerText='failed to load jobs';
  const arr=await r.json();
  const container=document.getElementById('jobs'); container.innerHTML='';
  for(const j of arr){
    const btn=document.createElement('button');
    btn.style.display='block'; btn.style.width='100%'; btn.style.textAlign='left'; btn.style.marginBottom='6px';
    const txcount = j.transactions_count !== undefined ? j.transactions_count : (j.employees_count || 0);
    btn.innerText=(j.name||'(no name)')+' ['+ (txcount)+'] '+(j.created_at||'');
    btn.onclick=()=>{ document.getElementById('job').value=j.job_id; loadJob(); };
    container.appendChild(btn);
  }
}
window.loadJob = async function(){
  const id=document.getElementById('job').value.trim();
  if(!id) return alert('enter job id');
  const r=await fetch('/clawback/job/'+id);
    if(!r.ok){
    let txt='';
    try{ txt = await r.text(); }catch(e){}
    return alert('failed to load job: '+r.status+' '+r.statusText+'\\n'+txt);
  }
  job=await r.json(); idx=0; render();
}
window.render = function(){
  if(!job) return;
  const items=job.items||[];
  document.getElementById('summary').innerText = 'Employees: '+items.length+' Transactions total: '+(job.transactions_count||'n/a');
  document.getElementById('prev').disabled = idx<=0;
  document.getElementById('next').disabled = idx>=items.length-1;
  document.getElementById('notify').disabled = items.length===0;
  document.getElementById('save').disabled = items.length===0;
  if(items.length>0){
    document.getElementById('email').value = items[idx].rendered_email || '(no email)';
    edited=false;
    document.getElementById('email').oninput = onEdit;
  } else document.getElementById('email').value='(no items)';
}
window.prev = function(){ if(idx>0){ idx--; render(); } }
window.next = function(){ if(job && idx<job.items.length-1){ idx++; render(); } }
window.onEdit = function(){ edited=true; document.getElementById('save').disabled=false; if(debounceTimer) clearTimeout(debounceTimer); debounceTimer=setTimeout(()=>saveCurrent(), 1500); }
window.saveCurrent = async function(){
  if(!job) return; const items=job.items||[]; if(items.length===0) return;
  const it=items[idx];
  const text=document.getElementById('email').value;
  const resp=await fetch('/clawback/job/'+job.job_id+'/item/'+it.item_id, {method:'PATCH', headers:{'content-type':'application/json'}, body: JSON.stringify({rendered_email:text})});
  if(!resp.ok){ alert('save failed'); return; }
  const updated=await resp.json();
  job.items[idx].rendered_email = updated.get('rendered_email') || text;
  edited=false; document.getElementById('save').disabled=true;
}
window.notifyAll = async function(){
  if(!job) return;
  const items=job.items||[];
  document.getElementById('notify').disabled=true;
  for(let i=0;i<items.length;i++){
    document.getElementById('email').value='Sending to '+items[i].employee_id+'...';
    await new Promise(r=>setTimeout(r,250));
    await fetch('/clawback/job/'+job.job_id+'/simulate-send', {method:'POST',headers:{'content-type':'application/json'}, body: JSON.stringify({item_ids:[items[i].item_id]})});
    const res = await fetch('/clawback/job/'+job.job_id+'/item/'+items[i].item_id);
    if(res.ok){ items[i]=await res.json(); }
    document.getElementById('email').value='Sent to '+items[i].employee_id+'\\n\\n'+items[i].rendered_email;
  }
  alert('Simulation complete');
}
// load jobs list on startup
window.loadJobsList();

// If a job query param is provided, auto-load it (e.g. /clawback/ui?job=...)
try{
  const params = new URLSearchParams((window.location && window.location.search) || '');
  const jid = params.get('job');
  if(jid){ document.getElementById('job').value = jid; window.loadJob(); }
}catch(e){ /* ignore */ }

window.render();
</script>
</body>
</html>
"""
    return HTMLResponse(content=html, media_type='text/html')