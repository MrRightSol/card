from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import logging

log = logging.getLogger(__name__)

from ..services.policy_rag import build_index, generate_answer

router = APIRouter()


@router.get('/openai-models')
async def list_openai_models():
    try:
        import os
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            return {'error': 'OPENAI_API_KEY not configured'}
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        models = client.models.list()
        # models.data may be iterable of model objects
        out = []
        try:
            for m in models.data:
                out.append(getattr(m, 'id', str(m)))
        except Exception:
            # fallback: models might be a list
            try:
                for m in models:
                    out.append(getattr(m, 'id', str(m)))
            except Exception:
                out = []
        return {'models': out}
    except Exception:
        log.exception('failed to list openai models')
        raise HTTPException(status_code=500, detail='failed to list openai models')


class IndexRequest(BaseModel):
    embed_model: str | None = None


@router.post('/index-policies')
async def index_policies(req: IndexRequest) -> Any:
    try:
        res = build_index(embed_model=req.embed_model or 'text-embedding-3-small')
        return res
    except Exception as e:
        log.exception('index build failed')
        raise HTTPException(status_code=500, detail=str(e))


class ChatRequest(BaseModel):
    query: str
    top_k: int | None = 4
    model: str | None = None
    embed_model: str | None = None


@router.post('/chat-policy')
async def chat_policy(req: ChatRequest) -> Any:
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail='query required')
    try:
        out = generate_answer(req.query, top_k=(req.top_k or 4), model=(req.model or 'gpt-5-mini'), embed_model=(req.embed_model or 'text-embedding-3-small'))
        # Post-process formatting: produce a compact single-line style answer
        raw_answer = out.get('answer', '') or ''
        # Build bullets from the raw answer: prefer currency mentions and policy keywords,
        # otherwise fall back to sentence splitting. This produces concise inline bullets.
        import re
        lines = [l.strip() for l in raw_answer.splitlines() if l.strip()]
        sentences: list[str] = []
        if lines:
            for ln in lines:
                if ln.startswith(('-', '*', '•')):
                    sentences.append(ln.lstrip('-*• ').strip())
                else:
                    parts = [p.strip() for p in re.split(r'(?<=[\.!?])\s+', ln) if p.strip()]
                    sentences.extend(parts)
        else:
            sentences = [s.strip() for s in re.split(r'(?<=[\.!?])\s+', raw_answer) if s.strip()]

        # prioritize sentences containing currency or key policy terms
        currency_re = re.compile(r"(?:(?:USD|US\$|\$)\s?\d{1,3}(?:[\,\.]\d{3})*(?:\.\d+)?|\d+\s?(?:USD|USD\b))", flags=re.IGNORECASE)
        policy_keywords = re.compile(r"\b(reimbursable|not reimbursable|per night|per day|per person|approve|approval|VP|manager|pre-approval|deny|denied)\b", flags=re.IGNORECASE)

        prioritized: list[str] = []
        others: list[str] = []
        for s in sentences:
            if currency_re.search(s) or policy_keywords.search(s):
                prioritized.append(s)
            else:
                others.append(s)

        bullets = prioritized + others

        # normalize bullets: remove excessive whitespace and strip trailing punctuation
        norm_bullets = []
        seen = set()
        for b in bullets:
            s = ' '.join(b.split())
            if not s:
                continue
            # strip trailing periods for consistent joining, but keep percentages and similar
            s_clean = s.rstrip(' .')
            if s_clean not in seen:
                seen.add(s_clean)
                norm_bullets.append(s_clean)

        if norm_bullets:
            resp_text = 'Per policy: ' + ' - '.join([f"{b}." for b in norm_bullets])
        else:
            # fallback to raw answer
            resp_text = raw_answer.replace('\n', ' ').strip()

        # Build human-readable source labels and attach to output
        sources = out.get('sources') or []
        sources_readable: list[str] = []
        if isinstance(sources, list) and sources:
            for s in sources:
                try:
                    src = s.get('source') or s.get('id') or ''
                    # take basename and append chunk id if present
                    from pathlib import Path
                    base = Path(str(src)).name
                    # try to extract trailing #index from id
                    idx = None
                    sid = s.get('id') or ''
                    if isinstance(sid, str) and '#' in sid:
                        idx = sid.split('#')[-1]
                    if idx:
                        label = f"{base}#{idx}"
                    else:
                        label = base
                except Exception:
                    label = str(s)
                sources_readable.append(label)
            # include readable source list in parentheses
            resp_text = f"{resp_text} (sources: {', '.join(sources_readable)})"
        out['sources_readable'] = sources_readable

        # Colors: inline styles for question and response
        q_color = '#1f6feb'  # blue-ish for user question
        a_color = '#0b6b0b'  # green-ish for bot answer
        question_html = f"<span style=\"color:{q_color};font-weight:600\">You: {req.query}</span>"
        answer_html = f"<span style=\"color:{a_color}\">Bot: {resp_text}</span>"
        formatted_html = question_html + ' ' + answer_html

        out['formatted_html'] = formatted_html
        out['formatted_text'] = f"You: {req.query} \nBot: {resp_text}"
        # expose which models were used for transparency/debugging
        out['used_model'] = model
        out['used_embed_model'] = embed_model
        log.info('chat-policy: used model=%s embed_model=%s top_k=%s', model, embed_model, top_k)
        return out
    except Exception as e:
        # If the index has not been built, give a friendly error with actionable steps
        msg = str(e)
        log.exception('chat_policy failed')
        if 'index not built' in msg.lower() or 'index not built; run build_index first' in msg.lower():
            raise HTTPException(status_code=400, detail="index_not_built: run POST /index-policies to build the policy vector index before querying")
        raise HTTPException(status_code=500, detail=msg)
