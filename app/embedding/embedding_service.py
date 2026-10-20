from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config.settings import settings


class EmbeddingService:
    """
    SentenceTransformer embedding service.

    Model:
        BAAI/bge-small-zh-v1.5

    Dimension:
        512

    Embeddings:
        normalized FLOAT32 vectors

    Loading strategy:
        1. Prefer the local Hugging Face cache.
        2. Avoid unnecessary network HEAD requests.
        3. Load lazily on first encode().
    """

    MODEL_NAME = "BAAI/bge-small-zh-v1.5"

    EMBEDDING_DIMENSION = 512

    def __init__(
        self,
        model_name: str = MODEL_NAME,
    ) -> None:

        self.model_name = model_name

        self.model: SentenceTransformer | None = None

        self._load_lock = threading.Lock()

        self.dimension = self.EMBEDDING_DIMENSION


    # ==========================================================
    # Model loading
    # ==========================================================

    def _cached_model_path(self) -> str | None:
        """Return the pinned local snapshot when it is already downloaded."""
        explicit_path = str(settings.embedding_model_path or "").strip()
        if explicit_path and (Path(explicit_path) / "config.json").is_file():
            return explicit_path
        cache_root = Path(
            settings.embedding_cache_dir
            or os.environ.get(
                "HF_HUB_CACHE",
                Path.home() / ".cache" / "huggingface" / "hub",
            )
        )
        repo_dir = cache_root / (
            "models--" + self.model_name.replace("/", "--")
        )
        ref_file = repo_dir / "refs" / "main"
        revision = (
            ref_file.read_text(encoding="utf-8").strip()
            if ref_file.is_file()
            else ""
        )
        snapshot = repo_dir / "snapshots" / revision
        if not revision:
            snapshots = sorted(
                (repo_dir / "snapshots").glob("*"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            snapshot = snapshots[0] if snapshots else snapshot
        if not (snapshot / "config.json").is_file():
            return None
        return str(snapshot)

    def _load_model(self) -> None:

        if self.model is not None:
            return


        # Prevent Hugging Face from trying to contact
        # the Hub for metadata that may already be cached.
        #
        # This is especially useful on machines where
        # Hugging Face HTTPS requests fail but the model
        # files are already available locally.

        previous_offline_value = os.environ.get(
            "HF_HUB_OFFLINE"
        )

        os.environ["HF_HUB_OFFLINE"] = "1"


        try:

            local_path = self._cached_model_path()
            if settings.production_mode and settings.embedding_model_local_only and not local_path:
                raise RuntimeError(
                    "Embedding model is not bundled locally; configure EMBEDDING_MODEL_PATH or EMBEDDING_CACHE_DIR"
                )
            self.model = SentenceTransformer(
                local_path or self.model_name,
                local_files_only=bool(settings.embedding_model_local_only or local_path),
            )

        except Exception as local_exc:

            # Restore the previous environment value
            # before trying the normal online loader.

            if previous_offline_value is None:

                os.environ.pop(
                    "HF_HUB_OFFLINE",
                    None,
                )

            else:

                os.environ["HF_HUB_OFFLINE"] = (
                    previous_offline_value
                )


            if settings.embedding_model_local_only:
                raise RuntimeError(
                    "Embedding model is not available in the configured local cache"
                ) from local_exc

            try:

                self.model = SentenceTransformer(
                    self.model_name
                )

            except Exception as remote_exc:

                raise RuntimeError(
                    "Failed to load embedding model "
                    f"'{self.model_name}'. "
                    "The model is not fully available in "
                    "the local Hugging Face cache and the "
                    "Hugging Face Hub request also failed. "
                    f"Local error: {local_exc}; "
                    f"Remote error: {remote_exc}"
                ) from remote_exc

        finally:

            if previous_offline_value is None:

                os.environ.pop(
                    "HF_HUB_OFFLINE",
                    None,
                )

            else:

                os.environ["HF_HUB_OFFLINE"] = (
                    previous_offline_value
                )


        dimension = (
            self.model.get_embedding_dimension()
        )


        if dimension != self.EMBEDDING_DIMENSION:

            self.model = None

            raise ValueError(
                "Embedding dimension mismatch: "
                f"expected "
                f"{self.EMBEDDING_DIMENSION}, "
                f"got {dimension}"
            )


        self.dimension = dimension

    def ensure_ready(self) -> None:
        """Load the model once so readiness checks can verify local availability."""
        if self.model is not None:
            return
        with self._load_lock:
            if self.model is None:
                self._load_model()

    @property
    def is_ready(self) -> bool:
        """Whether the model has been loaded successfully in this process."""
        return self.model is not None


    # ==========================================================
    # Encode
    # ==========================================================

    def encode(
        self,
        text: str,
    ) -> List[float]:
        """
        Generate a normalized 512-dimensional embedding.
        """

        if not isinstance(
            text,
            str,
        ):

            raise TypeError(
                "text must be a string"
            )


        text = text.strip()


        if not text:

            return []


        self.ensure_ready()


        vector = self.model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )


        vector = np.asarray(
            vector,
            dtype=np.float32,
        )


        if vector.ndim != 1:

            vector = vector.reshape(-1)


        if len(vector) != self.dimension:

            raise ValueError(
                "Unexpected embedding dimension: "
                f"expected {self.dimension}, "
                f"got {len(vector)}"
            )


        return vector.tolist()


    # ==========================================================
    # Similarity
    # ==========================================================

    def similarity(
        self,
        a,
        b,
    ) -> float:

        if not a or not b:

            return 0.0


        if len(a) != len(b):

            return 0.0


        a_array = np.asarray(
            a,
            dtype=np.float32,
        )


        b_array = np.asarray(
            b,
            dtype=np.float32,
        )


        similarity = float(
            np.dot(
                a_array,
                b_array,
            )
        )


        return max(
            -1.0,
            min(
                1.0,
                similarity,
            )
        )
