from fastapi import APIRouter, HTTPException, Request
from fastapi import BackgroundTasks
from typing import Any
from pathlib import Path
import json, uuid, logging

log = logging.getLogger(__name__)

router = APIRouter()

# Models that are known to not accept temperature or max tokens
_MODELS_NO_TEMPERATURE = [
    'gpt-5-mini',
    'gpt-5',
]

def _model_allows_temperature(model_name: str) -> bool:
    if not model_name:
        return True
    mn = model_name.lower()
    for bad in _MODELS_NO_TEMPERATURE:
        if bad in mn:
            return False
    return True


async def _create_bot_from_body(body: dict) -> Any:
    """Create a bot from policy text. Expects JSON: { name: str, text: str, model?: str, k?: int }
    This is a minimal implementation that chunks the text and stores chunks for brute-force retrieval.
    """
    # Name precedence: explicit name -> derived from source filename (if provided) -> generated short id
    provided_name = body.get('name')
    # If the client passed a generic auto-generated name like 'bot_974615' treat it
    # as not provided so we will derive a clearer name from the source filename.
    if provided_name:
        try:
            import re
            if re.match(r"^bot[_-]?[0-9a-fA-F]+$", provided_name):
                provided_name = None
        except Exception:
            pass

    # If the client passed a generated name using the old epoch-ms format
    # (e.g. Travel_Expense_Policy.docx_1758517096518_gpt-5-mini), detect that and
    # rewrite it into the new compact timestamp format so the UI shows a
    # consistent naming scheme even if the front-end sent an auto-generated name.
    # If we detect such a name, capture the original base filename so we can
    # prefer it later when constructing a derived name.
    derived_source_from_name = None
    if provided_name:
        try:
            # look for: <base>_<10-13 digits>[_<model>]
            import re
            m = re.match(r"^(?P<base>.+)_(?P<epoch>\d{10,13})(?:_(?P<model>.+))?$", provided_name)
            if m:
                base = m.group('base')
                possible_model = m.group('model')
                # capture base to prefer as source filename when building a nicer name
                derived_source_from_name = base
                if possible_model and not body.get('model'):
                    body['model'] = possible_model
                provided_name = None
        except Exception:
            pass
    # Accept multiple common keys that may be provided by the client/front-end
    source_filename = body.get('source_filename') or body.get('file_name') or body.get('fileName') or derived_source_from_name
    if provided_name:
        name = provided_name
    elif source_filename:
        # Create a compact, predictable bot name that includes the source filename,
        # a UTC timestamp and the model name so it's easy to identify when the bot
        # was created. Example: Travel_Expense_Policy.docx_May292025_130501__gpt-5-mini
        from datetime import datetime
        # Use UTC timestamp with abbreviated month for readability and include seconds
        ts = datetime.utcnow().strftime('%b%d%Y_%H%M%S')
        # If the client already sent a filename that includes a millisecond
        # epoch and model suffix (e.g. Travel_Expense_Policy.docx_1758517096518_gpt-5-mini)
        # extract the original basename and the model if present so we do not
        # double-append timestamps.
        raw_src = source_filename
        model_for_name = body.get('model')
        try:
            candidate = Path(raw_src).name
        except Exception:
            candidate = str(raw_src)

        # Split on underscores and look for a numeric epoch-like segment (10-13 digits)
        parts = candidate.split('_')
        src_base_parts = parts
        for idx, p in enumerate(parts):
            if p.isdigit() and 10 <= len(p) <= 13:
                # Found epoch-like segment; everything before this is the true base name
                src_base_parts = parts[:idx]
                # Attempt to extract model from what follows, if model not provided
                if not model_for_name and idx + 1 < len(parts):
                    possible_model = parts[idx + 1]
                    if 'gpt' in possible_model.lower():
                        model_for_name = possible_model
                break

        # If no epoch segment but last segment looks like a model token (contains 'gpt'),
        # treat it as model and remove from the base filename.
        if not model_for_name and len(parts) > 1 and 'gpt' in parts[-1].lower():
            model_for_name = parts[-1]
            src_base_parts = parts[:-1]

        src_base = '_'.join(src_base_parts) if src_base_parts else candidate
        src_base = src_base.replace(' ', '_')
        model_for_name = model_for_name or 'gpt-5-mini'
        name = f"{src_base}_{ts}__{model_for_name}"
    else:
        name = f"bot_{uuid.uuid4().hex[:6]}"
    text = body.get('text')
    # Support uploading files (pdf/docx/txt). Accept either raw text in 'text' or
    # a base64-encoded file in 'file_base64' with 'source_filename' indicating the name/extension,
    # or a local file path in 'file_path'. If Python libraries to parse PDF/DOCX are available,
    # prefer local parsing; otherwise, if OPENAI_API_KEY is present and file is reasonably small,
    # fall back to asking OpenAI to convert the file to text.
    if not text:
        file_b64 = body.get('file_base64')
        file_path = body.get('file_path')
        src_name = body.get('source_filename') or None
        raw_bytes = None
        if file_b64:
            try:
                import base64
                raw_bytes = base64.b64decode(file_b64)
                if not src_name and body.get('file_name'):
                    src_name = body.get('file_name')
            except Exception:
                raw_bytes = None
        elif file_path:
            try:
                p = Path(file_path)
                if p.exists():
                    raw_bytes = p.read_bytes()
                    if not src_name:
                        src_name = p.name
            except Exception:
                raw_bytes = None
        # If a source filename is provided and raw_bytes still empty, try to read from data/uploads
        if raw_bytes is None and src_name:
            try:
                upl = Path('data') / 'uploads' / src_name
                if upl.exists():
                    raw_bytes = upl.read_bytes()
            except Exception:
                raw_bytes = None

        if raw_bytes is not None and not text:
            # determine extension
            ext = None
            if src_name and '.' in src_name:
                ext = src_name.split('.')[-1].lower()

            parsed_text = None
            # try local python parsing for pdf/docx/txt
            try:
                import io
                if ext == 'pdf':
                    try:
                        from PyPDF2 import PdfReader
                        reader = PdfReader(io.BytesIO(raw_bytes))
                        pages = []
                        for pg in reader.pages:
                            try:
                                pages.append(pg.extract_text() or '')
                            except Exception:
                                pages.append('')
                        parsed_text = '\n\n'.join(pages).strip()
                    except Exception:
                        parsed_text = None
                elif ext in ('docx', 'doc'):
                    try:
                        import docx
                        # python-docx expects a filename; write to temp file
                        import tempfile
                        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.' + ext)
                        tf.write(raw_bytes)
                        tf.close()
                        doc = docx.Document(tf.name)
                        paras = [p.text for p in doc.paragraphs]
                        parsed_text = '\n\n'.join(paras).strip()
                    except Exception:
                        parsed_text = None
                else:
                    # default: try treat as utf-8 text
                    try:
                        parsed_text = raw_bytes.decode('utf-8')
                    except Exception:
                        parsed_text = None
            except Exception:
                parsed_text = None

            # Fallback: if parsing failed and OpenAI key present and file small, ask OpenAI to extract
            if (not parsed_text or parsed_text.strip() == ''):
                # use openai_key from function scope
                if openai_key and len(raw_bytes) < 500000:  # limit to ~500KB for safety
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=openai_key)
                        import base64
                        b64 = base64.b64encode(raw_bytes).decode('ascii')
                        # Build a prompt asking the model to decode base64 and extract text.
                        # This is only appropriate for small files; it's a fallback when no parser is available.
                        msg = (
                            f"The following is a base64-encoded {ext or 'file'}.\n"
                            "Decode the base64 and extract all human-readable text from the file.\n"
                            "Return ONLY the extracted plain text.\n\n"
                            f"BASE64:\n{b64}"
                        )
                        # Use a conservative model and the messages parameter for compatibility
                        try:
                            from ..services.model_caps import send_model_request
                            resp = send_model_request(client, 'gpt-4o-mini', [{'role':'user','content':msg}], temperature=0)
                        except Exception:
                            # try a more widely-available model
                            from ..services.model_caps import send_model_request
                            resp = send_model_request(client, 'gpt-3.5-turbo', [{'role':'user','content':msg}], temperature=0)
                        try:
                            parsed_text = resp.choices[0].message.content
                        except Exception:
                            parsed_text = None
                    except Exception:
                        parsed_text = None

            if parsed_text and parsed_text.strip():
                text = parsed_text
            else:
                # If we still don't have text, error out with a helpful message
                raise HTTPException(status_code=400, detail='Unable to extract text from provided file. Provide plain text or install PyPDF2/python-docx on the server.')
    # read OpenAI key early to avoid UnboundLocalError when referenced in nested blocks
    import os as _os
    openai_key = _os.environ.get('OPENAI_API_KEY')

    model = body.get('model') or 'gpt-5-mini'
    embed_model = body.get('embed_model') or 'text-embedding-3-small'
    k = int(body.get('k') or 4)
    if not text:
        raise HTTPException(status_code=400, detail='text required')
    bot_id = uuid.uuid4().hex
    base = Path('data') / 'bots' / bot_id
    base.mkdir(parents=True, exist_ok=True)
    # simple chunking by paragraphs ~1000 chars
    chunks = []
    cur = ''
    for para in text.split('\n\n'):
        if not para.strip():
            continue
        if len(cur) + len(para) > 1000 and cur:
            chunks.append(cur.strip())
            cur = para
        else:
            cur = (cur + '\n\n' + para).strip()
    if cur: chunks.append(cur)
    # store bot metadata and chunks
    (base / 'bot.json').write_text(json.dumps({'id': bot_id, 'name': name, 'model': model, 'embed_model': embed_model, 'k': k}, indent=2))
    (base / 'chunks.json').write_text(json.dumps(chunks, indent=2))
    # Precompute embeddings for chunks if OpenAI key and embed_model available.
    if openai_key and embed_model:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            # chunk embeddings in batches to avoid very large requests
            batch = []
            embs = []
            BATCH = 64
            for i, c in enumerate(chunks):
                batch.append(c)
                if len(batch) >= BATCH:
                    resp = client.embeddings.create(model=embed_model, input=batch)
                    for d in resp.data:
                        embs.append(d.embedding)
                    batch = []
            if batch:
                resp = client.embeddings.create(model=embed_model, input=batch)
                for d in resp.data:
                    embs.append(d.embedding)
            # Persist embeddings alongside chunks. Prefer numpy for efficiency.
            try:
                import numpy as _np
                _arr = _np.array(embs, dtype=_np.float32)
                (_p := (base / 'embeddings.npy')).parent.mkdir(parents=True, exist_ok=True)
                _np.save(str(_p), _arr)
            except Exception:
                # Fallback to JSON if numpy not available
                (base / 'embeddings.json').write_text(json.dumps(embs))
        except Exception:
            log.exception('failed to precompute embeddings for bot %s', bot_id)
    log.info('Created bot %s (name=%s) with %d chunks', bot_id, name, len(chunks))
    # If OpenAI key present, optionally run a short summarization step so create is not trivially fast
    summary = None
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            model_name = model
            # Build a short context (first few chunks) to summarize
            ctx = '\n\n'.join(chunks[:4])
            sys = "You are a summarization assistant. Produce a short (<=50 words) summary of the policy excerpts. Return plain text only."
            user = f"Policy excerpts:\n{ctx}\n\nProvide a concise summary." 
            def _safe_chat_create_local(cli, **kwargs):
                try:
                    from ..services.model_caps import send_model_request
                    model = kwargs.get('model')
                    messages_or_input = kwargs.get('messages') or kwargs.get('input')
                    # remove keys that would be passed twice (positional + kwargs)
                    call_kwargs = {k: v for k, v in kwargs.items() if k not in ('model', 'messages', 'input')}
                    return send_model_request(cli, model, messages_or_input, **call_kwargs)
                except Exception as e:
                    # fallback to direct call if helper fails
                    msg = str(e)
                    for k in ['temperature', 'max_completion_tokens', 'max_tokens']:
                        kwargs.pop(k, None)
                    if hasattr(cli, 'chat') and hasattr(cli.chat, 'completions'):
                        return cli.chat.completions.create(**kwargs)
                    raise

            try:
                kwargs_local = dict(model=model_name, messages=[{'role':'system','content':sys},{'role':'user','content':user}])
                if _model_allows_temperature(model_name):
                    kwargs_local['temperature'] = 0.2
                    kwargs_local['max_completion_tokens'] = 200
                else:
                    log.info('Create: model %s does not accept temperature/max_tokens; calling without them', model_name)
                resp = _safe_chat_create_local(client, **kwargs_local)
            except Exception:
                resp = None
            try:
                summary = resp.choices[0].message.content or None
            except Exception:
                summary = str(resp) if resp is not None else None
            # persist summary into bot metadata
            try:
                meta = json.loads((base / 'bot.json').read_text())
                meta['summary'] = summary
                (base / 'bot.json').write_text(json.dumps(meta, indent=2))
            except Exception:
                log.exception('failed to persist summary into bot.json')
        except Exception:
            log.exception('OpenAI summarization during create failed; continuing')

    # Include the model/embed_model used to create the bot in the response for debugging/UI
    return {'id': bot_id, 'name': name, 'chunks': len(chunks), 'summary_present': bool(summary), 'used_model': model, 'used_embed_model': embed_model}


