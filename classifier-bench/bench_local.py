import json
import pickle
import resource
import time

import numpy as np
import scipy.sparse as sp
from fastembed import TextEmbedding

d = pickle.load(open("/app/combined.pkl", "rb"))
tf, clf = d["tfidf"], d["clf"]
texts = json.load(open("/app/inputs.json"))
emb = TextEmbedding("BAAI/bge-base-en-v1.5", cache_dir="/models", threads=1)


def predict(t):
    e = np.array(list(emb.embed([t])), dtype=np.float32)
    e = e / np.linalg.norm(e, axis=1, keepdims=True)
    return clf.predict(sp.hstack([tf.transform([t]), sp.csr_matrix(e)]).tocsr())[0]


predict(texts[0])  # warm-up, not timed
lat = []
t0 = time.perf_counter()
for t in texts:
    s = time.perf_counter()
    predict(t)
    lat.append((time.perf_counter() - s) * 1000)
lat.sort()
print(
    f"messages {len(texts)}  p50 {lat[len(lat) // 2]:.0f} ms  p95 {lat[int(len(lat) * 0.95)]:.0f} ms  max {lat[-1]:.0f} ms  total {time.perf_counter() - t0:.0f} s"
)
print(f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")
