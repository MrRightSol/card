from __future__ import annotations

import json
import os
import ast
from typing import Any, Dict, List
import logging

# Logger used by the policy parser to emit step-by-step processing details
log = logging.getLogger(__name__)
import re


def _fallback_rules(text: str) -> Dict[str, Any]:
    rules = [
        {
            "name": "Meal cap",
            "description": "Meals should not exceed $75 per person",
            "condition": "category == 'Meals' and amount > 75",
            "sql_condition": "category = 'Meals' AND amount > 75",
            "threshold": 75,
            "unit": "USD",
            "category": "Meals",
            "scope": "per txn",
            "applies_when": "business travel",
            "violation_message": "Meal exceeds $75 limit",
        },
        {
            "name": "Lodging nightly cap",
            "description": "Hotel nightly rate should not exceed $300",
            "condition": "category == 'Lodging' and amount > 300",
            "sql_condition": "category = 'Lodging' AND amount > 300",
            "threshold": 300,
            "unit": "USD",
            "category": "Lodging",
            "scope": "per night",
            "applies_when": "business travel",
            "violation_message": "Hotel rate exceeds $300/night",
        },
    ]
    return {"rules": rules, "version": "1.0", "source": "fallback"}


def parse_policy_text(text: str, prefer: str = "heuristic", model: str | None = None, max_completion_tokens: int | None = None) -> Dict[str, Any]:
    """Parse policy text into structured rules.

    prefer: 'heuristic' (default) or 'openai'. When 'heuristic', try the
    lightweight heuristic parser first and fall back to OpenAI if available.
    When 'openai', try OpenAI first and fall back to heuristics.
    """
    prefer = (prefer or "heuristic").lower()
    # parser_pref is passed down into normalization so callers can see which
    # parser was preferred/used. model_name is used for logging and metadata.
    parser_pref = prefer
    model_name = model or os.environ.get("OPENAI_MODEL") or "gpt-5-mini"
    use_openai = os.environ.get("USE_OPENAI", "1") not in {"0", "false", "False"}
    api_key = os.environ.get("OPENAI_API_KEY")

    def try_openai() -> Dict[str, Any] | None:
        if not (use_openai and api_key):
            return None
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI(api_key=api_key)
            # System prompt instructs the model to emit JSON describing rules
            # Provide the model with the canonical transaction fields so it only
            # emits conditions referencing existing columns. Try to read the
            # schema doc; fall back to a conservative list.
            try:
                df = open('docs/DATA_SCHEMA.md', 'r', encoding='utf-8').read()
                # combine lines and parse comma-separated tokens across the file
                combined = ",".join([ln.strip() for ln in df.splitlines() if ln.strip()])
                parts = [re.sub(r"\(.*?\)|\[.*?\]", "", p).strip() for p in combined.split(',') if p.strip()]
                allowed_fields = [p for p in parts if p]
                allowed_fields = [p for p in allowed_fields if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', p)]
            except Exception:
                allowed_fields = [
                    'txn_id', 'employee_id', 'merchant', 'city', 'category', 'timestamp', 'amount', 'channel', 'card_id',
                    'is_weekend', 'hour', 'day_total', 'merchant_txn_7d', 'city_distance_km'
                ]
            allowed = ", ".join(allowed_fields)
            prompt = (
                "Extract corporate travel & expense policy rules as JSON. Return a single JSON object with two keys: 'rules' and 'policy_statements'.\n"
                "'rules' should be an array of objects with: name, description, condition (Python expression), sql_condition (SQL expression), threshold, unit, category, scope, applies_when, violation_message, enforceable (true/false), confidence ('high'|'medium'|'low'), source_sentence_index (int).\n"
                "'policy_statements' should be an array of cleaned natural-language sentences extracted from the policy; each item can be either a string or an object with 'sentence' and 'source_index'.\n"
                "Use only the following transaction fields in conditions: {allowed}. Do NOT invent new field names.\n"
                "If the source policy mentions entities or fields that are not present in the transaction schema (e.g., specific merchants, cities, or non-existent columns), do NOT create an enforceable rule for them: instead include that text in 'policy_statements' and for any rule you mark enforceable=false add a short note in description explaining why.\n"
                "For condition use Python operators (==, !=, >, >=, <, <=, and/or). Also provide sql_condition using =, <>, AND, OR for SQL.\n"
                "Return ONLY the JSON object and nothing else."
            ).format(allowed=allowed)
            log.info("Calling OpenAI model=%s for parse", model_name)
            # Extra diagnostic info: log prompt/text sizes so we can estimate token usage
            try:
                log.info("OpenAI diagnostics: model=%s prompt_len=%d text_len=%d", model_name, len(prompt), len(text))
                print(f"[policy_parser] OpenAI request: model={model_name} prompt_len={len(prompt)} text_len={len(text)}")
            except Exception:
                pass
            # Some newer models may not accept a temperature=0 parameter.
            # Try deterministic (0) first, and if the model rejects it, retry
            # without the temperature parameter.
            # Use parameters supported by the newer models/SDKs: use max_completion_tokens
            base_kwargs = dict(
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                max_completion_tokens=(max_completion_tokens or 4096),
            )
            resp = None
            try:
                try:
                    from .model_caps import send_model_request
                    resp = send_model_request(client, base_kwargs.get('model'), base_kwargs.get('messages') or base_kwargs.get('input'), **base_kwargs)
                except Exception:
                    resp = client.chat.completions.create(**base_kwargs)
            except Exception as e:
                # Log and re-raise after adding diagnostic info
                log.exception("OpenAI call failed on create")
                raise
            # Extract model content
            try:
                content = resp.choices[0].message.content or "{}"
            except Exception:
                # Some SDKs use slightly different structure; try safe extraction
                try:
                    content = getattr(resp.choices[0].message, 'content', None) or "{}"
                except Exception:
                    content = str(resp)
            # If the content is very large, attempt to truncate preview in logs to keep output manageable
            content_str = str(content)
            if len(content_str) > 20000:
                log.info("OpenAI content trimmed for logging; full length=%d", len(content_str))
                print(f"[policy_parser] OpenAI response large, length={len(content_str)}; preview={content_str[:2000]}")
            else:
                print(f"[policy_parser] OpenAI response content_len={len(content_str)}")
            # Save full response to disk for traceability and offline inspection
            try:
                from pathlib import Path
                out_dir = Path('data') / 'openai_responses'
                out_dir.mkdir(parents=True, exist_ok=True)
                fname = out_dir / f"openai_resp_{int(__import__('time').time())}_{model_name}.json"
                # write stringified content (may be JSON or text)
                fname.write_text(content_str, encoding='utf-8')
                log.info("Saved OpenAI response to %s", str(fname))
                print(f"[policy_parser] OpenAI response saved to {str(fname)}")
            except Exception:
                log.exception("Failed to persist OpenAI response to disk")
            # Log response size and a short preview for debugging token usage
            try:
                log.info("OpenAI response received: model=%s response_len=%d", model_name, len(str(content)))
                print(f"[policy_parser] OpenAI response: model={model_name} response_len={len(str(content))}")
                # include a short preview in logs (avoid dumping extremely large content)
                log.debug("OpenAI response preview: %s", (str(content)[:1000] + '...') if len(str(content))>1000 else str(content))
            except Exception:
                pass
            # Try to parse the model output as JSON. If that fails, attempt to
            # extract a JSON object from the text (code block or first balanced
            # braces) as a best-effort recovery.
            try:
                data = json.loads(content)
            except Exception:
                candidate = _extract_json_object_from_text(content)
                if candidate:
                    try:
                        data = json.loads(candidate)
                        data.setdefault("extracted", True)
                    except Exception:
                        data = {}
                else:
                    data = {}

            # If the model returned a top-level list of rule objects, wrap it
            # into a dict with a 'rules' key so downstream normalization works.
            if isinstance(data, list):
                data = {"rules": data}

            if isinstance(data, dict) and "rules" in data:
                data["version"] = model_name
                data["source"] = "openai"
                data["parser"] = "openai api"
                # If model returned policy_statements include them in the result
                if isinstance(data.get('policy_statements'), list):
                    # ensure each policy_statement has expected shape
                    ps = []
                    for i, p in enumerate(data.get('policy_statements') or []):
                        if isinstance(p, dict) and 'sentence' in p:
                            ps.append({
                                'sentence': p.get('sentence'),
                                'source_index': p.get('source_index', i),
                            })
                        elif isinstance(p, str):
                            ps.append({'sentence': p, 'source_index': i})
                    data['policy_statements'] = ps
                log.info("OpenAI parse succeeded, rules=%d", len(data.get('rules', [])))
                try:
                    print(f"[policy_parser] OpenAI parsed JSON rules={len(data.get('rules',[]))} preview={str(json.dumps(data)[:2000])}")
                except Exception:
                    pass
                return _normalize_result(data, parser_pref, model_name)
        except Exception:
            log.exception("OpenAI parse failed")
            pass
        return None

    def try_heuristic() -> Dict[str, Any] | None:
        heur = _heuristic_parse(text)
        if heur and heur.get("rules"):
            heur.setdefault("version", "1.0")
            heur.setdefault("source", "heuristic")
            heur.setdefault("parser", "heuristic")
            return heur
        return None

    # Decide order based on preference
    if prefer == "openai":
        res = try_openai()
        if res:
            return _normalize_result(res, prefer, model_name)
        res = try_heuristic()
        if res:
            return _normalize_result(res, prefer, model_name)
    else:
        # default: heuristic first
        res = try_heuristic()
        if res:
            return _normalize_result(res, prefer, model_name)
        res = try_openai()
        if res:
            return res
    # If OpenAI is not available or fails, try a lightweight heuristic parser
    fb = _fallback_rules(text)
    fb.setdefault("parser", "fallback")
    return _normalize_result(fb, parser_pref, model_name)


def _extract_json_object_from_text(s: str) -> str | None:
    """Extract a JSON object from a larger string.

    Strategy:
    - Look for ```json ... ``` or ``` ... ``` fenced blocks and try to
      return the first {...} substring inside.
    - Otherwise find the first balance-matched {...} range in the text.
    Returns the JSON substring or None.
    """
    import re

    # Look for fenced code blocks first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)

    # Otherwise find first balanced braces
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _normalize_result(obj: Any, parser_pref: str | None, model_name: str | None) -> Dict[str, Any] | None:
    """Normalize various parser outputs into a consistent dict with 'rules' list.

    Ensures keys: rules (list), version, source, parser. Removes 'original_text'.
    """
    if obj is None:
        return None
    res: Dict[str, Any] = {}
    # If obj is a top-level list of rule-like dicts
    if isinstance(obj, list):
        res = {"rules": obj}
    elif isinstance(obj, dict):
        if isinstance(obj.get("rules"), list):
            res = dict(obj)
        else:
            # try to find the first list of dicts inside
            found = None
            for k, v in obj.items():
                if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    found = v
                    break
            if found is not None:
                res = {"rules": found}
            else:
                # fallback: if dict looks like a single rule, wrap
                if all(k in obj for k in ("name", "condition")):
                    res = {"rules": [obj]}
                else:
                    # unknown structure -> return empty rules with some metadata
                    res = {"rules": []}
    else:
        # unknown type -> empty rules
        res = {"rules": []}

    # Set identification metadata
    if parser_pref == 'openai':
        res["version"] = model_name or res.get("version", "")
        res["source"] = "openai"
        res["parser"] = "openai api"
    else:
        res.setdefault("version", "1.0")
        res.setdefault("source", parser_pref or res.get("source", "heuristic"))
        res.setdefault("parser", parser_pref or res.get("parser", "heuristic"))

    # Ensure each rule has a SQL-compatible condition variant for downstream use
    try:
        allowed_fields = _get_allowed_fields()
        allowed_set = set(allowed_fields)
        for r in res.get("rules", []):
            cond = r.get("condition")
            if cond:
                # If the returned condition isn't valid Python, try to coerce
                # SQL-style (=, <>) into a Python-evaluable form (==, !=, and/or)
                try:
                    ast.parse(cond, mode="eval")
                except Exception:
                    try:
                        py = _pyize_condition(cond)
                        ast.parse(py, mode="eval")
                        r["condition"] = py
                    except Exception:
                        pass
            if cond and "sql_condition" not in r:
                try:
                    r["sql_condition"] = _sqlize_condition(r.get("condition") or cond)
                except Exception:
                    r.setdefault("sql_condition", cond)
            # Validate identifiers used in the condition against allowed fields
            try:
                ids = _identifiers_in_expr(r.get('condition') or '')
                bad = [i for i in ids if i not in allowed_set and not i.isdigit()]
                if bad:
                    r['invalid_fields'] = bad
                    r['condition_valid'] = False
                    # Suggested synonym mappings for common policy terms
                    synonyms = {}
                    syn_map = {'day_total': 'amount', 'nightly_rate': 'amount', 'trip_type': 'category'}
                    for b in bad:
                        if b in syn_map:
                            synonyms[b] = syn_map[b]
                    if synonyms:
                        r['suggested_field_mapping'] = synonyms
                else:
                    r['condition_valid'] = True
            except Exception:
                r['condition_valid'] = False

            # Extract literal values used in the condition for entity validation
            try:
                fld_literals = _extract_field_literals(r.get('condition') or '')
                # For entity fields like merchant or city, verify values exist in data
                entity_issues: Dict[str, List[str]] = {}
                try:
                    from .db import distinct_values
                    for f, vals in fld_literals.items():
                        if f == 'category':
                            allowed_cats = _get_allowed_category_values()
                            bad_vals = [v for v in vals if v not in allowed_cats]
                            if bad_vals:
                                entity_issues[f] = bad_vals
                        elif f in {'merchant', 'city'}:
                            try:
                                existing = set(distinct_values(f, limit=10000))
                            except Exception:
                                existing = set()
                            # If DB returned no existing values, conservatively treat unknown as non-enforceable
                            if not existing:
                                entity_issues[f] = vals
                            else:
                                bad_vals = [v for v in vals if v not in existing]
                                if bad_vals:
                                    entity_issues[f] = bad_vals
                except Exception:
                    # DB not available: be conservative
                    for f, vals in fld_literals.items():
                        if f == 'category':
                            allowed_cats = _get_allowed_category_values()
                            bad_vals = [v for v in vals if v not in allowed_cats]
                            if bad_vals:
                                entity_issues[f] = bad_vals
                        elif f in {'merchant', 'city'}:
                            # Without DB knowledge, treat merchant/city literal usage as non-enforceable
                            entity_issues[f] = vals
                if entity_issues:
                    r.setdefault('non_enforceable_reasons', {})
                    r['non_enforceable_reasons'].update({f: vals for f, vals in entity_issues.items()})
                    r['enforceable'] = False
                else:
                    # If not already invalid by identifiers, mark enforceable true
                    if not r.get('condition_valid', False):
                        r['enforceable'] = False
                    else:
                        r.setdefault('enforceable', True)
            except Exception:
                # on any error, conservatively mark as non-enforceable
                r['enforceable'] = False
            # Set default confidence and ensure source index exists
            try:
                if 'confidence' not in r:
                    r['confidence'] = 'high' if r.get('enforceable') else 'low'
            except Exception:
                r.setdefault('confidence', 'low')
            try:
                if 'source_sentence_index' not in r:
                    # try common alternate keys
                    r['source_sentence_index'] = r.get('source_index', None)
            except Exception:
                r.setdefault('source_sentence_index', None)
    except Exception:
        pass

    # Remove large original_text if present
    if "original_text" in res:
        try:
            del res["original_text"]
        except Exception:
            pass

    return res


def _get_allowed_fields() -> List[str]:
    # Use the authoritative MSSQL transactions schema fields. We keep this
    # authoritative to avoid models inventing non-existent fields.
    return [
        'txn_id', 'employee_id', 'merchant', 'city', 'category', 'amount', 'timestamp', 'channel', 'card_id',
        'is_fraud', 'label', 'policy_flags'
    ]


def _identifiers_in_expr(expr: str) -> List[str]:
    try:
        node = ast.parse(expr, mode='eval')
    except Exception:
        return []
    ids = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            ids.add(n.id)
    return list(ids)


def _extract_field_literals(expr: str) -> Dict[str, List[str]]:
    """Return mapping field_name -> list of string literal values used with that field.

    Examples handled:
      merchant == 'Minibar'
      merchant in ('Minibar','Spa')
      'Minibar' == merchant
    """
    out: Dict[str, List[str]] = {}
    try:
        node = ast.parse(expr, mode='eval')
    except Exception:
        return out

    for n in ast.walk(node):
        if isinstance(n, ast.Compare):
            # left side may be Name or Constant
            left_name = None
            if isinstance(n.left, ast.Name):
                left_name = n.left.id
            # comparators may be constants or tuples/lists
            for comp in n.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    if left_name:
                        out.setdefault(left_name, []).append(comp.value)
                    else:
                        # left is constant; attempt to find name in comparator side
                        pass
                if isinstance(comp, (ast.Tuple, ast.List)):
                    for elt in comp.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and left_name:
                            out.setdefault(left_name, []).append(elt.value)
        # handle reversed comparisons like 'Minibar' == merchant
        if isinstance(n, ast.Compare):
            for comp in n.comparators:
                if isinstance(n.left, ast.Constant) and isinstance(n.left.value, str) and isinstance(comp, ast.Name):
                    out.setdefault(comp.id, []).append(n.left.value)
    return out


def _get_allowed_category_values() -> List[str]:
    try:
        txt = open('docs/DATA_SCHEMA.md', 'r', encoding='utf-8').read()
        # look for category[...] pattern
        m = re.search(r"category\s*\[(.*?)\]", txt, flags=re.IGNORECASE)
        if m:
            items = [p.strip() for p in m.group(1).split('|') if p.strip()]
            return items
    except Exception:
        pass
    return ["Meals", "Travel", "Lodging", "Supplies", "Transport", "Other"]


def _sqlize_condition(cond: str) -> str:
    if not cond:
        return cond
    s = str(cond)
    # not equal first
    s = re.sub(r"\s*!=\s*", " <> ", s)
    # equality
    s = re.sub(r"\s*==\s*", " = ", s)
    # boolean ops
    s = re.sub(r"\band\b", " AND ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bor\b", " OR ", s, flags=re.IGNORECASE)
    # True/False
    s = re.sub(r"\bTrue\b", "1", s)
    s = re.sub(r"\bFalse\b", "0", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _pyize_condition(cond: str) -> str:
    if not cond:
        return cond
    s = str(cond)
    s = re.sub(r"\s*<>\s*", " != ", s)
    s = re.sub(r"(?<![<>=!])\s=\s(?![=])", " == ", s)
    s = re.sub(r"\bAND\b", " and ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bOR\b", " or ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _heuristic_parse(text: str) -> Dict[str, Any]:
    """Try to extract simple threshold-style rules from policy text.

    This is a best-effort, lightweight parser intended to run locally and
    return quickly when OpenAI is not available. It focuses on numeric
    thresholds and simple scope/unit patterns (per day/night/txn/person).
    """
    rules: List[Dict[str, Any]] = []
    # Normalize whitespace
    t = re.sub(r"\s+", " ", text)

    # Pattern: <Category> ... up to $X(/unit)? or ... not exceed $X(/unit)?
    pat = re.compile(
        r"(?P<category>\b[A-Z][a-zA-Z ]{2,30}?\b).*?(?:up to|no more than|not exceed|should not exceed|limit of|cap of)\s*\$?(?P<threshold>\d+(?:\.\d+)?)(?:\s*/?\s*(?P<unit>day|night|txn|transaction|person|per person))?",
        flags=re.IGNORECASE,
    )
    for m in pat.finditer(t):
        cat = (m.group("category") or "").strip()
        thr = float(m.group("threshold"))
        unit = m.group("unit") or "per txn"
        # normalize unit
        unit_map = {"day": "per day", "night": "per night", "txn": "per txn", "transaction": "per txn", "person": "per person"}
        scope = unit_map.get(unit.lower(), unit)
        name = f"{cat} cap"
        condition = f"category == '{cat}' and amount > {thr}"
        rules.append(
            {
                "name": name,
                "description": f"{cat} limit extracted from text",
                "condition": condition,
                "sql_condition": _sqlize_condition(condition),
                "threshold": thr,
                "unit": "USD",
                "category": cat,
                "scope": scope,
                "applies_when": "business travel",
                "violation_message": f"{cat} exceeds {thr} {scope}",
            }
        )
    log.debug("heuristic_parse: found %d rules", len(rules))

    # Fallback: try to find simple $X/day style mentions with a nearby word as category
    if not rules:
        simple = re.findall(r"([A-Za-z]{3,20})[^\n\r]{0,40}?\$([0-9]+(?:\.[0-9]+)?)\s*(?:/|per)?\s*(day|night|person)?", t, flags=re.IGNORECASE)
        for item in simple:
            cat = item[0].strip()
            thr = float(item[1])
            unit = item[2] or "per txn"
            unit_map = {"day": "per day", "night": "per night", "person": "per person"}
            scope = unit_map.get(unit.lower(), unit)
            name = f"{cat} cap"
            rules.append(
                {
                    "name": name,
                    "description": f"{cat} limit extracted from text",
                    "condition": f"category == '{cat}' and amount > {thr}",
                    "sql_condition": _sqlize_condition(f"category == '{cat}' and amount > {thr}"),
                    "threshold": thr,
                    "unit": "USD",
                    "category": cat,
                    "scope": scope,
                    "applies_when": "business travel",
                    "violation_message": f"{cat} exceeds {thr} {scope}",
                }
            )
        if simple:
            log.debug("heuristic_parse (simple): found %d rules", len(simple))

    # Additional heuristic: detect explicit non-reimbursable statements
    deny_pat = re.compile(r"(?P<category>\b[A-Z][a-zA-Z ]{2,30}?\b):?\s+not\s+(?:reimbursable|allowed|permitted)", flags=re.IGNORECASE)
    for m in deny_pat.finditer(t):
        cat = m.group('category').strip()
        cond = f"category == '{cat}'"
        try:
            sqlc = _sqlize_condition(cond)
        except Exception:
            sqlc = cond
        rules.append({
            'name': f"{cat} not reimbursable",
            'description': f"{cat} is not reimbursable",
            'condition': cond,
            'sql_condition': sqlc,
            'threshold': 0,
            'unit': 'USD',
            'category': cat,
            'scope': 'per txn',
            'applies_when': 'business travel',
            'violation_message': f"{cat} is not reimbursable",
        })
    return {"rules": rules, "version": "1.0", "source": "heuristic"} if rules else {}


def parse_policy_file(content: bytes, filename: str | None = None) -> Dict[str, Any]:
    # First, try to detect common document types (docx) and extract text
    # Note: OpenAI-based extraction is performed by the dedicated
    # /extract-text endpoint. This helper was removed to keep parsing and
    # extraction responsibilities separate.

    try:
        # detect DOCX (it's a ZIP archive containing word/document.xml)
        import io
        import zipfile
        from xml.etree import ElementTree as ET

        bio = io.BytesIO(content)
        if zipfile.is_zipfile(bio):
            with zipfile.ZipFile(bio) as z:
                # common docx document path
                if any(p.startswith('word/') for p in z.namelist()):
                    if 'word/document.xml' in z.namelist():
                        try:
                            raw = z.read('word/document.xml')
                            # parse XML and extract text from w:t nodes
                            # handle namespaces by ignoring them in tag names
                            tree = ET.fromstring(raw)
                            texts: list[str] = []
                            for elem in tree.iter():
                                # local-name check for 't' (w:t)
                                tag = elem.tag
                                if tag.endswith('}t') or tag == 't' or tag.endswith('}text'):
                                    if elem.text:
                                        texts.append(elem.text)
                            doc_txt = '\n'.join(texts)
                            # hand off to the text parser
                            return parse_policy_text(doc_txt)
                        except Exception:
                            log.exception('failed to extract text from docx')
                            # fall through to other handlers
    except Exception:
        # if zip/xml processing fails, continue to normal JSON/text handling
        log.debug('docx detection/extraction failed or not a docx file')

    # Detect PDF files (simple magic header check) and try to extract text
    try:
        if content[:4] == b'%PDF':
            # Try PyMuPDF (fitz) first
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(stream=content, filetype='pdf')
                texts = []
                for page in doc:
                    try:
                        ptxt = page.get_text()
                        if ptxt:
                            texts.append(ptxt)
                    except Exception:
                        log.exception('error extracting text from a PDF page (fitz)')
                pdf_txt = '\n'.join(texts)
                if pdf_txt.strip():
                    return parse_policy_text(pdf_txt)
            except Exception:
                log.debug('PyMuPDF not available or failed; trying pdfminer.six')
            # Try pdfminer.six as a fallback
            try:
                from io import BytesIO, StringIO
                from pdfminer.high_level import extract_text_to_fp

                out = StringIO()
                fp = BytesIO(content)
                extract_text_to_fp(fp, out)
                pdf_txt = out.getvalue()
                if pdf_txt.strip():
                    return parse_policy_text(pdf_txt)
            except Exception:
                log.exception('pdfminer extraction failed or pdfminer not installed')
            # If we reach here, PDF extraction failed locally. Extraction via
            # OpenAI should be invoked via the /extract-text endpoint so the
            # UI can explicitly request OpenAI extraction. Return a clear note
            # so the client can act accordingly.
            log.info('PDF uploaded but no local extractor succeeded')
            return {"rules": [], "version": "1.0", "source": "upload", "note": "pdf_extraction_failed_local"}
    except Exception:
        # any unexpected error shouldn't block further processing
        log.exception('unexpected error during pdf detection/extraction')

    # Try to decode as UTF-8 text and parse JSON policy, otherwise parse text
    try:
        txt = content.decode("utf-8", errors="ignore")
        maybe = json.loads(txt)
        # If the uploaded file is already JSON, accept either a dict with a
        # top-level 'rules' key or a top-level list of rule dicts.
        if isinstance(maybe, dict) and "rules" in maybe:
            maybe.setdefault("version", "1.0")
            maybe.setdefault("source", filename or "upload")
            return maybe
        if isinstance(maybe, list) and len(maybe) > 0 and isinstance(maybe[0], dict):
            return {"rules": maybe, "version": "1.0", "source": (filename or "upload"), "parser": "upload"}
    except Exception:
        # not JSON, continue to text parsing
        txt = content.decode("utf-8", errors="ignore")
    # Use the full file text for parsing (heuristic or OpenAI)
    return parse_policy_text(txt)