@router.post('/bots')
async def create_bot(request: Request) -> Any:
    # Accept both JSON and form-data (multipart). Build a normalized body dict
    # and delegate to the core creation logic above.
    content_type = request.headers.get('content-type', '')
    body: dict = {}
    if 'application/json' in content_type or content_type == '':
        try:
            body = await request.json()
        except Exception:
            # fallback to form parsing if JSON parsing fails
            form = await request.form()
            body = {k: v for k, v in form.items()}
    else:
        form = await request.form()
        body = {k: v for k, v in form.items()}
        # If a file was uploaded as 'file' or 'upload', capture filename and base64
        for key in ('file', 'upload'):
            if key in form:
                f = form[key]
                try:
                    # UploadFile: has filename and .read()
                    fname = getattr(f, 'filename', None)
                    if fname:
                        body.setdefault('source_filename', fname)
                        raw = await f.read()
                        import base64
                        body['file_base64'] = base64.b64encode(raw).decode('ascii')
                except Exception:
                    pass

    return await _create_bot_from_body(body)


@router.get('/bots')
async def list_bots():
    base = Path('data') / 'bots'
    out = []
    if not base.exists(): return out
    for p in base.iterdir():
        meta = p / 'bot.json'
        if meta.exists():
            try:
                out.append(json.loads(meta.read_text()))
            except Exception:
                continue
    return out


