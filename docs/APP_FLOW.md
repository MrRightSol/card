# Application flow: policy -> chatbot -> ML anomaly detection

This document describes the end-to-end flow the application aims to implement, maps that flow to the current codebase, and enumerates what is implemented today vs. what remains to be done. A simple ASCII diagram is included to illustrate components and data movement.

## Overview (intended flow)
1. Generate dataset (DB or synthetic) of transactions.
2. Load an expense policy file (PDF/DOCX/TXT/JSON) into the app.
3. Parse the policy text via an LLM (or heuristic parser) to produce a structured JSON representation of rules/policies.
4. Create a chatbot based on the parsed policy: chunk/tokenize the policy, compute embeddings, persist metadata and embeddings.
5. Chat with the LLM using retrieval-augmented prompts: for each question, compute query embedding, retrieve top-k chunks, send a prompt (system + user) to the chat model and parse JSON output.
6. Generate and persist transaction features (or load transactions from DB), train an ML model (e.g., Isolation Forest) on the historical data to detect anomalies or out-of-policy transactions.
7. Use the trained ML model to classify new transactions and flag potential fraud / out-of-policy deviations per transaction.

## Current implementation status

### Step 1 — Generate dataset
- Implemented: `api/app/services/synth_gen.py` provides `generate_synth(rows, seed)` that generates a CSV of synthetic transactions and persists it into `data/synth` (or `DATA_DIR`). The trainer uses `set_last_dataset_path` to capture the last generated file.

### Step 2 — Load expense policy file
- Implemented: `api/app/routers/bots.py` (`create_bot`) supports uploading text or base64-encoded files, accepts `source_filename`, PDF/DOCX/TXT handling and falls back to asking OpenAI to extract text for small files when extraction libraries are not present.
- Relevant code: `api/app/services/policy_parser.py` (`parse_policy_file`) handles docx/pdf/text and delegates to text parsers.

### Step 3 — Parse policy via LLM
- Implemented (hybrid): `api/app/services/policy_parser.py` implements a heuristic parser and an OpenAI-backed parser (`parse_policy_text`). Behavior:
  - Default is heuristic first, then OpenAI fallback. You can prefer openai by passing `prefer='openai'` or by setting environment variables (`OPENAI_API_KEY`, `USE_OPENAI`).
  - `parse_policy_text` attempts to call OpenAI and normalize the returned JSON into a rules list.

### Step 4 — Create chatbot based on parsed policies
- Implemented (MVP): `api/app/routers/bots.py/_create_bot_from_body`
  - Chunks long policy text into ~1000 character chunks and persists `chunks.json` and `bot.json` into `data/bots/<bot_id>/`
  - Pre-computes embeddings at create-time (if `OPENAI_API_KEY` present) and persists `embeddings.npy` or `embeddings.json`.
  - Creates metadata (`model`/`embed_model`/`k`) in `bot.json`.

### Step 5 — Chat using retrieval + LLM
- Implemented (MVP): `api/app/routers/bots.py/chat_bot`
  - Loads chunks and precomputed embeddings (or computes them on-demand), computes query embedding, finds top-k similar chunks, builds a prompt with labeled excerpts and calls the model.
  - The code uses a compatibility wrapper (`api/app/services/model_caps.py` `send_model_request`) and falls back to `client.chat.completions.create`.
  - The chat path parses JSON returned by the model (or extracts `function_call` arguments) and returns a structured object with `answer`, `reasoning`, `references`, `needs`, and `sources` (chunk indices).

### Step 6 — Train ML model (Isolation Forest or similar)
- Partially implemented: `api/app/services/trainer.py` and `api/app/routers/train.py`
  - There is a `train` endpoint (`/train`) and a trainer module that currently:
    - loads a CSV dataset (synth or provided via `set_last_dataset_path`)
    - computes a very simple statistical model (mean/std) as a placeholder
    - registers that simple model in an in-memory registry and returns metadata
  - The code includes a generator (`synth_gen`) and logging hooks so you can run a training flow, but a real `IsolationForest` training using sklearn (fit/persist) is not yet implemented.

### Step 7 — Classify transactions (fraud / out-of-policy)
- Not implemented / Pending
  - There is no endpoint that accepts a transaction and returns a classification (anomaly score / out-of-policy verdict) based on both the parsed policies and the trained ML model.
  - There is no persistent model storage (beyond an in-memory registry inside `trainer.py`) nor a standard predict API.

