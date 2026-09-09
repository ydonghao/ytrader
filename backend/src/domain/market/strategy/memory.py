"""
FinancialSituationMemory
========================
Memory system for storing and retrieving past trading decisions
and their outcomes. Uses vector embeddings for similarity search.
"""
from typing import Any

try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


class FinancialSituationMemory:
    """
    Memory system for financial situations and trading advice.
    
    Uses vector embeddings to find similar past situations and
    their corresponding recommendations.
    
    Args:
        name: Name of the memory collection
        config: Configuration dict with 'backend_url' for LLM API
    """
    
    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        
        backend_url = config.get("backend_url", "http://localhost:11434/v1")
        
        # Determine embedding model based on backend
        if "localhost" in backend_url or "11434" in backend_url:
            self.embedding_model = "nomic-embed-text"
        else:
            self.embedding_model = "text-embedding-3-small"
        
        self._client: OpenAI | None = None
        self._chroma_client: Any | None = None
        self._collection: Any | None = None
        
        if _OPENAI_AVAILABLE:
            self._client = OpenAI(base_url=backend_url)
        
        if _CHROMA_AVAILABLE:
            self._chroma_client = chromadb.Client(Settings(allow_reset=True))
            self._collection = self._chroma_client.create_collection(name=name)
    
    def get_embedding(self, text: str) -> list[float]:
        """
        Get vector embedding for text.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        if self._client is None:
            # Return dummy embedding if client not available
            return [0.0] * 768
        
        try:
            response = self._client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception:
            # Return dummy embedding on failure
            return [0.0] * 768
    
    def add_situations(self, situations_and_advice: list[tuple[str, str]]) -> None:
        """
        Add financial situations and their corresponding advice.
        
        Args:
            situations_and_advice: List of (situation, recommendation) tuples
        """
        if self._collection is None:
            return
        
        situations = []
        advice = []
        ids = []
        embeddings = []
        
        offset = self._collection.count()
        
        for i, (situation, recommendation) in enumerate(situations_and_advice):
            situations.append(situation)
            advice.append(recommendation)
            ids.append(str(offset + i))
            embeddings.append(self.get_embedding(situation))
        
        self._collection.add(
            documents=situations,
            metadatas=[{"recommendation": rec} for rec in advice],
            embeddings=embeddings,
            ids=ids,
        )
    
    def get_memories(
        self,
        current_situation: str,
        n_matches: int = 1
    ) -> list[dict[str, Any]]:
        """
        Find matching recommendations using embeddings.
        
        Args:
            current_situation: Current market situation description
            n_matches: Number of similar situations to retrieve
            
        Returns:
            List of dicts with matched_situation, recommendation, similarity_score
        """
        if self._collection is None:
            return []
        
        query_embedding = self.get_embedding(current_situation)
        
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n_matches,
            include=["metadatas", "documents", "distances"],
        )
        
        matched_results = []
        if results["documents"] and results["metadatas"]:
            for i in range(len(results["documents"][0])):
                matched_results.append({
                    "matched_situation": results["documents"][0][i],
                    "recommendation": results["metadatas"][0][i]["recommendation"],
                    "similarity_score": 1 - results["distances"][0][i],
                })
        
        return matched_results
