from fastapi import APIRouter, Request
import importlib.util
import logging

# Logger for policy parsing endpoint. We log each step of the upload/parse
# flow to help tracing and debugging in production or when running locally.
log = logging.getLogger(__name__)
from pydantic import BaseModel
from typing import Any
import json
from ..services.policy_parser import parse_policy_text, parse_policy_file
from fastapi import UploadFile, File, HTTPException
import io
import zipfile
import base64
import threading
import uuid
from typing import Dict

router = APIRouter()

# Simple in-memory job store for extraction background tasks
# job_id -> { status: 'pending'|'running'|'done'|'error', progress: int (0-100), result: str|None, error: str|None }
_extract_jobs: Dict[str, Dict] = {}
_extract_jobs_lock = threading.Lock()


def _set_job(job_id: str, **kwargs):
    with _extract_jobs_lock:
        job = _extract_jobs.setdefault(job_id, {'status': 'pending', 'progress': 0, 'result': None, 'error': None})
        job.update(kwargs)


def _get_job(job_id: str):
    with _extract_jobs_lock:
        return dict(_extract_jobs.get(job_id, {}))


def _attach_used_model(out: Any, model_pref: str | None, parser_pref: str | None):
    try:
        if isinstance(out, dict) and parser_pref == 'openai':
            out['used_model'] = model_pref
    except Exception:
        pass
    return out


def _extract_worker(path: str, filename: str, job_id: str):
    try:
        _set_job(job_id, status='running', progress=5)
        # read file bytes
        with open(path, 'rb') as f:
            content = f.read()
        # If file is PDF or docx, try local fast extraction first (docx xml, PyMuPDF/pdfminer)
        txt = None
        try:
            # reuse parse_policy_file local extraction: call parse_policy_file which returns parsed rules if JSON,
            # but we want raw text. Instead try to detect docx/pdf and extract textual content here.
            from ..services.policy_parser import parse_policy_file
            # parse_policy_file returns structured rules if it can parse; but it will call parse_policy_text when given plain text.
            # For extracting text, we'll attempt simple DOCX XML extraction or PDF extraction via existing code paths.
            # Try DOCX xml
            import io, zipfile
            bio = io.BytesIO(content)
            if zipfile.is_zipfile(bio) and 'word/document.xml' in zipfile.ZipFile(bio).namelist():
                # reuse existing docx extraction in parse_policy_file by calling it and then falling back
                # but simpler: extract w:t values
                bio.seek(0)
                z = zipfile.ZipFile(bio)
                raw = z.read('word/document.xml')
                from xml.etree import ElementTree as ET
                tree = ET.fromstring(raw)
                texts = []
                for elem in tree.iter():
                    tag = elem.tag
                    if tag.endswith('}t') or tag == 't' or tag.endswith('}text'):
                        if elem.text:
                            texts.append(elem.text)
                txt = '\n'.join(texts)
        except Exception:
            txt = None
        _set_job(job_id, progress=25)
        # If no docx text found, attempt PDF local extraction
        if not txt:
            try:
                # Try PyMuPDF
                try:
                    import fitz
                    doc = fitz.open(stream=content, filetype='pdf')
                    pages = []
                    for p in doc:
                        pages.append(p.get_text())
                    txtp = '\n'.join(pages).strip()
                    if txtp:
                        txt = txtp
                except Exception:
                    txt = None
                # Try pdfminer if still no text
                if not txt:
                    try:
                        from io import BytesIO, StringIO
                        from pdfminer.high_level import extract_text_to_fp
                        out = StringIO()
                        fp = BytesIO(content)
                        extract_text_to_fp(fp, out)
                        pdf_txt = out.getvalue()
                        if pdf_txt.strip():
                            txt = pdf_txt
                    except Exception:
                        txt = None
            except Exception:
                txt = None
        _set_job(job_id, progress=50)
        # If still no text, try OCR (pytesseract) if available
        if not txt:
            try:
                try:
                    from pdf2image import convert_from_bytes
                    import pytesseract
                    from PIL import Image
                    pages = convert_from_bytes(content)
                    ocr_texts = []
                    for i, page in enumerate(pages):
                        ocr_texts.append(pytesseract.image_to_string(page))
                        _set_job(job_id, progress=50 + int(40 * (i+1)/max(1, len(pages))))
                    txt = '\n'.join(ocr_texts)
                except Exception:
                    txt = None
            except Exception:
                txt = None
        _set_job(job_id, progress=90)
        # If still no text, use OpenAI extraction as last resort
        if not txt:
            try:
                import base64
                from openai import OpenAI
                client = OpenAI(api_key=__import__('os').environ.get('OPENAI_API_KEY'))
                b64 = base64.b64encode(content).decode('ascii')
                system = "You are a helpful assistant that extracts readable plain text from files. Return ONLY the extracted plain text and nothing else."
                user_msg = f"extract text from this file\nFilename: {filename}\nBase64:\n{b64}"
                try:
                    from ..services.model_caps import send_model_request
                    resp = send_model_request(client, (__import__('os').environ.get('OPENAI_MODEL') or 'gpt-4o-mini'), [{'role':'system','content':system},{'role':'user','content':user_msg}], max_output_tokens=6000)
                except Exception:
                    resp = client.chat.completions.create(
                        model=(__import__('os').environ.get('OPENAI_MODEL') or 'gpt-4o-mini'),
                        messages=[{'role':'system','content':system},{'role':'user','content':user_msg}],
                        max_completion_tokens=6000,
                    )
                try:
                    txt = resp.choices[0].message.content or ''
                except Exception:
                    txt = str(resp)
            except Exception:
                txt = None

        if txt:
            _set_job(job_id, status='done', progress=100, result=str(txt))
        else:
            _set_job(job_id, status='error', progress=100, error='extraction_failed')
    except Exception as e:
        log.exception('extract worker failed')
        _set_job(job_id, status='error', progress=100, error=str(e))



