# File: models/conversation.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON
from sqlalchemy.sql import func
from utils.db import Base

class ConversationHistory(Base):
    """Store conversation history for context and learning"""
    __tablename__ = "conversation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), index=True, nullable=False)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    context = Column(JSON, default={})
    intent = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    session_id = Column(String(100), nullable=True)

class UserPreferences(Base):
    """Store user preferences and learned communication patterns"""
    __tablename__ = "user_preferences"
    
    user_id = Column(String(50), primary_key=True, index=True)
    settings = Column(JSON, default={})
    learned_patterns = Column(JSON, default={})
    service_weights = Column(JSON, default={})
    communication_style = Column(String(20), default="enthusiastic")
    preferred_response_length = Column(String(10), default="medium")
    last_updated = Column(DateTime(timezone=True), server_default=func.now())