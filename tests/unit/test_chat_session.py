"""Unit tests for chat session management in AgentDeepDive CLI."""

import os
import json
import pytest
from pathlib import Path
from src.cli.chat.session import ChatSession, HISTORY_DIR

def test_chat_session_init():
    session = ChatSession(model="test-model", tenant_id="tenant-123", max_context_tokens=1000)
    assert session.model == "test-model"
    assert session.tenant_id == "tenant-123"
    assert session.max_context_tokens == 1000
    assert len(session.messages) == 1
    assert session.messages[0]["role"] == "system"

def test_chat_session_add_messages():
    session = ChatSession(max_context_tokens=2000)
    session.add_user_message("Hello")
    session.add_assistant_message("Hi there")
    
    assert len(session.messages) == 3
    assert session.messages[1] == {"role": "user", "content": "Hello"}
    assert session.messages[2] == {"role": "assistant", "content": "Hi there"}

def test_chat_session_clear():
    session = ChatSession()
    session.add_user_message("Hello")
    session.clear()
    
    assert len(session.messages) == 1
    assert session.messages[0]["role"] == "system"

def test_chat_session_estimate_tokens():
    session = ChatSession()
    # Completely empty the message list to isolate token estimation
    session.messages = []
    session.add_user_message("Hello world of testing")
    # "Hello world of testing" is 23 characters, 23 // 4 = 5 tokens
    assert session.estimate_tokens() == 5

def test_chat_session_truncation():
    # Set a max token size that is just slightly larger than the new system prompt (70 tokens)
    session = ChatSession(max_context_tokens=74)
    
    # 20 chars -> 5 tokens. Total = 70 + 5 = 75 (exceeds 74)
    session.add_user_message("12345678901234567890")
    
    # The user message is retained because it is the only message besides the system prompt
    assert len(session.messages) == 2
    assert session.messages[0]["role"] == "system"
    assert session.messages[1]["role"] == "user"
    
    # Now add another which pushes it over: 24 chars -> 6 tokens.
    session.add_assistant_message("abcdefghijklmnopqrstuvwx")
    
    # It should have truncated the oldest user message (index 1), leaving system prompt (index 0) and assistant response (index 1)
    assert len(session.messages) == 2
    assert session.messages[0]["role"] == "system"
    assert session.messages[1]["role"] == "assistant"

def test_chat_session_role_aware_truncation():
    # Primary system prompt (70 tokens) + role system prompt (20 chars -> 5 tokens) = 75 tokens.
    # We set max_context_tokens to 80.
    session = ChatSession(max_context_tokens=80)
    
    # Add a system message defining a role instruction
    session.messages.append({"role": "system", "content": "You are a senior coder"})
    
    # Add a user message (24 chars -> 6 tokens). Total = 75 + 6 = 81 tokens
    session.add_user_message("abcdefghijklmnopqrstuvwx")
    assert len(session.messages) == 3
    
    # Add another user message (24 chars -> 6 tokens). Total = 75 + 6 + 6 = 87 tokens (exceeds 80)
    # The oldest user message should be truncated, but both system prompts should be preserved!
    session.add_user_message("123456789012345678901234")
    
    assert len(session.messages) == 3
    assert session.messages[0]["role"] == "system"  # Primary system prompt
    assert session.messages[1]["role"] == "system"  # Role instruction system prompt
    assert session.messages[2]["role"] == "user"    # Latest user message
    assert session.messages[2]["content"] == "123456789012345678901234"

def test_chat_session_save_load(tmp_path):
    # Override HISTORY_DIR for testing
    import src.cli.chat.session
    original_history_dir = src.cli.chat.session.HISTORY_DIR
    src.cli.chat.session.HISTORY_DIR = tmp_path
    
    try:
        session = ChatSession(model="gpt-test", tenant_id="tenant-xyz")
        session.add_user_message("Test message")
        
        filepath = session.save_to_disk("test_save")
        assert filepath.exists()
        
        # Load in another session
        session2 = ChatSession()
        loaded = session2.load_from_disk(filepath)
        
        assert loaded is True
        assert session2.model == "gpt-test"
        assert session2.tenant_id == "tenant-xyz"
        assert len(session2.messages) == 2
        assert session2.messages[1]["content"] == "Test message"
        
    finally:
        src.cli.chat.session.HISTORY_DIR = original_history_dir
