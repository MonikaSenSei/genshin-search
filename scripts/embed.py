#!/usr/bin/env python3
"""Shared local embedding (bge-small-zh-v1.5 ONNX). Run with .venv/bin/python."""
import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(os.path.dirname(HERE), "models")
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_tok = None
_sess = None


def _lazy():
    global _tok, _sess
    if _tok is None:
        _tok = Tokenizer.from_file(os.path.join(MODELS, "tokenizer.json"))
        _tok.enable_truncation(max_length=256)
        _tok.enable_padding(pad_id=0, pad_token="[PAD]")
        _sess = ort.InferenceSession(
            os.path.join(MODELS, "model.onnx"),
            providers=[("CPUExecutionProvider",
                        {"intra_op_num_threads": 12})])
    return _tok, _sess


def encode_texts(texts):
    """Encode a batch -> L2-normalized float32 matrix (bge dense retrieval)."""
    tok, sess = _lazy()
    enc = tok.encode_batch(list(texts))
    ids = np.stack([e.ids for e in enc]).astype("int64")
    mask = np.stack([e.attention_mask for e in enc]).astype("int64")
    out = sess.run(["sentence_embedding"],
                   {"input_ids": ids, "attention_mask": mask,
                    "token_type_ids": np.zeros_like(ids)})[0]
    return (out / np.linalg.norm(out, axis=1, keepdims=True)).astype(np.float32)
