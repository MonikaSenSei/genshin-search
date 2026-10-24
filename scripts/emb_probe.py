#!/usr/bin/env python3
"""Smoke test for the local ONNX embedding (bge-small-zh-v1.5).
Run with .venv/bin/python."""
import numpy as np, onnxruntime as ort
from tokenizers import Tokenizer

M = "models"
tok = Tokenizer.from_file(f"{M}/tokenizer.json")
tok.enable_truncation(max_length=256)
tok.enable_padding(pad_id=0, pad_token="[PAD]")
sess = ort.InferenceSession(f"{M}/model.onnx",
                            providers=[("CPUExecutionProvider",
                                       {"inter_op_num_threads": 12,
                                        "intra_op_num_threads": 12})])

def encode(texts, prefix=""):
    texts = [prefix + t for t in texts]
    enc = tok.encode_batch(texts)
    ids = np.stack([e.ids for e in enc]).astype("int64")
    mask = np.stack([e.attention_mask for e in enc]).astype("int64")
    out = sess.run(["sentence_embedding"],
                   {"input_ids": ids, "attention_mask": mask,
                    "token_type_ids": np.zeros_like(ids)})[0]
    return out / np.linalg.norm(out, axis=1, keepdims=True)

q = "为这个句子生成表示以用于检索相关文章："
pairs = [
    ("法涅斯是谁", "【法涅斯，或者原初的那一位】彼时的僣主", "同主题"),
    ("法涅斯是谁", "至上的高天之主，有翼者，摧灭地上万国的凶王", "代称暗示"),
    ("法涅斯是谁", "今日委托已完成，去冒险家协会领取奖励吧。", "无关"),
]
qs = encode([p[0] for p in pairs], prefix=q)
ds = encode([p[1] for p in pairs])
for (a, b, why), x, y in zip(pairs, qs, ds):
    print(f"sim({why}) = {float(x @ y):.3f}   {a!r} vs {b!r}")
