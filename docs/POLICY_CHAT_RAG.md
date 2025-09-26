Policy Chat & RAG (Retrieval-Augmented Generation)
===============================================

This document explains the policy parsing, RAG-based chat, and related UI features so users and maintainers understand how to use and troubleshoot them.

High-level features
- Generate Data
  - Generate synthetic dataset (dev utility). See Generate Data step in UI.
  - Browse Transactions: load / view generated or DB-backed transactions.
  - Logs: recent server and client-side logs for tracing UI actions.

- Parse Policy
  - File parser: paste policy text or upload a policy file and click Parse Text. The server will attempt heuristic parsing first and optionally call OpenAI when enabled.
  - Parsed Policy JSON: shows the parser output (editable). You may review or modify and Apply Parsed JSON.
  - Bots: create a small bot for quick Q&A using the parsed policy. Each bot stores simple chunks of the policy and can be chatted with. You can delete bots.
  - Policy Chat (RAG): a RAG-powered chat that retrieves relevant policy excerpts and asks an LLM to answer the user's question while citing sources.

Why RAG?
- RAG combines a vector index (embeddings) for retrieval with an LLM for fluent answers. This provides:
  - Provenance: answers include citations to original policy excerpts
  - Updatability: re-index when policies change (no model retraining required)
  - Cost control: embeddings use cheaper models; generation uses the model you choose

Quick UI workflow
1. Parse policy text or upload a policy file (Parse Policy tab).
2. (Optional) Create a bot from the parsed policy (Bots card) for quick local Q&A.
3. In Policy Chat (RAG) ask a question. If the vector index has not been built, the UI will prompt you to Build Index.
4. Click Build Index to create embeddings (this calls the OpenAI Embeddings API and may incur cost). After success the pending query retries automatically.

API endpoints (server)
- POST /index-policies
  - Rebuilds the vector index from known policy sources (data/openai_responses, data/uploads, data/bots)
  - Body: { "embed_model": "text-embedding-3-small" } (optional)
  - Returns: { ok: true, indexed: N }

- POST /chat-policy
  - Query the RAG chat: { "query": "...", "top_k": 4 }
  - Requires the vector index to be built. If not built it returns a helpful 400 error: index_not_built: run POST /index-policies
  - Returns: { answer, sources, formatted_html, formatted_text, sources_readable }

- GET /openai-models
  - Lists available OpenAI model ids via the OpenAI API (requires OPENAI_API_KEY)

- /bots endpoints (simple bots)
  - POST /bots { name, text, model } -> creates a bot (stores chunks in data/bots/{id})
  - GET /bots -> list available bots
  - DELETE /bots/{bot_id} -> delete bot files
  - POST /bots/{bot_id}/chat { message } -> chat with a bot (simple chunk matching + optional OpenAI generation)

Where content is sourced from
- data/openai_responses/*.json — model outputs saved by the parser for traceability. These may be JSON arrays or objects; the parser extracts readable text.
- data/uploads/* — uploaded policy files saved from the UI
- data/bots/*/chunks.json — small bot chunks created by the UI
- data/vector_store/* — generated embeddings and metadata created by POST /index-policies

Indexing details
- Chunking: text is split into overlapping chunks (~700 chars with 100 char overlap)
- Deduplication: during indexing small/empty chunks are skipped and repeated excerpts are deduplicated
- Embeddings: embeddings are computed via OpenAI (default: text-embedding-3-small) and saved to data/vector_store/embeddings.npy and metadata.json
- Retrieval: nearest-neighbors (cosine) via sklearn NearestNeighbors; top-K results are deduped and truncated before being sent to the LLM

Prompting rules (server)
- The server builds a short prompt containing the user's question and the retrieved excerpts (each truncated to a safe length). The prompt instructs the model to answer using only the provided excerpts and to include citations.
- The server returns both raw model output and a formatted_html version (the UI sanitizes this before rendering).

Costs and safety
- Building the index calls the Embeddings API and may be expensive for large corpora. The UI asks for confirmation before building.
- Generation also costs tokens. Choose an appropriate model for your needs. The UI can query GET /openai-models to populate the model dropdown for bot creation.
- The UI sanitizes HTML returned from the server to reduce XSS risk.

Troubleshooting
- If /chat-policy returns index_not_built: run POST /index-policies (the UI provides a Build Index button).
- If responses include "{}" or empty sources, check data/openai_responses: some saved responses may be empty or malformed and should be re-generated or removed.
- If the bot returns long concatenated excerpts rather than a short answer, the server will truncate excerpts; consider tweaking the prompt in api/app/services/policy_rag.py or limiting top_k.

Developer notes
- Code locations:
  - Backend: api/app/services/policy_rag.py (indexing + generate_answer)
  - Backend routers: api/app/routers/policy_chat.py (chat + index endpoints), api/app/routers/bots.py
  - Frontend: web/src/app/app.component.ts (UI wiring for parse, bots, policy chat, index build)
- Data persistence: data/vector_store/ contains embeddings and metadata, data/bots/ contains bot chunks, data/openai_responses/ has saved model outputs.

Recommended future improvements
- Stream index build progress or provide a status endpoint so the UI can poll progress.
- Require the model to return a short structured JSON answer plus citation array — this will make UI rendering deterministic and avoid fragmentary quoting.
- Replace innerHTML with structured components or pre-sanitized fragments to avoid needing bypassSecurityTrustHtml.
