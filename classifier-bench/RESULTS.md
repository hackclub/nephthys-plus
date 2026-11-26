# Classifier container benchmark

Model: TF-IDF (word 1-2 grams + char 3-5 grams) + bge-base-en-v1.5 embeddings (run locally with fastembed) + logistic regression.

Accuracy (trained on 1,000 labelled messages; evaluated on 590 held-out messages):
- Set A, 90 hand-labelled messages: 83.3%
- Set B, 500 messages labelled by an LLM: 72.2%

Container (python:3.13-slim, `--cpus=1 --memory=2g`, `--network none`, `HF_HUB_OFFLINE=1`), 500 single-message predictions:
- p50 103 ms, p95 380 ms, max 1,723 ms
- peak RSS 491 MB

Reproduce: place the trained `combined.pkl`, the model cache at `models/`, and an `inputs.json` list of strings next to this folder, then:

    docker build -t classifier-bench .
    docker run --rm --network none --cpus=1 --memory=2g -e HF_HUB_OFFLINE=1 \
      -v "$PWD":/app -v "$PWD/models":/models -w /app classifier-bench python bench_local.py

Training data, labels and trained weights are not included in this repository.