@router.get('/debug/openai-simulate')
def debug_openai_simulate(model: str | None = None):
    """Return the most recent saved OpenAI response (for UI simulation).

    This endpoint is intended for local debugging only. It looks in
    data/openai_responses for the newest file, optionally filtered by model
    name, and returns its parsed JSON or raw text.
    """
    from pathlib import Path
    d = Path('data') / 'openai_responses'
    if not d.exists():
        return { 'error': 'no_responses' }
    files = sorted(list(d.glob('openai_resp_*.json')), key=lambda p: p.stat().st_mtime, reverse=True)
    if model:
        files = [p for p in files if f"_{model}.json" in p.name]
    if not files:
        return { 'error': 'no_matching_responses' }
    p = files[0]
    try:
        txt = p.read_text(encoding='utf-8')
        try:
            j = json.loads(txt)
            log.info('debug/openai-simulate: returning parsed JSON from %s', str(p))
            return j
        except Exception:
            log.info('debug/openai-simulate: returning raw text from %s', str(p))
            return { 'raw': txt }
    except Exception:
        log.exception('debug/openai-simulate: failed to read file %s', str(p))
        return { 'error': 'read_failed' }


@router.get('/parse-config')
def parse_config():
    import os

    return {
        'openai_available': bool(os.environ.get('OPENAI_API_KEY')),
        'default_model': os.environ.get('OPENAI_MODEL') or 'gpt-5-mini',
    }



