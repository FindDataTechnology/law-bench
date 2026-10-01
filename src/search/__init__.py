"""Semantic search / RAG subsystem for the contract drafter.

Ingests contract documents from MinIO, embeds them via OpenRouter
(``nvidia/nemotron-3-embed-1b:free``, 2048-dim), stores vectors in Elasticsearch,
and serves retrieval through a LlamaIndex query engine - exposed as a
``/api/search`` JSON endpoint, a ``/search`` page, and a CrewAI retrieval tool.
"""