## Files and endpoints (quick reference)
- Upload/parse policy: `api/app/services/policy_parser.py` (`parse_policy_file`, `parse_policy_text`)
- Create bot (policy -> chunks -> embeddings): POST `/bots`  (`api/app/routers/bots.py`)
- List bots: GET `/bots`
- Chat with bot: POST `/bots/{bot_id}/chat`
- Generate synthetic transactions: `api/app/services/synth_gen.generate_synth` (also used by trainer)
- Train model: POST `/train` (`api/app/routers/train.py`) -> `api/app/services/trainer.train_model` (placeholder)

## Pending / recommended work (short-term roadmap)
1. **Isolation Forest implementation**
   - Replace the simple mean/std placeholder with a real `IsolationForest` (scikit-learn) pipeline.
   - Persist trained models (`joblib`/`pickle`) under `data/models/<model-name>.pkl` and record metadata (training time, rows, features) in a small registry file.

2. **Prediction API**
   - Add an endpoint `POST /predict` that accepts a transaction (or batch) and returns:
     - ML anomaly score (e.g., isolation score)
     - Policy evaluation result (run the parsed rules/conditions against the transaction)
     - Final combined verdict (e.g., `out_of_policy`: true/false, `why`: reasoning)

3. **Policy rule engine**
   - Implement a small evaluation engine that can take the parsed JSON rules and safely evaluate them against a transaction (the `policy_parser` already emits simple `condition` strings; use a sandboxed expression evaluator rather than raw `eval`).

4. **Improve ML feature engineering**
   - Current trainer only reads `amount` and `timestamp`. Extend featurization to include categorical encodings (merchant, city, category, channel), time features, employee profiles, aggregated history, and one-hot / embedding encodings where appropriate.

5. **UI / results linking**
   - The chat endpoint now returns `chunk_index` in `sources`; the UI should show the excerpt and link the user to the exact policy text. Optionally return snippet text in `sources` for convenience.

6. **Tests and validation**
   - Add unit tests for policy parsing, retrieval correctness, and trainer/predictor behavior.

## ASCII diagram (high level)

```
  +-----------------+      (1) upload policy file      +--------------------+
  |  Frontend / UI  |  ------------------------------> |  API: /bots (POST)  |
  +-----------------+                                 +--------------------+
                                                           | (parse file)
                                                           v
                                                  +--------------------------+
                                                  | policy_parser.parse_*    |
                                                  +--------------------------+
                                                           | (structured JSON rules)
                                                           v
  +-----------------+      (2) create bot/chunks        +--------------------------+
  |  Frontend / UI  |  ------------------------------> |  api/app/routers/bots.py |
  +-----------------+                                 +--------------------------+
                                                           | (chunk, embed)
                                                           v
                                                  +--------------------------+
                                                  | data/bots/<bot_id>/      |
                                                  |  - bot.json              |
                                                  |  - chunks.json           |
                                                  |  - embeddings.npy/json   |
                                                  +--------------------------+

  Chat flow (query):
  User -> POST /bots/<bot_id>/chat -> compute query embedding -> retrieve top-k chunks -> build prompt (system + labeled excerpts) -> model -> parse JSON -> return structured answer + sources

  ML training / predictions:
  generate_synth() -> CSV dataset -> POST /train -> trainer.train_model (fit) -> persist model (pending)
  Later: POST /predict -> load model -> featurize -> score -> optionally run policy-rule engine -> return verdict
```

## Summary
- The repository already implements most of the data flow from policy ingestion -> parsed JSON -> bot creation -> retrieval-based chat.
- The ML/anomaly detection pieces are present as prototypes (synth data generator, train endpoint, basic trainer scaffold) but require a concrete `IsolationForest` training/persistence, richer featurization, and a prediction API to be fully usable for fraud/out-of-policy classification.

If you want, I can now:
- Implement a production-ready `IsolationForest` training/persistence and add a `POST /predict` endpoint (I can base it on scikit-learn and joblib), or
- Add a small policy-rule evaluator and prediction endpoint that combines rule-based and ML signals, or
- Produce a Mermaid diagram (text) you can paste into docs or render in the UI.
