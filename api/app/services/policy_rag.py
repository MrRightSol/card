from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
import logging

log = logging.getLogger(__name__)

import numpy as np
from sklearn.neighbors import NearestNeighbors


VECTOR_DIR = Path("data") / "vector_store"
VECTOR_DIR.mkdir(parents=True, exist_ok=True)
EMB_FILE = VECTOR_DIR / "embeddings.npy"
META_FILE = VECTOR_DIR / "metadata.json"


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 100) -> List[str]:
    if not text:
        return []
    text = text.replace("\r\n", "\n")
    chunks: List[str] = []
    start = 0
    L = len(text)
    while start < L:
        end = min(start + chunk_size, L)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == L:
            break
        start = max(0, end - overlap)
    return chunks


def _gather_source_texts() -> List[Tuple[str, str]]:
    """Collect policy-like source texts from known data directories.

    Returns a list of (source_path, text) tuples.
    """
    out: List[Tuple[str, str]] = []
    base = Path("data")
    # OpenAI saved responses
    resp_dir = base / "openai_responses"
    if resp_dir.exists():
        for p in sorted(resp_dir.glob("*.json")):
            try:
                txt = p.read_text(encoding="utf-8")
                # If it's JSON array/object we try to create a textual representation
                try:
                    j = json.loads(txt)
                    if isinstance(j, list):
                        # join rule name+description
                        parts = []
                        for item in j:
                            if isinstance(item, dict):
                                parts.append(item.get("name", ""))
                                parts.append(item.get("description", ""))
                                # include condition if present
                                parts.append(item.get("condition", ""))
                        txt = "\n\n".join([p for p in parts if p])
                    elif isinstance(j, dict) and "rules" in j and isinstance(j["rules"], list):
                        parts = []
                        for item in j["rules"]:
                            parts.append(item.get("name", ""))
                            parts.append(item.get("description", ""))
                        txt = "\n\n".join([p for p in parts if p])
                except Exception:
                    pass
                out.append((str(p), txt))
            except Exception:
                log.exception("Failed to read %s", str(p))
    # uploaded raw files
    uploads = base / "uploads"
    if uploads.exists():
        for p in sorted(uploads.iterdir()):
            try:
                txt = p.read_text(encoding="utf-8")
                out.append((str(p), txt))
            except Exception:
                log.exception("Failed to read upload %s", str(p))
    # bots chunks
    bots = base / "bots"
    if bots.exists():
        for bot in bots.iterdir():
            chunksf = bot / "chunks.json"
            if chunksf.exists():
                try:
                    arr = json.loads(chunksf.read_text(encoding="utf-8"))
                    out.append((str(chunksf), "\n\n".join([c for c in arr if c])))
                except Exception:
                    log.exception("Failed to read bot chunks %s", str(chunksf))

    return out