@router.get('/models')
async def list_models() -> Any:
    """Return a list of available models from the OpenAI API to populate UI dropdowns.

    Returns a JSON array of objects: {"id": <model-id>, "name": <model-id>}.
    If OPENAI_API_KEY is not configured the endpoint returns an empty list.
    """
    import os, time
    openai_key = os.environ.get('OPENAI_API_KEY')
    # preferred fallback models to show even when API key absent
    preferred = ['gpt-5-mini', 'gpt-4o-mini', 'gpt-3.5-turbo']
    # simple in-memory cache to avoid frequent calls
    if not hasattr(list_models, '_cache'):
        list_models._cache = {'ts': 0, 'data': None}
    TTL = int(os.environ.get('MODELS_CACHE_TTL_SECONDS', '300'))
    now = time.time()
    if list_models._cache['data'] and now - list_models._cache['ts'] < TTL:
        return list_models._cache['data']

    if not openai_key:
        log.info('list_models: OPENAI_API_KEY not set; returning preferred list')
        out = [{'id': p, 'name': p} for p in preferred]
        list_models._cache = {'ts': now, 'data': out}
        return out
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        # The newer OpenAI client exposes models.list()
        resp = client.models.list()
        models = []
        try:
            data = getattr(resp, 'data', None) or resp.get('data') if isinstance(resp, dict) else None
        except Exception:
            data = None
        if data is None:
            # Try to interpret resp as an iterable
            try:
                for m in resp:
                    if isinstance(m, dict) and 'id' in m:
                        models.append({'id': m['id'], 'name': m.get('id')})
            except Exception:
                pass
        else:
            for m in data:
                try:
                    mid = m.id if hasattr(m, 'id') else m.get('id') if isinstance(m, dict) else None
                except Exception:
                    mid = None
                if not mid:
                    try:
                        mid = m['id']
                    except Exception:
                        mid = None
                if mid:
                    models.append({'id': mid, 'name': mid})
        # Add a couple of fallback commonly-used models at the top if missing
        out = []
        seen = set()
        for p in preferred:
            if p not in seen:
                out.append({'id': p, 'name': p}); seen.add(p)
        for m in models:
            if m['id'] not in seen:
                out.append(m); seen.add(m['id'])
        list_models._cache = {'ts': now, 'data': out}
        return out
    except Exception:
        log.exception('Failed to list models from OpenAI')
        return [{'id': p, 'name': p} for p in preferred]


