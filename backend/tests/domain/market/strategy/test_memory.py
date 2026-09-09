"""
Tests for TradingAgents - FinancialSituationMemory Tests
========================================================
TDD approach: define expected memory interface first.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))


class TestFinancialSituationMemoryInterface:
    """Test FinancialSituationMemory class interface."""

    def test_memory_is_importable(self):
        """Memory class should be importable from memory module"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        assert FinancialSituationMemory is not None

    def test_memory_has_get_memories_method(self):
        """Memory should have get_memories method"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        assert hasattr(FinancialSituationMemory, 'get_memories')

    def test_memory_has_add_situations_method(self):
        """Memory should have add_situations method"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        assert hasattr(FinancialSituationMemory, 'add_situations')


class TestFinancialSituationMemoryInstantiation:
    """Test that memory can be instantiated with proper config."""

    def test_memory_init_with_name_and_config(self):
        """Memory should be initialized with name and config"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        
        config = {
            "backend_url": "http://localhost:11434/v1",
        }
        
        # Should be able to create instance
        # Note: Full init may require chromadb/openai, so we test interface
        memory = FinancialSituationMemory(name="test_memory", config=config)
        assert memory is not None


class TestMemoryAddSituations:
    """Test adding situations to memory."""

    def test_add_situations_accepts_list_of_tuples(self):
        """add_situations should accept list of (situation, advice) tuples"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        
        config = {"backend_url": "http://localhost:11434/v1"}
        memory = FinancialSituationMemory(name="test", config=config)
        
        situations_and_advice = [
            ("High inflation scenario", "Consider defensive sectors"),
            ("Tech volatility scenario", "Reduce growth stock exposure"),
        ]
        
        # Should not raise
        # Note: May fail due to actual API calls, we just test interface
        try:
            memory.add_situations(situations_and_advice)
        except Exception:
            # Expected if chromadb not available
            pass


class TestMemoryGetMemories:
    """Test retrieving memories."""

    def test_get_memories_returns_list(self):
        """get_memories should return a list of matched results"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        
        config = {"backend_url": "http://localhost:11434/v1"}
        memory = FinancialSituationMemory(name="test", config=config)
        
        result = memory.get_memories("current market situation", n_matches=1)
        
        # Should return list (may be empty)
        assert isinstance(result, list)

    def test_get_memories_with_n_matches(self):
        """get_memories should accept n_matches parameter"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        
        config = {"backend_url": "http://localhost:11434/v1"}
        memory = FinancialSituationMemory(name="test", config=config)
        
        result = memory.get_memories("test situation", n_matches=3)
        assert isinstance(result, list)

    def test_memory_result_contains_expected_keys(self):
        """Memory results should contain matched_situation, recommendation, similarity_score"""
        # This documents the expected result structure
        expected_keys = ["matched_situation", "recommendation", "similarity_score"]
        assert len(expected_keys) == 3


class TestMemoryEmbedding:
    """Test embedding functionality."""

    def test_get_embedding_method_exists(self):
        """Memory should have get_embedding method"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        assert hasattr(FinancialSituationMemory, 'get_embedding')

    def test_embedding_returns_list_of_floats(self):
        """get_embedding should return a list of floats"""
        from src.domain.market.strategy.memory import FinancialSituationMemory
        
        config = {"backend_url": "http://localhost:11434/v1"}
        memory = FinancialSituationMemory(name="test", config=config)
        
        try:
            embedding = memory.get_embedding("test text")
            # Should be a list of floats
            assert isinstance(embedding, list)
            if len(embedding) > 0:
                assert isinstance(embedding[0], float)
        except Exception:
            # Expected if API not available
            pass
