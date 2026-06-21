"""
HeyDoc — one-time local script to produce INT8-quantized ONNX versions of
the embedder and reranker, and push them to Hugging Face Hub.

Run once by hand: python scripts/quantize_models.py
Never executed by the deployed app — server.py/ingestion.py/retrieval.py
only ever *load* the resulting Hub repos when THEARCH_QUANTIZED=1.
"""
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from huggingface_hub import login, whoami, create_repo, upload_folder
from sentence_transformers import SentenceTransformer, CrossEncoder
from sentence_transformers.backend import export_dynamic_quantized_onnx_model

login(token=os.environ["HF_TOKEN"])
username = whoami()["name"]

EMBEDDER_REPO = f"{username}/bge-large-en-v1.5-int8-onnx"
RERANKER_REPO = f"{username}/bge-reranker-v2-m3-int8-onnx"


def quantize_and_push(model_cls, source_model_name, repo_id):
    # push_to_hub=True assumes the repo already exists -- create it first.
    create_repo(repo_id, exist_ok=True)

    print(f"Quantizing {source_model_name} -> {repo_id}")
    onnx_model = model_cls(source_model_name, backend="onnx")
    export_dynamic_quantized_onnx_model(onnx_model, "avx2", repo_id, push_to_hub=True, file_suffix="int8")

    # export_dynamic_quantized_onnx_model only pushes the ONNX artifact --
    # the repo needs config/tokenizer files too to be loadable standalone.
    # Re-load normally (no backend="onnx") to get the plain HF save layout,
    # strip the FP32 weight files, and push just the small supporting files
    # alongside the ONNX file already on the hub.
    print("  pushing supporting config/tokenizer files...")
    plain_model = model_cls(source_model_name)
    with tempfile.TemporaryDirectory() as tmp:
        plain_model.save_pretrained(tmp)
        for pattern in ["*.bin", "*.safetensors"]:
            for f in Path(tmp).rglob(pattern):
                f.unlink()
        upload_folder(repo_id=repo_id, folder_path=tmp, commit_message="Add config/tokenizer files")
    print("  done")


quantize_and_push(SentenceTransformer, "BAAI/bge-large-en-v1.5", EMBEDDER_REPO)
quantize_and_push(CrossEncoder, "BAAI/bge-reranker-v2-m3", RERANKER_REPO)

print()
print("Pushed:")
print(" ", EMBEDDER_REPO)
print(" ", RERANKER_REPO)