@router.get('/extract-warning')
def extract_warning(file_name: str | None = None) -> Any:
    """Return a user-facing warning message about using an LLM to extract text.

    If OpenAI is available, ask the model to generate a concise friendly
    warning that mentions potential costs and asks for user's consent.
    Otherwise return a sensible fallback message instructing the user to
    copy/paste the text into the UI.
    """
    import os
    api_key = os.environ.get('OPENAI_API_KEY')
    filename = file_name or 'your document'
    fallback = (
        f"The selected file ({filename}) appears to be a binary document (DOCX/PDF). "
        "We can extract the text from it using an external LLM service, which may incur additional costs. "
        "If you consent, we will send the file to the LLM for text extraction. "
        "If you prefer not to use the LLM, please open the file locally and copy & paste the text into the policy text box. "
        "Do you want to proceed with LLM extraction?"
    )
    if not api_key:
        return {'message': (
            f"OpenAI integration is not configured on the server. \n\n{fallback}"
        )}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        system = (
            "You are a helpful friendly assistant. Produce a short user-facing message (50-120 chars) "
            "that warns the user we will send their uploaded document to an external LLM for text extraction, "
            "that this may incur additional costs, asks for consent, and offers the alternative to paste text manually. "
            "Return only the message text, no markup or JSON."
        )
        user = f"File name: {filename}." + "\nProvide a concise consent prompt the UI can show to the user." 
        try:
            from ..services.model_caps import send_model_request
            resp = send_model_request(client, (os.environ.get('OPENAI_MODEL') or 'gpt-4o-mini'), [{'role':'system','content':system},{'role':'user','content':user}], max_output_tokens=200)
        except Exception:
            resp = client.chat.completions.create(
                model=(os.environ.get('OPENAI_MODEL') or 'gpt-4o-mini'),
                messages=[{'role':'system','content':system},{'role':'user','content':user}],
                max_completion_tokens=200
            )
        try:
            msg = resp.choices[0].message.content or ''
        except Exception:
            msg = str(resp)
        # Ensure we return a simple message string
        text = str(msg).strip()
        if not text:
            text = fallback
        return {'message': text}
    except Exception:
        log.exception('extract_warning generation failed; falling back to static message')
        return {'message': fallback}



class ParsePolicyTextBody(BaseModel):
    text: str


