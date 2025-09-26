# API Spec (contract-first for code-gen)

## POST /generate-synth
Body: `{ "rows": int, "seed"?: int }`
200: `{ "path": "string", "preview": [ {...10 rows...} ] }`

## POST /parse-policy
Multipart file `policy` OR `{ "text": string }`
200: `{"rules":[{ "name":str, "description":str, "condition":str, "threshold":number, "unit":str, "category":str, "scope":str, "applies_when":str, "violation_message":str }], "version":"1.0", "source":"string"}`

## POST /train
Body: `{ "algo": "isoforest"|"rf", "max_rows"?: int }`
200: `{ "algo": str, "fit_seconds": float, "features": [str] }`

## POST /score
Body: `{ "dataset_path": str, "rules_json"?: object }`
200: `[ { "txn_id": str, "amount": number, "category": str, "fraud_score": number,
         "policy": { "compliant": bool, "violated_rules": [str], "reason": str } } ]`

## GET /healthz
200: `{ "status": "ok" }`