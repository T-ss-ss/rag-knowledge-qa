from openai import OpenAI

from app.config import settings
from app.utils.exceptions import EmbeddingAPIError


class EmbeddingService:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
        self.model = settings.embedding_model
        self.batch_size = settings.embedding_batch_size

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                )
            except Exception as e:
                raise EmbeddingAPIError(
                    f"Embedding API call failed (batch {i // self.batch_size + 1}): {e}"
                ) from e
            all_embeddings.extend(d.embedding for d in response.data)
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=[text],
            )
        except Exception as e:
            raise EmbeddingAPIError(f"Embedding API call failed: {e}") from e
        return response.data[0].embedding