@router.post("/parse-policy")
async def parse_policy_endpoint(request: Request) -> Any:
    ctype = request.headers.get("content-type", "")
    # optional query param: parser=heuristic|openai
    parser_pref = request.query_params.get("parser")
    model_pref = request.query_params.get("model")
    # Default parsing preference is heuristic unless the client explicitly requests OpenAI
    if not parser_pref:
        parser_pref = "heuristic"
    max_pref = request.query_params.get("max_completion_tokens")
    try:
        max_pref = int(max_pref) if max_pref is not None else None
    except Exception:
        max_pref = None
    # If client requested openai but the package is not installed, log a helpful message
    if parser_pref == "openai":
        if importlib.util.find_spec("openai") is None:
            log.warning("OpenAI parser requested but 'openai' package is not installed in the environment. Falling back to heuristic.")
    # Log incoming request basic info for traceability
    try:
        client = request.client.host if request.client is not None else 'unknown'
    except Exception:
        client = 'unknown'
    log.info("parse-policy called, client=%s, content-type=%s, parser_pref=%s, model_pref=%s", client, ctype, parser_pref, model_pref)
    # Ensure parser/service logs are visible at INFO level
    try:
        logging.getLogger('api.app.services.policy_parser').setLevel(logging.INFO)
    except Exception:
        pass
    # Prefer framework multipart parsing instead of manual parsing
    if ctype.startswith("multipart/form-data"):
        form = None
        try:
            form = await request.form()
        except Exception as e:
            # starlette raises an AssertionError requiring python-multipart to be
            # installed. If that's the case, fall back to a manual multipart
            # parser that extracts the 'policy' part.
            msg = str(e)
            log.warning("request.form() failed: %s; attempting manual multipart parse", msg)
            body = await request.body()
            boundary = None
            try:
                for part in ctype.split(";"):
                    part = part.strip()
                    if part.startswith("boundary="):
                        boundary = part.split("=", 1)[1].strip().strip('"')
                        break
            except Exception:
                boundary = None

            content = b""
            filename = None
            if boundary:
                bsep = ("--" + boundary).encode()
                sections = body.split(bsep)
                for sec in sections:
                    if b"Content-Disposition" not in sec:
                        continue
                    head, _, content_part = sec.partition(b"\r\n\r\n")
                    if b"name=\"policy\"" not in head:
                        continue
                    # extract filename if present
                    try:
                        h = head.decode("utf-8", errors="ignore")
                        lines = [ln for ln in h.splitlines() if ln.strip()]
                        first_line = ""
                        for ln in lines:
                            if ln.lower().startswith("content-disposition"):
                                first_line = ln
                                break
                        for token in first_line.split(";"):
                            token = token.strip()
                            if token.startswith("filename="):
                                filename = token.split("=", 1)[1].strip().strip('"') or None
                                break
                    except Exception:
                        filename = None
                    content = content_part.rstrip(b"\r\n")
                    break

            # if we manually parsed something, ensure we have content available
            if not (content is not None and content != b""):
                log.warning("Manual multipart parsing did not find a 'policy' part")
                return {"rules": [], "version": "1.0", "source": "upload"}

        # If we have a form (python-multipart available) use it, otherwise
        # fall back to the manually extracted content/filename variables above
        if form is not None and "policy" in form:
            part = form["policy"]
            # UploadFile or simple str
            try:
                # Starlette UploadFile
                content = await part.read()
                filename = getattr(part, "filename", None)
            except Exception:
                # If it's not an UploadFile, try to coerce to string
                try:
                    content = str(part).encode("utf-8")
                except Exception:
                    content = b""
                filename = None
            # Log uploaded file summary
            try:
                clen = len(content) if content is not None else 0
            except Exception:
                clen = 0
            log.info("Uploaded file received: filename=%s, bytes=%d", filename, clen)
            # Persist uploaded file to server for traceability and possible later use
            uploaded_path = None
            try:
                from pathlib import Path
                up_dir = Path('data') / 'uploads'
                up_dir.mkdir(parents=True, exist_ok=True)
                # Ensure we have bytes content
                bcontent = content if isinstance(content, (bytes, bytearray)) else bytes(content)
                fname = (getattr(part, 'filename', None) or 'policy_upload')
                # sanitize filename a bit
                fname = fname.replace('/', '_').replace('..', '_')
                dest = up_dir / f"{int(__import__('time').time())}_{fname}"
                dest.write_bytes(bcontent)
                uploaded_path = str(dest)
            except Exception:
                log.exception("Failed to persist uploaded file to data/uploads")
                uploaded_path = None

            # If the client explicitly requested OpenAI-based extraction for
            # an uploaded binary document (docx/pdf), instruct the client to
            # call the dedicated /extract-text endpoint instead — this keeps
            # parsing (parse-policy) and extraction (extract-text) distinct.
            try:
                is_docx = False
                is_pdf = False
                try:
                    bio = io.BytesIO(content)
                    is_docx = zipfile.is_zipfile(bio)
                except Exception:
                    is_docx = False
                try:
                    is_pdf = content[:4] == b'%PDF'
                except Exception:
                    is_pdf = False
            except Exception:
                is_docx = is_pdf = False

            if parser_pref == 'openai' and (is_docx or is_pdf):
                # Return a clear 400 so the UI can call /extract-text instead.
                raise HTTPException(status_code=400, detail='file_is_binary_use_extract_text: upload binary docs (docx/pdf) should be sent to POST /extract-text for OpenAI extraction')

            # Try to parse the uploaded file. parse_policy_file will attempt
            # to detect docx and other structured formats and extract text
            # before applying the heuristic/OpenAI parsers.
            try:
                out = parse_policy_file(content, filename=(getattr(part, 'filename', None) or filename))
            except Exception:
                log.exception('parse_policy_file failed; falling back to text parse')
                txt = content.decode("utf-8", errors="ignore")
                if parser_pref == 'openai' and len(txt.strip()) < 20:
                    out = parse_policy_text(txt, prefer='heuristic')
                    out.setdefault('note', 'openai_skipped_insufficient_content')
                else:
                    out = parse_policy_text(txt, prefer=parser_pref or "heuristic", model=model_pref, max_completion_tokens=max_pref)

            if uploaded_path:
                out.setdefault('uploaded_path', uploaded_path)
            log.info("Parsed uploaded file, rules=%d, parser=%s", len(out.get('rules', [])), out.get('parser'))
            return _attach_used_model(out, model_pref, parser_pref)
        else:
            # No python-multipart form, but we may have manually extracted content
            if content is not None and content != b"":
                # If the client asked for OpenAI extraction, and the manually
                # uploaded content is a binary doc (docx/pdf), instruct the
                # client to call /extract-text instead of /parse-policy.
                try:
                    bio = io.BytesIO(content)
                    is_docx = zipfile.is_zipfile(bio)
                except Exception:
                    is_docx = False
                try:
                    is_pdf = content[:4] == b'%PDF'
                except Exception:
                    is_pdf = False
                if parser_pref == 'openai' and (is_docx or is_pdf):
                    raise HTTPException(status_code=400, detail='file_is_binary_use_extract_text: upload binary docs (docx/pdf) should be sent to POST /extract-text for OpenAI extraction')

                # Attempt to parse file bytes via parse_policy_file which will
                # handle docx extraction and JSON detection.
                try:
                    out = parse_policy_file(content, filename=filename)
                except Exception:
                    log.exception('parse_policy_file failed for manual multipart; falling back to text parse')
                    try:
                        txt = content.decode("utf-8", errors="ignore")
                    except Exception:
                        txt = str(content)
                    if parser_pref == 'openai' and len(txt.strip()) < 20:
                        out = parse_policy_text(txt, prefer='heuristic')
                        out.setdefault('note', 'openai_skipped_insufficient_content')
                    else:
                        out = parse_policy_text(txt, prefer=parser_pref or "heuristic", model=model_pref, max_completion_tokens=max_pref)

                if uploaded_path:
                    out.setdefault('uploaded_path', uploaded_path)
                log.info("Parsed uploaded file (manual), rules=%d, parser=%s", len(out.get('rules', [])), out.get('parser'))
                return _attach_used_model(out, model_pref, parser_pref)
            return {"rules": [], "version": "1.0", "source": "upload"}
    # Non-multipart: prefer JSON body then pydantic model
    try:
        js = await request.json()
        if isinstance(js, dict) and "text" in js:
            txt = str(js["text"] or "")
            # Skip OpenAI if insufficient content
            if parser_pref == 'openai' and len(txt.strip()) < 20:
                log.info("OpenAI parsing skipped for JSON body due to insufficient content; falling back to heuristic")
                res = parse_policy_text(txt, prefer='heuristic')
                res.setdefault('note', 'openai_skipped_insufficient_content')
                return res
            return parse_policy_text(txt, prefer=parser_pref or "heuristic", model=model_pref, max_completion_tokens=max_pref)
    except Exception:
        pass
    return {"rules": [], "version": "1.0", "source": "none"}



