# 3-Min Demo Script
1) Open UI → click "Generate Data" (toast: 100k txns).
2) Upload policy.pdf → preview rules JSON.
3) Train model (IsolationForest, capped rows).
4) Run scoring → table fills with red/yellow/green.
5) Click a red row → explanation panel (violated rule + anomaly features).