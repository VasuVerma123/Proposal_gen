"""
OpenAI embedding helper — text-embedding-3-small (1536 dims).
"""

import os
from openai import OpenAI


def get_embeddings(texts: list[str], api_key: str | None = None) -> list[list[float]]:
    """Return embedding vectors for a list of text strings."""
    key = api_key or os.getenv("OPENAI_API_KEY", "")
    client = OpenAI(api_key=key)
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


def get_embedding(text: str, api_key: str | None = None) -> list[float]:
    """Return a single embedding vector."""
    return get_embeddings([text], api_key)[0]