def build_index(embed_model: str = "text-embedding-3-small", batch_size: int = 32) -> Dict[str, Any]:
    """Build or rebuild the vector index from known policy sources.

    Persists embeddings and metadata to data/vector_store.
    Returns metadata summary.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required to build embeddings")
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("openai package required for embeddings") from e

    client = OpenAI(api_key=api_key)

    sources = _gather_source_texts()
    all_chunks: List[Dict[str, Any]] = []
    seen_texts = set()
    for src_path, txt in sources:
        chunks = chunk_text(txt)
        for i, c in enumerate(chunks):
            if not c or not c.strip():
                continue
            key = (str(src_path), i, c.strip()[:200])
            # simple dedupe: skip identical first-200-char excerpts
            if key in seen_texts:
                continue
            seen_texts.add(key)
            all_chunks.append({"id": f"{Path(src_path).name}#{i}", "source": src_path, "text": c})

    if not all_chunks:
        return {"ok": True, "indexed": 0}

    embeddings: List[List[float]] = []
    texts_batch: List[str] = []
    meta_batch: List[Dict[str, Any]] = []
    for item in all_chunks:
        texts_batch.append(item["text"])
        meta_batch.append({k: item[k] for k in ("id", "source")})
        if len(texts_batch) >= batch_size:
            resp = client.embeddings.create(model=embed_model, input=texts_batch)
            for emb in resp.data:
                embeddings.append(emb.embedding)
            texts_batch = []
    if texts_batch:
        resp = client.embeddings.create(model=embed_model, input=texts_batch)
        for emb in resp.data:
            embeddings.append(emb.embedding)

    arr = np.array(embeddings, dtype=np.float32)
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    np.save(EMB_FILE, arr)
    # metadata aligns with embeddings index
    metas = [{"id": c["id"], "source": c["source"], "text": c["text"]} for c in all_chunks]
    META_FILE.write_text(json.dumps(metas, indent=2), encoding="utf-8")
    log.info("Built vector index with %d vectors", arr.shape[0])
    return {"ok": True, "indexed": arr.shape[0]}


class Retriever:
    def __init__(self):
        self._loaded = False
        self._embs = None
        self._meta: List[Dict[str, Any]] = []
        self._nn = None

    def load(self):
        if not EMB_FILE.exists() or not META_FILE.exists():
            raise RuntimeError("index not built; run build_index first")
        self._embs = np.load(EMB_FILE)
        self._meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        # normalize vectors for cosine similarity
        # sklearn NearestNeighbors with metric='cosine' returns distances in [0,2]
        self._nn = NearestNeighbors(n_neighbors=min(32, len(self._embs)), metric="cosine")
        self._nn.fit(self._embs)
        self._loaded = True

    def retrieve(self, query: str, top_k: int = 4, embed_model: str = "text-embedding-3-small") -> List[Dict[str, Any]]:
        if not self._loaded:
            self.load()
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY required for retrieval")
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model=embed_model, input=[query])
        qv = np.array(resp.data[0].embedding, dtype=np.float32).reshape(1, -1)
        dists, idxs = self._nn.kneighbors(qv, n_neighbors=min(top_k, len(self._embs)))
        results = []
        seen = set()
        for dist, idx in zip(dists[0], idxs[0]):
            # convert cosine distance to similarity approx
            sim = 1.0 - float(dist)
            meta = self._meta[int(idx)].copy()
            key = (meta.get('source'), meta.get('id'))
            if key in seen:
                continue
            seen.add(key)
            meta.update({"score": sim})
            results.append(meta)
        return results


_RETRIEVER: Retriever | None = None


def get_retriever() -> Retriever:
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = Retriever()
    return _RETRIEVER


def generate_answer(query: str, top_k: int = 4, model: str = "gpt-5-mini", embed_model: str = "text-embedding-3-small") -> Dict[str, Any]:
    """Retrieve relevant chunks and ask the LLM to answer with citations.

    Returns { answer: str, sources: [ {id, source, score} ], raw_retrieval: [...] }
    """
    retr = get_retriever()
    hits = retr.retrieve(query, top_k=top_k, embed_model=embed_model)
    # dedupe hits by (source,id) and remove empty texts
    seen = set()
    deduped: list[Dict[str,Any]] = []
    for h in hits:
        sid = h.get('id') or ''
        src = h.get('source') or ''
        text = (h.get('text') or '').strip()
        if not text:
            continue
        key = (src, sid)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)
    hits = deduped
    # System prompt and few-shot examples for the policy assistant
    system = (
        "You are a corporate travel & expense policy assistant. Answer strictly from the provided “Relevant Policy Excerpts.” "
        "Do not invent rules. If evidence is insufficient or conditional on approvals, return “Needs Review” and state what approval or detail is missing. "
        "Prefer concise answers with precise citations (section titles or numbers). Currency is the one used in the excerpt unless the user specifies otherwise.\n\n"
        "Return JSON only:\n"
        "{\n"
        "  \"verdict\": \"Yes|No|Needs Review\",\n"
        "  \"justification\": \"short, plain-English reason\",\n"
        "  \"citations\": [\n"
        "    { \"section\": \"<e.g., 5. Meals & Entertainment>\", \"text\": \"<exact quoted line(s)>\" }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "  • If the excerpt sets daily limits, do not treat them as per-meal limits.\n"
        "  • If an item requires manager/VP/CFO approval, use verdict=“Needs Review” and name the approver.\n"
        "  • If location (domestic vs international) matters and is unspecified, use verdict=“Needs Review” and ask for it.\n"
        "  • If the request conflicts with a “Not Reimbursable” list, return “No” and cite it.\n"
        "  • When in doubt, be conservative; never guess amounts not present in the excerpts.\n\n"
        "Example 1\n"
        "Question:\n"
        "Can I spend $200 on lunch during a domestic trip?\n\n"
        "Relevant Policy Excerpts:\n"
        "• 5. Meals & Entertainment: \"Daily Meal Allowance: Up to $75 per day domestic travel. Up to $100 per day international travel.\"\n\n"
        "Expected JSON:\n"
        "{\n"
        "  \"verdict\": \"Needs Review\",\n"
        "  \"justification\": \"The policy sets a daily meal cap ($75 domestic), not a per-meal cap. Whether $200 is compliant depends on total meals that day.\",\n"
        "  \"citations\": [\n"
        "    { \"section\": \"5. Meals & Entertainment\", \"text\": \"Daily Meal Allowance: Up to $75 per day domestic travel.\" }\n"
        "  ]\n"
        "}\n\n"
        "Example 2\n"
        "Question:\n"
        "May I book business class on a 7-hour flight?\n\n"
        "Relevant Policy Excerpts:\n"
        "• 3. Air Travel: \"Premium economy or business class may be approved for flights over 6 continuous hours with prior manager approval.\"\n\n"
        "Expected JSON:\n"
        "{\n"
        "  \"verdict\": \"Needs Review\",\n"
        "  \"justification\": \"Business class on >6h flights requires prior manager approval.\",\n"
        "  \"citations\": [\n"
        "    { \"section\": \"3. Air Travel\", \"text\": \"…business class may be approved for flights over 6 continuous hours with prior manager approval.\" }\n"
        "  ]\n"
        "}\n\n"
        "Example 3\n"
        "Question:\n"
        "Is a $230/night hotel in my home country reimbursable?\n\n"
        "Relevant Policy Excerpts:\n"
        "• 4. Lodging: \"Domestic (home country): up to $200 per night.\"\n\n"
        "Expected JSON:\n"
        "{\n"
        "  \"verdict\": \"No\",\n"
        "  \"justification\": \"Domestic hotel limit is $200/night; $230 exceeds the cap.\",\n"
        "  \"citations\": [\n"
        "    { \"section\": \"4. Lodging\", \"text\": \"Domestic (home country): up to $200 per night.\" }\n"
        "  ]\n"
        "}\n\n"
        "Example 4\n"
        "Question:\n"
        "Can I expense $30 of alcohol with dinner on an international trip?\n\n"
        "Relevant Policy Excerpts:\n"
        "• 5. Meals & Entertainment: \"Alcohol is reimbursable only when consumed with a meal and does not exceed $25 per day.\"\n\n"
        "Expected JSON:\n"
        "{\n"
        "  \"verdict\": \"No\",\n"
        "  \"justification\": \"Alcohol reimbursement is capped at $25/day even on international trips.\",\n"
        "  \"citations\": [\n"
        "    { \"section\": \"5. Meals & Entertainment\", \"text\": \"Alcohol is reimbursable only when consumed with a meal and does not exceed $25 per day.\" }\n"
        "  ]\n"
        "}\n\n"
        "Example 5\n"
        "Question:\n"
        "Can I buy a luxury 5-star hotel for a client meeting if my manager approves?\n\n"
        "Relevant Policy Excerpts:\n"
        "• 4. Lodging: \"Luxury hotels (5-star) are not permitted unless hosting clients and pre-approved by management.\"\n\n"
        "Expected JSON:\n"
        "{\n"
        "  \"verdict\": \"Yes\",\n"
        "  \"justification\": \"Allowed when hosting clients and pre-approved by management.\",\n"
        "  \"citations\": [\n"
        "    { \"section\": \"4. Lodging\", \"text\": \"Luxury hotels (5-star) are not permitted unless hosting clients and pre-approved by management.\" }\n"
        "  ]\n"
        "}\n\n"
        "User Prompt Template (each question)\n\n"
        "Question:\n"
        "{user_question}\n\n"
        "Relevant Policy Excerpts:\n"
        "{retrieved_chunks}\n\n"
        "Respond in the required JSON schema only.\n"
    )
    # prepare retrieved context snippets
    context_parts: List[str] = []
    for i, h in enumerate(hits):
        excerpt = (h.get('text') or '').strip()
        if len(excerpt) > 1500:
            excerpt = excerpt[:1500] + '\n...'
        context_parts.append(f"{excerpt}")
    # build the live user prompt using the template section from the system prompt
    user_prompt = (
        f"Question:\n{query}\n\n"
        "Relevant Policy Excerpts:\n\n"
        + "\n---\n".join(context_parts)
        + "\n\nRespond in the required JSON schema only."
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required for generation")

    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    try:
        from .model_caps import send_model_request
        resp = send_model_request(client, model, [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}], max_output_tokens=1024)
        content = resp.choices[0].message.content or ""
    except Exception:
        log.exception("OpenAI chat completion failed")
        content = None

    # Try to parse the model output as strict JSON with fields: answer (str), reasoning (list[str]), references (list[str])
    parsed_json = None
    if content:
        try:
            import json as _json

            parsed_json = _json.loads(content)
        except Exception:
            # attempt to extract JSON object from text (use policy_parser helper if available)
            try:
                from .policy_parser import _extract_json_object_from_text

                candidate = _extract_json_object_from_text(content)
                if candidate:
                    try:
                        parsed_json = __import__('json').loads(candidate)
                    except Exception:
                        parsed_json = None
            except Exception:
                # last-resort: try to find a balanced brace JSON in the text
                import re, json as _json2

                m = re.search(r"\{[\s\S]*\}", str(content))
                if m:
                    try:
                        parsed_json = _json2.loads(m.group(0))
                    except Exception:
                        parsed_json = None

    # If we obtained a parsed JSON with expected keys, use it; otherwise fall back to generating structured output
    structured = None
    if isinstance(parsed_json, dict) and ('answer' in parsed_json or 'reasoning' in parsed_json or 'references' in parsed_json):
        # normalize keys: allow 'references' or 'refs'
        refs = parsed_json.get('references') or parsed_json.get('refs') or parsed_json.get('references')
        parsed_json['references'] = refs or []
        structured = parsed_json
    else:
        # If the model didn't return JSON, attempt to synthesize a short structured answer from the raw content or retrieved excerpts
        if isinstance(content, str) and content.strip():
            # We will place the full content as 'answer' fallback and leave reasoning/references empty
            structured = {"answer": content.strip(), "reasoning": [], "references": [h.get('id') or h.get('source') for h in hits]}
        else:
            # last resort: join top retrieved snippets into a short answer
            joined = " ".join([h.get('text') for h in hits if h.get('text')])
            snippet = (joined[:800] + '...') if len(joined) > 800 else joined
            structured = {"answer": snippet or "I could not find relevant policy text.", "reasoning": [], "references": [h.get('id') or h.get('source') for h in hits]}

    # Build formatted_text and formatted_html from structured JSON
    def _build_formatted_from_struct(sj: dict) -> tuple[str, str]:
        import html, re

        ans = sj.get('answer') or ''
        reasoning = sj.get('reasoning') or []
        refs = sj.get('references') or sj.get('refs') or []
        # Compose markdown-like text
        parts = []
        parts.append('**Answer:**')
        parts.append(f"- {ans.strip()}")
        parts.append('\n**Reasoning (short):**')
        if isinstance(reasoning, list) and reasoning:
            for r in reasoning:
                parts.append(f"- {r}")
        else:
            # try to keep a short hint from the answer
            pass
        if refs:
            parts.append('\n**Policy Reference (if needed):**')
            for rf in refs:
                parts.append(f"- {rf}")
        text = '\n'.join(parts)
        # simple HTML conversion
        lines = text.splitlines()
        out_lines = []
        in_ul = False
        for ln in lines:
            ln = ln.rstrip()
            if ln.startswith('- '):
                if not in_ul:
                    out_lines.append('<ul>')
                    in_ul = True
                out_lines.append(f"<li>{html.escape(ln[2:])}</li>")
            else:
                if in_ul:
                    out_lines.append('</ul>')
                    in_ul = False
                # bold markers
                ln_html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html.escape(ln))
                out_lines.append(f"<div>{ln_html}</div>")
        if in_ul:
            out_lines.append('</ul>')
        return text, '\n'.join(out_lines)

    formatted_text, formatted_html = _build_formatted_from_struct(structured)
    # If structured answer is empty, attempt one retry asking the model to produce JSON-only output
    if not (structured.get('answer') and str(structured.get('answer')).strip()):
        try:
            retry_system = (
                "You are a corporate T&E policy assistant.\n"
                "Produce a JSON object ONLY with keys: answer (string), reasoning (array of strings), references (array of strings).\n"
                "Use only the provided policy excerpts. Keep answer under 120 words. Start with Yes/No if possible."
            )
            retry_prompt = "Produce the JSON for the user question and provided excerpts.\nUser question:\n" + query + "\n\nExcerpts:\n\n" + "\n---\n".join(context_parts)
            try:
                from .model_caps import send_model_request
                resp2 = send_model_request(
                    client,
                    model,
                    [{"role": "system", "content": retry_system}, {"role": "user", "content": retry_prompt}],
                    max_output_tokens=512,
                )
            except Exception:
                resp2 = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": retry_system}, {"role": "user", "content": retry_prompt}],
                    max_completion_tokens=512,
                )
            c2 = resp2.choices[0].message.content or ""
            try:
                j2 = json.loads(c2)
                if isinstance(j2, dict) and j2.get('answer'):
                    structured = j2
                    formatted_text, formatted_html = _build_formatted_from_struct(structured)
            except Exception:
                pass
        except Exception:
            log.exception('retry JSON generation failed')

    return {"answer": structured.get('answer'), "structured": structured, "formatted_text": formatted_text, "formatted_html": formatted_html, "sources": hits, "raw_retrieval": hits}
