"""RAG / knowledge base — §10.2 capability domain 3 (MILESTONE_L_PLAN.md).

Control-plane half only: a `KnowledgeBase` + a `Retriever` protocol with a stdlib
BM25 fallback. A real embedding store / RAG framework (§16: RAGFlow, LlamaIndex,
Haystack) slots in behind `Retriever`. KB content is `doc_input` trust.
"""