@router.post('/models/probe')
async def probe_models_endpoint() -> Any:
    """Trigger a background probe of model capabilities and persist the results.

    This returns immediately with a message that the probe has started.
    """
    try:
        from ..services.model_probe import schedule_probe_background
        schedule_probe_background()
        return {'status': 'started'}
    except Exception:
        log.exception('failed to schedule model probe')
        raise HTTPException(status_code=500, detail='failed_to_schedule_probe')


@router.delete('/bots/{bot_id}')
async def delete_bot(bot_id: str) -> Any:
    base = Path('data') / 'bots' / bot_id
    if not base.exists():
        raise HTTPException(status_code=404, detail='bot not found')
    try:
        # Remove directory and contents
        for p in base.iterdir():
            try:
                p.unlink()
            except Exception:
                # fallback: if directory, remove recursively
                import shutil
                try:
                    if p.is_dir(): shutil.rmtree(p)
                except Exception:
                    pass
        try:
            base.rmdir()
        except Exception:
            import shutil
            shutil.rmtree(base, ignore_errors=True)
        return { 'ok': True }
    except Exception:
        log.exception('failed to delete bot %s', bot_id)
        raise HTTPException(status_code=500, detail='delete_failed')


def _score_query_to_chunk(q: str, chunk: str) -> int:
    # naive relevance: count intersection words
    qw = set([w.lower() for w in q.split() if len(w)>2])
    cw = set([w.lower() for w in chunk.split() if len(w)>2])
    return len(qw & cw)