@router.post('/extract-text')
async def extract_text_endpoint(policy: UploadFile | None = File(None)) -> Any:
    """Accept a file upload, persist it, and start background extraction job.

    Returns a job_id which the client can poll via /extract-status and then
    fetch results via /extract-result when done.
    """
    if policy is None:
        return { 'error': 'no_file' }

    try:
        content = await policy.read()
    except Exception:
        return { 'error': 'failed_read' }

    from pathlib import Path
    up_dir = Path('data') / 'uploads'
    up_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    dest = up_dir / f"{job_id}_{(policy.filename or 'upload')}"
    try:
        dest.write_bytes(content)
    except Exception:
        return { 'error': 'failed_save_upload' }

    _set_job(job_id, status='pending', progress=0, result=None, error=None)
    t = threading.Thread(target=_extract_worker, args=(str(dest), policy.filename or 'upload', job_id), daemon=True)
    t.start()
    return { 'job_id': job_id, 'status': 'started' }


@router.get('/extract-status')
def extract_status(job_id: str) -> Any:
    job = _get_job(job_id)
    if not job:
        return { 'error': 'not_found' }
    return { 'job_id': job_id, 'status': job.get('status'), 'progress': job.get('progress', 0), 'error': job.get('error') }


@router.get('/extract-result')
def extract_result(job_id: str) -> Any:
    job = _get_job(job_id)
    if not job:
        return { 'error': 'not_found' }
    if job.get('status') != 'done':
        return { 'error': 'not_ready', 'status': job.get('status'), 'progress': job.get('progress') }
    return { 'text': job.get('result') }
