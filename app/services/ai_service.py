# Updated on June 15, 2025: Standardized schemas, completed function implementations, improved error handling, resource management, configurable model, token loading robustness, context-aware follow-ups, and argument validation.
import asyncio
import json
import time
import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import openai
from sqlalchemy.orm import Session
from utils.db import SessionLocal
from utils.token_store import load_tokens

logger = logging.getLogger(__name__)

class ConversationContext:
    def __init__(self, user_id: str, messages: List[Dict], functions: List[Dict], preferences: Dict):
        self.user_id = user_id
        self.messages = messages
        self.functions = functions
        self.preferences = preferences

class EnhancedAIService:
    def __init__(self):
        # Initialize OpenAI client
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4-turbo")  # Configurable model with fallback
        self.max_context_messages = 10
    
    async def process_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """Process user message with enhanced AI capabilities"""
        try:
            # Get conversation context
            context = await self._build_context(user_id, message)
            
            # Generate AI response
            response = await self._generate_response(context)
            
            # Handle function calls if present
            function_results = []
            if response.get("tool_calls"):
                function_results = await self._execute_functions(user_id, response["tool_calls"])
            
            # Store conversation in database
            await self._store_conversation(user_id, message, response["content"], response.get("metadata", {}))
            
            return {
                "success": True,
                "response": response["content"],
                "function_results": function_results,
                "suggestions": self._generate_suggestions(context, response),
                "follow_up_questions": self._generate_follow_ups(context, response),
                "metadata": response.get("metadata", {})
            }
            
        except Exception as e:
            logger.error(f"Error processing message for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": "I'm having trouble processing your request right now. Please try again in a moment! 😊"
            }
    
    async def _build_context(self, user_id: str, current_message: str) -> ConversationContext:
        """Build conversation context with history and available functions"""
        
        # Get recent conversation history
        messages = await self._get_conversation_history(user_id)
        
        # Add system message for GPT-4
        system_message = {
            "role": "system",
            "content": """You are DATA-AI, an enthusiastic and helpful productivity assistant! 🚀

You help users with:
- Calendar management and scheduling  
- Email composition and search
- Notion page creation and organization
- Slack messaging and communication
- Zoom meeting creation
- Task automation and workflow optimization

Always be:
- Enthusiastic and positive! Use emojis appropriately 😊
- Helpful and actionable in your suggestions
- Proactive in offering relevant assistance
- Clear and conversational in your responses

When users ask about their services, check what they have connected and offer specific help based on their available integrations.

If you need to perform actions, use the available functions. Always confirm what you're doing and provide helpful context."""
        }
        
        # Insert system message at the beginning
        messages.insert(0, system_message)
        
        # Add current user message
        messages.append({"role": "user", "content": current_message})
        
        # Get available functions based on user's connected services
        functions = await self._get_available_functions(user_id)
        
        # Get user preferences
        preferences = await self._get_user_preferences(user_id)
        
        return ConversationContext(user_id, messages, functions, preferences)
    
    async def _generate_response(self, context: ConversationContext) -> Dict[str, Any]:
        """Generate AI response using OpenAI GPT-4"""
        try:
            start_time = time.time()
            
            # Prepare the request for OpenAI
            kwargs = {
                "model": self.model,
                "messages": context.messages,
                "max_tokens": 1500,
                "temperature": 0.3
            }
            
            # Add functions if available (OpenAI tools format)
            if context.functions:
                kwargs["tools"] = [{"type": "function", "function": func} for func in context.functions]
                kwargs["tool_choice"] = "auto"
            
            # Make API call
            response = await self.client.chat.completions.create(**kwargs)
            
            response_time = time.time() - start_time
            
            # Parse response
            message = response.choices[0].message
            content = message.content or ""
            
            # Handle tool calls
            tool_calls = []
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_calls.append({
                        "id": tool_call.id,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
            
            return {
                "content": content,
                "tool_calls": tool_calls,
                "metadata": {
                    "provider": "openai",
                    "model": self.model,
                    "response_time": response_time,
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "finish_reason": response.choices[0].finish_reason
                }
            }
            
        except Exception as e:
            logger.error(f"OpenAI API error for user {context.user_id}: {str(e)}")
            return {
                "content": "I'm having a small technical hiccup! 😅 Please try again in a moment.",
                "tool_calls": [],
                "metadata": {"error": str(e)}
            }
    
    async def _get_conversation_history(self, user_id: str) -> List[Dict[str, str]]:
        """Get recent conversation history for context"""
        try:
            from models.conversation import ConversationHistory
            
            with SessionLocal() as db:
                recent_conversations = db.query(ConversationHistory)\
                    .filter(ConversationHistory.user_id == user_id)\
                    .order_by(ConversationHistory.timestamp.desc())\
                    .limit(self.max_context_messages)\
                    .all()
                
                messages = []
                for conv in reversed(recent_conversations):
                    messages.append({"role": "user", "content": conv.message})
                    messages.append({"role": "assistant", "content": conv.response})
                
                return messages
                
        except Exception as e:
            logger.error(f"Error getting conversation history for user {user_id}: {str(e)}")
            return []
    
    async def _get_available_functions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get available functions based on user's connected services (OpenAI format)"""
        
        try:
            tokens = load_tokens(user_id)
        except Exception as e:
            logger.error(f"Error loading tokens for user {user_id}: {str(e)}")
            tokens = {}
        
        functions = []
        
        # Calendar functions (Google)
        if tokens.get("google"):
            functions.extend([
                {
                    "name": "get_calendar_events",
                    "description": "Get calendar events for a specific date range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string", 
                                "description": "Start date (YYYY-MM-DD), defaults to today"
                            },
                            "end_date": {
                                "type": "string", 
                                "description": "End date (YYYY-MM-DD), defaults to 7 days from start"
                            },
                            "event_type": {
                                "type": "string", 
                                "description": "Filter by event type (optional)"
                            }
                        }
                    }
                },
                {
                    "name": "create_calendar_event",
                    "description": "Create a new calendar event",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string", 
                                "description": "Event title/summary"
                            },
                            "start_time": {
                                "type": "string", 
                                "description": "Start time in ISO format (YYYY-MM-DDTHH:MM:SS)"
                            },
                            "duration": {
                                "type": "integer", 
                                "description": "Duration in minutes",
                                "default": 60
                            },
                            "description": {
                                "type": "string", 
                                "description": "Event description (optional)"
                            },
                            "location": {
                                "type": "string", 
                                "description": "Event location (optional)"
                            }
                        },
                        "required": ["summary", "start_time"]
                    }
                },
                {
                    "name": "compose_email",
                    "description": "Help compose or send an email",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string", 
                                "description": "Recipient email address"
                            },
                            "subject": {
                                "type": "string", 
                                "description": "Email subject"
                            },
                            "body": {
                                "type": "string", 
                                "description": "Email body content"
                            },
                            "action": {
                                "type": "string", 
                                "enum": ["draft", "send"], 
                                "description": "Whether to draft or send immediately"
                            }
                        },
                        "required": ["to", "subject", "body"]
                    }
                }
            ])
        
        # Notion functions
        if tokens.get("notion"):
            functions.extend([
                {
                    "name": "create_notion_page",
                    "description": "Create a new Notion page with content",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string", 
                                "description": "Page title"
                            },
                            "content": {
                                "type": "string", 
                                "description": "Page content/notes"
                            },
                            "parent_page_id": {
                                "type": "string", 
                                "description": "Parent page ID (optional)"
                            }
                        },
                        "required": ["title"]
                    }
                },
                {
                    "name": "list_notion_pages",
                    "description": "List available Notion pages",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_query": {
                                "type": "string", 
                                "description": "Search query to filter pages (optional)"
                            }
                        }
                    }
                }
            ])
        
        # Slack functions
        if tokens.get("slack"):
            functions.append({
                "name": "send_slack_message",
                "description": "Send a message to a Slack channel",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string", 
                            "description": "Message content"
                        },
                        "channel": {
                            "type": "string", 
                            "description": "Channel name (defaults to #general)"
                        }
                    },
                    "required": ["message"]
                }
            })
        
        # Zoom functions
        if tokens.get("zoom"):
            functions.append({
                "name": "create_zoom_meeting",
                "description": "Create a Zoom meeting with calendar integration",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string", 
                            "description": "Meeting topic/title"
                        },
                        "start_time": {
                            "type": "string", 
                            "description": "Start time in ISO format"
                        },
                        "duration": {
                            "type": "integer", 
                            "description": "Duration in minutes",
                            "default": 30
                        }
                    },
                    "required": ["topic"]
                }
            })
        
        return functions
    
    async def _get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user preferences and communication style"""
        try:
            from models.conversation import UserPreferences
            
            with SessionLocal() as db:
                prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
                
                if prefs:
                    return {
                        "communication_style": prefs.communication_style,
                        "preferred_response_length": prefs.preferred_response_length,
                        "settings": prefs.settings or {},
                        "learned_patterns": prefs.learned_patterns or {}
                    }
                
                # Default preferences for new users
                return {
                    "communication_style": "enthusiastic",
                    "preferred_response_length": "medium",
                    "settings": {},
                    "learned_patterns": {}
                }
                
        except Exception as e:
            logger.error(f"Error getting user preferences for user {user_id}: {str(e)}")
            return {"communication_style": "enthusiastic", "preferred_response_length": "medium"}
    
    async def _execute_functions(self, user_id: str, tool_calls: List[Dict]) -> List[Dict]:
        """Execute function calls from AI response"""
        
        results = []
        
        for tool_call in tool_calls:
            try:
                function_name = tool_call["function"]["name"]
                try:
                    arguments = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid arguments for function {function_name} for user {user_id}: {str(e)}")
                    results.append({
                        "function": function_name,
                        "success": False,
                        "error": "Invalid function arguments",
                        "arguments": tool_call["function"]["arguments"]
                    })
                    continue
                
                # Execute the function
                result = await self._execute_single_function(user_id, function_name, arguments)
                
                results.append({
                    "function": function_name,
                    "success": True,
                    "result": result,
                    "arguments": arguments
                })
                
            except Exception as e:
                logger.error(f"Function execution error for {function_name} for user {user_id}: {str(e)}")
                results.append({
                    "function": function_name,
                    "success": False,
                    "error": str(e),
                    "arguments": arguments if 'arguments' in locals() else {}
                })
        
        return results
    
    async def _execute_single_function(self, user_id: str, function_name: str, arguments: Dict) -> Any:
        """Execute a specific function with error handling"""
        
        if function_name == "get_calendar_events":
            from app.calendar_api import list_calendar_events
            return list_calendar_events(
                user_id,
                arguments.get("start_date"),
                arguments.get("end_date"),
                arguments.get("event_type")
            )
        
        elif function_name == "create_calendar_event":
            from app.calendar_api import create_calendar_event
            arguments["user_id"] = user_id
            return create_calendar_event(**arguments)
        
        elif function_name == "create_notion_page":
            from app.notion_api import create_notion_page
            return create_notion_page(
                title=arguments.get("title") or "",
                parent_page_id=arguments.get("parent_page_id") or "",
                user_id=user_id,
                extra_text=arguments.get("content") or ""
            )
        
        elif function_name == "create_zoom_meeting":
            from app.routes import create_zoom_meeting_logic
            return create_zoom_meeting_logic(arguments, user_id)
        
        elif function_name == "compose_email":
            from app.email_api import compose_email
            action = arguments.get("action", "draft")
            return compose_email(
                user_id=user_id,
                to=arguments.get("to"),
                subject=arguments.get("subject"),
                body=arguments.get("body"),
                action=action
            )
        
        elif function_name == "send_slack_message":
            from app.slack_api import send_slack_message
            return send_slack_message(
                user_id=user_id,
                message=arguments.get("message"),
                channel=arguments.get("channel", "#general")
            )
        
        elif function_name == "list_notion_pages":
            from app.notion_api import list_notion_pages
            return list_notion_pages(
                user_id=user_id,
            )
        
        else:
            logger.warning(f"Unknown function called: {function_name} for user {user_id}")
            raise ValueError(f"Function {function_name} is not supported")
    
    async def _store_conversation(self, user_id: str, message: str, response: str, metadata: Dict):
        """Store conversation in database for context"""
        try:
            from models.conversation import ConversationHistory
            
            with SessionLocal() as db:
                conversation = ConversationHistory(
                    user_id=user_id,
                    message=message,
                    response=response,
                    context=metadata,
                    timestamp=datetime.utcnow()
                )
                
                db.add(conversation)
                db.commit()
                
        except Exception as e:
            logger.error(f"Error storing conversation for user {user_id}: {str(e)}")
    
    def _generate_suggestions(self, context: ConversationContext, response: Dict) -> List[Dict]:
        """Generate contextual suggestions based on conversation"""
        
        try:
            tokens = load_tokens(context.user_id)
        except Exception as e:
            logger.error(f"Error loading tokens for suggestions for user {context.user_id}: {str(e)}")
            tokens = {}
        
        suggestions = []
        
        if tokens.get("google"):
            suggestions.append({
                "action": "Check calendar",
                "service": "google_calendar",
                "description": "View your upcoming events 📅",
                "priority": 5
            })
        
        if tokens.get("notion"):
            suggestions.append({
                "action": "Create Notion page",
                "service": "notion",
                "description": "Start a new document 📝",
                "priority": 4
            })
        
        if tokens.get("zoom"):
            suggestions.append({
                "action": "Create Zoom meeting",
                "service": "zoom",
                "description": "Set up a video call 🎥",
                "priority": 3
            })
        
        return suggestions[:3]  # Limit to top 3 suggestions
    
    def _generate_follow_ups(self, context: ConversationContext, response: Dict) -> List[str]:
        """Generate relevant follow-up questions based on conversation context"""
        
        follow_ups = []
        
        # Generate context-aware follow-ups
        last_message = context.messages[-1]["content"].lower()
        if "schedule" in last_message or "meeting" in last_message:
            follow_ups.append("Would you like me to check your calendar for available slots? 📅")
        elif "email" in last_message or "message" in last_message:
            follow_ups.append("Would you like to draft another email or message? ✉️")
        elif "notion" in last_message or "document" in last_message:
            follow_ups.append("Would you like to create another Notion page? 📝")
        
        # Add generic fallbacks
        follow_ups.extend([
            "What else can I help you with today? 😊",
            "Any other tasks I can assist you with? 🚀"
        ])
        
        return follow_ups[:2]  # Limit to 2 follow-ups

# Create singleton instance
ai_service = EnhancedAIService()