@router.post('/bots/{bot_id}/chat')
async def chat_bot(bot_id: str, body: dict) -> Any:
    user_msg = body.get('message','')
    if not user_msg:
        raise HTTPException(status_code=400, detail='message required')
    import os as _os
    openai_key = _os.environ.get('OPENAI_API_KEY')
    base = Path('data') / 'bots' / bot_id
    if not base.exists():
        raise HTTPException(status_code=404, detail='bot not found')
    chunks = json.loads((base / 'chunks.json').read_text())
    # Prefer embedding-based retrieval when an OpenAI key and embed model are available.
    topk = []
    # selected_indices holds the indices of chunks chosen for context so we can
    # report precise references back to the caller/UI.
    selected_indices = []
    embed_model = None
    try:
        bot_meta = json.loads((base / 'bot.json').read_text())
        embed_model = bot_meta.get('embed_model')
    except Exception:
        embed_model = None

    if openai_key and embed_model:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            # Try to load precomputed embeddings from bot storage (prefer numpy file)
            emb_path = base / 'embeddings.npy'
            chunk_embs = None
            if emb_path.exists():
                try:
                    import numpy as _np
                    chunk_embs = _np.load(str(emb_path)).tolist()
                except Exception:
                    # try json fallback
                    try:
                        chunk_embs = json.loads((base / 'embeddings.json').read_text())
                    except Exception:
                        chunk_embs = None
            # If no persisted embeddings, compute and persist them (like in create)
            if chunk_embs is None:
                # compute embeddings for all chunks in batches
                BATCH = 64
                chunk_embs = []
                batch = []
                for c in chunks:
                    batch.append(c)
                    if len(batch) >= BATCH:
                        resp = client.embeddings.create(model=embed_model, input=batch)
                        for d in resp.data:
                            chunk_embs.append(d.embedding)
                        batch = []
                if batch:
                    resp = client.embeddings.create(model=embed_model, input=batch)
                    for d in resp.data:
                        chunk_embs.append(d.embedding)
                # persist
                try:
                    import numpy as _np
                    _np.save(str(base / 'embeddings.npy'), _np.array(chunk_embs, dtype=_np.float32))
                except Exception:
                    try:
                        (base / 'embeddings.json').write_text(json.dumps(chunk_embs))
                    except Exception:
                        pass

            # compute query embedding
            qresp = client.embeddings.create(model=embed_model, input=[user_msg])
            qemb = qresp.data[0].embedding
            # compute cosine similarity
            def dot(a,b):
                return sum(x*y for x,y in zip(a,b))
            def norm(a):
                return sum(x*x for x in a) ** 0.5
            qn = norm(qemb) or 1.0
            sims = []
            for idx, ce in enumerate(chunk_embs):
                try:
                    s = dot(qemb, ce) / (qn * (norm(ce) or 1.0))
                except Exception:
                    s = 0.0
                sims.append((idx, float(s)))
            sims.sort(key=lambda x: x[1], reverse=True)
            selected = [i for i,sc in sims[:4] if sc > 0.01]
            selected_indices = selected
            topk = [chunks[i] for i in selected]
        except Exception:
            topk = []

    if not topk:
        # naive score fallback (word-overlap)
        scored = [(i, _score_query_to_chunk(user_msg, c)) for i,c in enumerate(chunks)]
        scored.sort(key=lambda x: x[1], reverse=True)
        selected_indices = [i for i,s in scored[:4] if s>0]
        topk = [chunks[i] for i in selected_indices]

    # build reply: if no relevant chunks, refuse
    if not topk:
        return {'answer': "I cannot find a direct policy rule for that question.", 'sources': []}
    # For MVP, build a simple answer by concatenating top chunks and asking OpenAI if available
    # If OPENAI_API_KEY present, call OpenAI; otherwise return concatenated chunks
    if not openai_key:
        log.info('OPENAI_API_KEY not set; skipping OpenAI call and returning concatenated chunks')
    if openai_key:
        try:
            log.info('OPENAI_API_KEY present; will call OpenAI for bot %s', bot_id)
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            bot_meta = json.loads((base / 'bot.json').read_text())
            # allow callers to override model/embed_model for a single chat call
            override_model = body.get('model')
            override_embed = body.get('embed_model')
            model = override_model or bot_meta.get('model','gpt-5-mini')
            embed_model = override_embed or bot_meta.get('embed_model','text-embedding-3-small')
            log.info('bots.chat: bot_id=%s will use model=%s embed_model=%s (override_model=%s override_embed=%s)', bot_id, model, embed_model, bool(override_model), bool(override_embed))
            # System prompt and OUTPUT CONTRACT per product requirements
            system = (
                "You are a corporate Travel & Expense (T&E) policy assistant.\n\n"
                "OUTPUT CONTRACT:\n"
                "Return ONE JSON object only. No prose, no code fences, no markdown.\n\n"
                "SCHEMA:\n"
                "{\n"
                "  \"answer\": \"yes\" | \"no\" | \"depends\" | \"insufficient_context\",\n"
                "  \"reasoning\": [string, ...],          // 1–4 short bullets, plain text\n"
                "  \"references\": [string, ...],         // short policy rule labels with thresholds\n"
                "  \"needs\": [string, ...]               // list missing facts if answer != yes/no; else []\n"
                "}\n\n"
                "RULES:\n"
                "- Keep bullets concise; no full sentences needed.\n"
                "- Use USD unless currency is specified.\n"
                "- If a limit is exceeded but an approval path exists, answer \"no\" (unless user states approval was granted).\n"
                "- If the user’s question is not about T&E, set \"answer\":\"insufficient_context\" and put what you need in \"needs\".\n"
                "- When listing references, include the chunk identifier (e.g. \"chunk#12\") as provided in the Context and a short policy label so callers can trace the source.\n"
                "- Do not include any text outside the JSON object.\n\n"
                "FEW-SHOT EXAMPLES:\n\n"
                "Q: Can I spend 100 bucks for lunch locally?\n"
                "A:\n"
                "{\n"
                "  \"answer\": \"no\",\n"
                "  \"reasoning\": [\"domestic meals allowance is 75/day\",\"100 exceeds limit; requires VP pre-approval\"],\n"
                "  \"references\": [\"Meals (domestic): $75/day max\",\"Exceptions: VP-level pre-approval required\"],\n"
                "  \"needs\": []\n"
                "}\n\n"
                "Q: Can I spend $100 for lunch on an international trip?\n"
                "A:\n"
                "{\n"
                "  \"answer\": \"depends\",\n"
                "  \"reasoning\": [\"international meals allowance is 100/day\",\"100 is at limit; receipt and business purpose required\"],\n"
                "  \"references\": [\"Meals (international): $100/day max\",\"Receipts: original itemized within 30 days\"],\n"
                "  \"needs\": []\n"
                "}\n\n"
                "Q: Can I get reimbursed for dinner?\n"
                "A:\n"
                "{\n"
                "  \"answer\": \"insufficient_context\",\n"
                "  \"reasoning\": [\"meal limit depends on domestic vs international\",\"need amount and proof of receipt\"],\n"
                "  \"references\": [\"Meals (domestic): $75/day max\",\"Meals (international): $100/day max\"],\n"
                "  \"needs\": [\"travel_type (domestic|international)\", \"amount_usd\", \"receipt_yes_no\"]\n"
                "}\n\n"
                "SYSTEM MESSAGE SETTINGS (integrator): temperature 0–0.3, max_tokens >=256.\n"
            )

            # Define a function schema so model is constrained to emit parameters matching our OUTPUT CONTRACT.
            # The OpenAI API expects 'tools' entries to use type 'function' or 'custom'.
            # Older code incorrectly used 'tool' which causes a 400 BadRequestError.
            functions = [
                {
                    "name": "answer_contract",
                    "type": "function",
                    "description": "Return a single JSON object that matches the OUTPUT CONTRACT schema.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string", "enum": ["yes", "no", "depends", "insufficient_context"]},
                            "reasoning": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 4},
                            "references": {"type": "array", "items": {"type": "string"}},
                            "needs": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["answer", "reasoning", "references", "needs"],
                        "additionalProperties": False,
                    },
                }
            ]
            # Label excerpts with their chunk indices so the model can reference them.
            context_parts = []
            for idx, excerpt in zip(selected_indices, topk):
                context_parts.append(f"chunk#{idx}:\n{excerpt}")
            context = '\n---\n'.join(context_parts)
            prompt = f"Context:\n{context}\n\nUser question:\n{user_msg}\n\nProvide a concise answer strictly following the policy."
            # Request deterministic output and prefer the function-calling path to constrain the shape
            # Use a safe caller that will retry without unsupported params (temperature/max_tokens) when needed
            def _safe_chat_create(cli, **kwargs):
                # Allowed keys per new contract. Include both 'input' (newer SDK) and 'messages'
                # (older SDK) and map aliases for compatibility (max_output_tokens -> max_tokens).
                allowed = {
                    'model', 'input', 'messages', 'temperature', 'top_p', 'max_output_tokens', 'max_tokens',
                    'stop', 'response_format', 'tools', 'tool_choice', 'metadata'
                }
                # filter kwargs to allowed set to avoid unsupported params
                safe_kwargs = {k: v for k, v in kwargs.items() if k in allowed}
                # Backwards-compat: if caller provided 'input' (newer SDK) but the installed
                # SDK expects 'messages', map input -> messages (list of {role,content}).
                if 'input' in safe_kwargs and 'messages' not in safe_kwargs:
                    safe_kwargs['messages'] = safe_kwargs.pop('input')
                # Alias for token limits: some SDKs expect max_tokens
                if 'max_output_tokens' in safe_kwargs and 'max_tokens' not in safe_kwargs:
                    safe_kwargs['max_tokens'] = safe_kwargs.get('max_output_tokens')
                try:
                    from ..services.model_caps import send_model_request
                    model = safe_kwargs.get('model')
                    messages_or_input = safe_kwargs.get('messages') or safe_kwargs.get('input')
                    call_kwargs = {k: v for k, v in safe_kwargs.items() if k not in ('model', 'messages', 'input')}
                    return send_model_request(cli, model, messages_or_input, **call_kwargs)
                except Exception as e:
                    msg = str(e)
                    # fallback: remove problematic tuning keys but keep the messages/input
                    # so the lower-level SDK receives the required parameters.
                    for k in ['temperature', 'max_output_tokens', 'max_tokens', 'top_p']:
                        safe_kwargs.pop(k, None)
                    if hasattr(cli, 'chat') and hasattr(cli.chat, 'completions'):
                        return cli.chat.completions.create(**safe_kwargs)
                    raise
            log.info('Sending chat completion to OpenAI model=%s for bot=%s (retrieval prompt)', model, bot_id)
            # Build simple messages-based prompt: system contains OUTPUT CONTRACT and examples.
            messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
            # Prefer calling the Chat completions API directly when available
            # for more predictable behavior with messages-based prompts.
            resp = None
            if hasattr(client, 'chat') and hasattr(client.chat, 'completions'):
                try:
                    call_kwargs = {}
                    if _model_allows_temperature(model):
                        call_kwargs['temperature'] = 0.2
                        call_kwargs['max_tokens'] = 1024
                    resp = client.chat.completions.create(model=model, messages=messages, **call_kwargs)
                except Exception:
                    log.exception('Direct chat.completions.create failed; falling back to send_model_request')

            if resp is None:
                try:
                    from ..services.model_caps import send_model_request
                    kwargs_req = {}
                    if _model_allows_temperature(model):
                        kwargs_req['temperature'] = 0.2
                        kwargs_req['max_tokens'] = 1024
                    resp = send_model_request(client, model, messages, **kwargs_req)
                except Exception:
                    log.exception('send_model_request fallback failed')
                    raise

            # Extract the main textual content from the response
            try:
                content = resp.choices[0].message.content or ''
            except Exception:
                content = ''
            # If model returned a function call, arguments are the canonical JSON output
            try:
                choice_msg = resp.choices[0].message
                # support both dict-style and attribute-style SDK responses
                if isinstance(choice_msg, dict):
                    fc = choice_msg.get('function_call')
                else:
                    fc = getattr(choice_msg, 'function_call', None)
                if fc and isinstance(fc, dict):
                    args = fc.get('arguments')
                    if args:
                        content = args
            except Exception:
                pass
            # Try to parse JSON from the model output
            parsed_json = None
            # content may already be a dict (function call args) or a JSON string
            if isinstance(content, (dict, list)):
                parsed_json = content
            else:
                try:
                    parsed_json = json.loads(content)
                except Exception:
                    try:
                        from ..services.policy_parser import _extract_json_object_from_text
                        candidate = _extract_json_object_from_text(content)
                        if candidate:
                            parsed_json = json.loads(candidate)
                    except Exception:
                        parsed_json = None

            structured = None
            def _normalize_and_validate(pj):
                # Ensure we return a dict with required keys and sensible defaults.
                out = {
                    'answer': None,
                    'reasoning': [],
                    'references': [],
                    'needs': [],
                }
                try:
                    if isinstance(pj, dict):
                        out['answer'] = pj.get('answer')
                        out['reasoning'] = pj.get('reasoning') or pj.get('reason', []) or []
                        out['references'] = pj.get('references') or pj.get('refs') or []
                        out['needs'] = pj.get('needs') or []
                    elif isinstance(pj, list):
                        out['answer'] = ''
                    else:
                        out['answer'] = str(pj)
                except Exception:
                    out['answer'] = str(pj)
                # normalize types
                if not isinstance(out['reasoning'], list):
                    out['reasoning'] = [str(out['reasoning'])]
                if not isinstance(out['references'], list):
                    out['references'] = [str(out['references'])]
                if not isinstance(out['needs'], list):
                    out['needs'] = [str(out['needs'])]
                return out

            if isinstance(parsed_json, dict) and ('answer' in parsed_json or 'reasoning' in parsed_json or 'references' in parsed_json):
                parsed_json['references'] = parsed_json.get('references') or parsed_json.get('refs') or []
                structured = _normalize_and_validate(parsed_json)
                # If required keys missing, log for debugging
                if structured.get('answer') is None:
                    log.warning('Parsed JSON from model missing "answer" key: %s', parsed_json)
            else:
                structured = { 'answer': content.strip(), 'reasoning': [], 'references': [f"chunk#{i}" for i in selected_indices], 'needs': [] }

            # If answer is empty, attempt a retry requesting strict JSON output
            if not structured.get('answer') or not str(structured.get('answer')).strip():
                try:
                    retry_system = (
                        "You are a corporate T&E policy assistant.\n"
                        "Produce a JSON object ONLY with keys: answer (string), reasoning (array of strings), references (array of strings).\n"
                        "Use only the provided policy excerpts. Keep answer under 120 words. Start with Yes/No if possible."
                    )
                    retry_prompt = "Produce the JSON for the user question and provided excerpts.\nUser question:\n" + user_msg + "\n\nExcerpts:\n\n" + "\n---\n".join(context_parts)
                    input_val2 = [{'role': 'system', 'content': retry_system}, {'role': 'user', 'content': retry_prompt}]
                    kwargs2 = {
                        'model': model,
                        'input': input_val2,
                        # Wrap the schema under json_schema.schema like above for compatibility
                        'response_format': {"type": "json_schema", "json_schema": {"name": "answer_contract", "schema": response_schema}},
                        'tools': functions,
                        'tool_choice': {"type": "function", "function": {"name": "answer_contract"}},
                        'metadata': {"bot_id": bot_id, "retry": True},
                    }
                    if _model_allows_temperature(model):
                        kwargs2['temperature'] = 0.2
                        kwargs2['max_output_tokens'] = 512
                    else:
                        log.info('Retry: Model %s does not accept temperature/max_output_tokens; retrying without them', model)
                    resp2 = _safe_chat_create(client, **kwargs2)
                    c2 = resp2.choices[0].message.content or ''
                    # if function_call used, extract arguments
                    try:
                        choice_msg2 = resp2.choices[0].message
                        if isinstance(choice_msg2, dict):
                            fc2 = choice_msg2.get('function_call')
                        else:
                            fc2 = getattr(choice_msg2, 'function_call', None)
                        if fc2 and isinstance(fc2, dict):
                            args2 = fc2.get('arguments')
                            if args2:
                                c2 = args2
                    except Exception:
                        pass
                    try:
                        j2 = json.loads(c2)
                        if isinstance(j2, dict) and j2.get('answer'):
                            structured = j2
                    except Exception:
                        pass
                except Exception:
                    log.exception('bot retry JSON generation failed')

            # build formatted text/html
            def build_from_struct(sj: dict):
                import html, re
                ans = sj.get('answer','')
                reasoning = sj.get('reasoning') or []
                refs = sj.get('references') or []
                parts = []
                parts.append('**Answer:**')
                parts.append(f"- {ans}")
                parts.append('\n**Reasoning (short):**')
                for r in reasoning:
                    parts.append(f"- {r}")
                if refs:
                    parts.append('\n**Policy Reference (if needed):**')
                    for rf in refs:
                        parts.append(f"- {rf}")
                text = '\n'.join(parts)
                lines = text.splitlines()
                out = []
                in_list=False
                for ln in lines:
                    if ln.startswith('- '):
                        if not in_list:
                            out.append('<ul>'); in_list=True
                        out.append('<li>'+html.escape(ln[2:])+'</li>')
                    else:
                        if in_list:
                            out.append('</ul>'); in_list=False
                        out.append('<div>'+re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html.escape(ln))+'</div>')
                if in_list: out.append('</ul>')
                return text, '\n'.join(out)

            formatted, formatted_html = build_from_struct(structured)
            return {
                'answer': structured.get('answer'),
                'formatted_text': formatted,
                'formatted_html': formatted_html,
                'structured': structured,
                'sources': [{'chunk_index': i} for i in selected_indices],
                'used_model': model,
                'used_embed_model': embed_model,
            }
        except Exception:
            log.exception('OpenAI chat failed, falling back')
            # build simple formatted output from the concatenated chunks
            fallback_text = '\n\n'.join(topk)
            fallback_struct = {'answer': fallback_text, 'reasoning': [], 'references': [], 'needs': []}
            formatted, formatted_html = (fallback_text, '<div>' + fallback_text.replace('\n','<br/>') + '</div>')
            return {'answer': fallback_text, 'formatted_text': formatted, 'formatted_html': formatted_html, 'structured': fallback_struct, 'sources':[{'chunk_index': i} for i in selected_indices], 'used_model': (override_model or json.loads((base / 'bot.json').read_text()).get('model','gpt-5-mini'))}
    else:
        fallback_text = '\n\n'.join(topk)
        fallback_struct = {'answer': fallback_text, 'reasoning': [], 'references': [], 'needs': []}
        formatted_html = '<div>' + fallback_text.replace('\n','<br/>') + '</div>'
        return {'answer': fallback_text, 'formatted_text': fallback_text, 'formatted_html': formatted_html, 'structured': fallback_struct, 'sources':[{'chunk_index': i} for i in selected_indices], 'used_model': json.loads((base / 'bot.json').read_text()).get('model','gpt-5-mini')}
