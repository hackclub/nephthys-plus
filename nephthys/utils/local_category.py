# Optional local category tagger, used before the hosted decision model.
#
# Enabled only when LOCAL_CATEGORY_MODEL_PATH points at a trained model file
# (a pickle holding a fitted TF-IDF union and logistic regression, trained on
# TF-IDF features plus fastembed bge-base-en-v1.5 embeddings). It is used only
# when the deployment's category tag names exactly match the labels the model
# was trained on, and only when its top probability reaches the threshold.
# Otherwise callers fall back to the hosted model.
#
# Install the extra first: `uv sync --extra local-classifier`.
# Only load a model file you trust: pickle runs code on load.
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

EMBED_MODEL = "BAAI/bge-base-en-v1.5"


DEFAULT_THRESHOLD = 0.40


def _threshold() -> float:
    raw = os.environ.get("LOCAL_CATEGORY_THRESHOLD")
    if raw is None:
        return DEFAULT_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        logging.error(
            f"Invalid LOCAL_CATEGORY_THRESHOLD={raw!r}; using {DEFAULT_THRESHOLD}"
        )
        return DEFAULT_THRESHOLD


@dataclass
class _Loaded:
    labels: frozenset[str]
    tfidf: Any
    clf: Any
    embedder: Any
    threshold: float


_loaded: _Loaded | None = None
_load_failed = False


def _load() -> _Loaded | None:
    global _loaded, _load_failed
    if _loaded is not None or _load_failed:
        return _loaded
    path = os.environ.get("LOCAL_CATEGORY_MODEL_PATH")
    if not path:
        _load_failed = True
        return None
    try:
        import pickle

        import numpy as np  # noqa: F401  (needed by the pickled estimators)
        import scipy.sparse  # pyright: ignore[reportMissingImports]  # noqa: F401
        from fastembed import TextEmbedding  # pyright: ignore[reportMissingImports]

        with open(path, "rb") as f:
            saved = pickle.load(f)
        embedder = TextEmbedding(
            EMBED_MODEL,
            cache_dir=os.environ.get("LOCAL_CATEGORY_EMBED_CACHE") or None,
            threads=1,
        )
        _loaded = _Loaded(
            labels=frozenset(saved["clf"].classes_),
            tfidf=saved["tfidf"],
            clf=saved["clf"],
            embedder=embedder,
            threshold=_threshold(),
        )
        logging.info(f"Loaded local category model from {path}")
    except Exception:
        logging.error("Failed to load local category model", exc_info=True)
        _load_failed = True
    return _loaded


def _predict(model: _Loaded, text: str) -> tuple[str, float]:
    import numpy as np
    import scipy.sparse as sp  # pyright: ignore[reportMissingImports]

    emb = np.array(list(model.embedder.embed([text])), dtype=np.float32)
    emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    x = sp.hstack([model.tfidf.transform([text]), sp.csr_matrix(emb)]).tocsr()
    probs = model.clf.predict_proba(x)[0]
    top = int(probs.argmax())
    return str(model.clf.classes_[top]), float(probs[top])


async def local_category_name(text: str, tag_names: list[str]) -> str | None:
    """Return the chosen tag name, or None to fall back to the hosted model."""
    model = await asyncio.to_thread(_load)
    if model is None or frozenset(tag_names) != model.labels:
        return None
    try:
        label, confidence = await asyncio.to_thread(_predict, model, text)
    except Exception:
        logging.error("Local category prediction failed", exc_info=True)
        return None
    if confidence < model.threshold:
        return None
    return label
