from app.config import settings
from app.services.document_service import get_embeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings


def test_get_embeddings_defaults_to_ollama(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    assert isinstance(get_embeddings(), OllamaEmbeddings)


def test_get_embeddings_supports_openai_compatible_provider(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "openai")
    monkeypatch.setattr(settings, "embed_openai_api_key", "test-key")
    assert isinstance(get_embeddings(), OpenAIEmbeddings)
