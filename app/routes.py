# In app/routes.py - Replace the import section at the top
import sys
import os
import json
import logging
import mimetypes
import traceback
import re
import requests
from datetime import datetime, timedelta
from urllib.parse import urlencode
from typing import Dict, List, Any, Optional
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from fastapi.responses import RedirectResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models.user import User
from utils.db import get_db
from utils.token_store import load_tokens
from auth.auth_routes import get_current_user
from utils.jwt_utils import generate_state_token, decode_state_token
from typing import Optional

# Updated imports - use the new enhanced function
from .recommendation import (
    process_user_message, 
    chat_with_mistral, 
    generate_contextual_response_enhanced
)

from .calendar_api import (
    create_calendar_event, 
    list_calendar_events, 
    upload_to_drive, 
    send_gmail, 
    create_calendar_event_with_zoom,
    get_gmail_service,  # ← Add this import
    get_calendar_service  # ← Add this import
)
from .calendar_api import create_calendar_event, list_calendar_events, upload_to_drive, send_gmail, create_calendar_event_with_zoom
from .encryption import encrypt_data
from .mistral_api import call_mistral_api
from .slack_oauth import get_slack_auth_url, handle_slack_callback, post_to_slack
from .zoom_oauth import get_zoom_auth_url, handle_zoom_callback, refresh_zoom_token
from .notion_api import create_notion_page, list_notion_pages , get_notion_client , search_notion_pages
from .powerpoint_api import create_powerpoint_slides
# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic Models
class ChatMessage(BaseModel):
    message: str
    context: Optional[str] = None

class Suggestion(BaseModel):
    action: str
    service: str
    description: str
    priority: int

class ChatResponse(BaseModel):
    message: str
    intent: str
    confidence: float
    response: str
    suggestions: List[Suggestion]
    follow_up_questions: List[str]
    notion_pages: List[Dict[str, Any]]

class ComposeEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: Optional[str] = None
    bcc: Optional[str] = None

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: Optional[str] = None
    bcc: Optional[str] = None

# Calendar API models
class CreateEventRequest(BaseModel):
    summary: str
    description: Optional[str] = ""
    start_time: str  # ISO format: 2025-06-05T10:00:00
    end_time: Optional[str] = None  # If not provided, will be start_time + 1 hour
    timezone: Optional[str] = "Asia/Kolkata"
    attendees: Optional[List[str]] = []  # List of email addresses
    location: Optional[str] = ""

class UpdateNotionPageRequest(BaseModel):
    page_id: str
    title: Optional[str] = None
    content: Optional[str] = None  # New content to append

# Helper Functions
def get_user_services_context(user_tokens: Dict) -> Dict[str, bool]:
    """Get available services for the user"""
    return {
        "google_calendar": "google" in user_tokens and "access_token" in user_tokens.get("google", {}),
        "gmail": "google" in user_tokens and "access_token" in user_tokens.get("google", {}),
        "slack": "slack" in user_tokens and "access_token" in user_tokens.get("slack", {}),
        "zoom": "zoom" in user_tokens and "access_token" in user_tokens.get("zoom", {}),
        "notion": "notion" in user_tokens and "access_token" in user_tokens.get("notion", {})
    }

def analyze_user_intent(message: str) -> Dict[str, Any]:
    """Enhanced intent detection using keywords and patterns"""
    message_lower = message.lower()
    
    intent_patterns = {
        "schedule_meeting": {
            "keywords": ["schedule", "meeting", "event", "appointment", "calendar", "book", "arrange"],
            "patterns": [r"schedule.*meeting", r"book.*appointment", r"arrange.*call"],
            "confidence_base": 0.8
        },
        "send_email": {
            "keywords": ["email", "send", "message", "notify", "inform"],
            "patterns": [r"send.*email", r"email.*about", r"notify.*team"],
            "confidence_base": 0.7
        },
        "create_document": {
            "keywords": ["create", "document", "note", "write", "draft"],
            "patterns": [r"create.*document", r"write.*note", r"draft.*proposal"],
            "confidence_base": 0.7
        },
        "search_information": {
            "keywords": ["find", "search", "look", "information", "data"],
            "patterns": [r"find.*information", r"search.*for", r"look.*up"],
            "confidence_base": 0.6
        },
        "status_update": {
            "keywords": ["status", "update", "progress", "report"],
            "patterns": [r"status.*update", r"progress.*report", r"how.*going"],
            "confidence_base": 0.6
        },
        "general_question": {
            "keywords": ["help", "how", "what", "why", "when", "where"],
            "patterns": [r"how.*do", r"what.*is", r"help.*with"],
            "confidence_base": 0.5
        }
    }
    
    best_intent = "general_question"
    best_confidence = 0.3
    
    for intent, config in intent_patterns.items():
        confidence = 0
        
        keyword_matches = sum(1 for keyword in config["keywords"] if keyword in message_lower)
        confidence += (keyword_matches / len(config["keywords"])) * config["confidence_base"]
        
        pattern_matches = sum(1 for pattern in config["patterns"] if re.search(pattern, message_lower))
        if pattern_matches > 0:
            confidence += 0.2
        
        if confidence > best_confidence:
            best_intent = intent
            best_confidence = confidence
    
    return {
        "intent": best_intent,
        "confidence": min(best_confidence, 1.0)
    }

def generate_intelligent_response(message: str, intent: str, services: Dict[str, bool]) -> str:
    """Generate contextual response using Mistral with better prompting"""
    
    available_services = [service for service, available in services.items() if available]
    services_text = ", ".join(available_services) if available_services else "none"
    
    # Handle general questions that don't need productivity focus
    if intent == "general_question":
        message_lower = message.lower()
        
        # Check if it's a casual/informational question that doesn't need service mentions
        casual_keywords = ["what is", "who is", "define", "meaning", "sup", "hi", "hello", 
                          "how are you", "thanks", "thank you", "what if", "why", "how does", 
                          "explain", "tell me about"]
        
        is_casual = any(keyword in message_lower for keyword in casual_keywords)
        
        if is_casual:
            system_prompt = """You are a helpful, friendly assistant. Answer the question naturally and conversationally. 
            
Provide a brief, informative response that:
1. Directly answers their question
2. Is conversational and natural
3. Keep it under 50 words
4. Don't mention productivity tools or connected services unless specifically asked

Be helpful and engaging."""
        else:
            # For productivity-related general questions
            system_prompt = f"""You are a productivity assistant. Respond in 1-2 sentences max.

Available services: {services_text}

Provide a brief, helpful response that:
1. Acknowledges what they want to do
2. Suggests using available services if relevant
3. Keep it under 30 words

Be direct and actionable."""
    else:
        # For specific productivity intents
        system_prompt = f"""You are a productivity assistant. Respond in 1-2 sentences max.

Available services: {services_text}
User intent: {intent}

Provide a brief, helpful response that:
1. Acknowledges what they want to do
2. Suggests using their connected services
3. Keep it under 30 words

Be direct and actionable."""

    try:
        mistral_api_key = os.getenv("MISTRAL_API_KEY")
        if not mistral_api_key:
            # Fallback responses based on intent
            if intent == "schedule_meeting":
                return "I can help you schedule that meeting! Let me suggest some quick actions."
            elif intent == "send_email":
                return "I can help you draft and send that email!"
            elif intent == "create_document":
                return "Let's create that document for you!"
            elif intent == "general_question":
                message_lower = message.lower()
                if any(keyword in message_lower for keyword in ["sup", "hi", "hello"]):
                    return "Hey there! How can I help you today?"
                elif "what is" in message_lower or "what are" in message_lower:
                    return "I'd be happy to help answer that question!"
                else:
                    return "I'm here to help! What would you like to know or accomplish?"
            else:
                return "I'm here to help you be more productive!"

        headers = {
            "Authorization": f"Bearer {mistral_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "mistral-small-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": 0.3,
            "max_tokens": 50
        }
        
        response = requests.post("https://api.mistral.ai/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Mistral API error: {response.status_code} {response.text}")
            # Fallback based on intent
            if intent == "schedule_meeting":
                return "I can help you schedule that meeting! Let me suggest some actions."
            elif intent == "general_question":
                return "I'm happy to help! What would you like to know?"
            return "I'm here to help you be more productive!"
            
    except Exception as e:
        logger.error(f"Error calling Mistral API: {str(e)}")
        # Fallback based on intent
        if intent == "schedule_meeting":
            return "I can help you schedule that meeting!"
        elif intent == "general_question":
            message_lower = message.lower()
            if any(keyword in message_lower for keyword in ["sup", "hi", "hello"]):
                return "Hey there! How can I help you today?"
            return "I'm happy to help! What would you like to know?"
        return "I'm here to help you be productive!"

def generate_smart_suggestions(intent: str, message: str, services: Dict[str, bool]) -> List[Dict]:
    """Generate contextual suggestions based on intent and available services"""
    suggestions = []
    
    if intent == "schedule_meeting":
        if services.get("google_calendar"):
            suggestions.append({
                "action": "Create calendar event",
                "service": "google_calendar", 
                "description": "Schedule this meeting on your Google Calendar",
                "priority": 5
            })
        else:
            suggestions.append({
                "action": "Connect Google Calendar",
                "service": "google_calendar",
                "description": "Connect your Google Calendar to schedule meetings directly",
                "priority": 5
            })
            
        if services.get("gmail"):
            suggestions.append({
                "action": "Send meeting invite",
                "service": "gmail",
                "description": "Send email invitations to participants", 
                "priority": 4
            })
            
        if services.get("zoom"):
            suggestions.append({
                "action": "Create Zoom meeting",
                "service": "zoom",
                "description": "Generate Zoom link for the meeting",
                "priority": 4
            })
    
    elif intent == "send_email":
        if services.get("gmail"):
            suggestions.append({
                "action": "Compose email",
                "service": "gmail", 
                "description": "Draft and send your email",
                "priority": 5
            })
        else:
            suggestions.append({
                "action": "Connect Gmail",
                "service": "gmail",
                "description": "Connect your Gmail to send emails directly",
                "priority": 5
            })
    
    elif intent == "create_document":
        if services.get("notion"):
            suggestions.append({
                "action": "Create Notion page",
                "service": "notion",
                "description": "Start a new document in Notion", 
                "priority": 5
            })
        else:
            suggestions.append({
                "action": "Connect Notion",
                "service": "notion",
                "description": "Connect your Notion workspace to create documents",
                "priority": 5
            })
    
    elif intent == "status_update":
        if services.get("slack"):
            suggestions.append({
                "action": "Post to Slack",
                "service": "slack",
                "description": "Share your status update with your team",
                "priority": 4
            })
        if services.get("gmail"):
            suggestions.append({
                "action": "Send status email", 
                "service": "gmail",
                "description": "Email a detailed status report",
                "priority": 3
            })
    
    elif intent == "search_information":
        if services.get("notion"):
            suggestions.append({
                "action": "Search Notion",
                "service": "notion",
                "description": "Look for relevant information in your Notion workspace",
                "priority": 4
            })
    
    if not suggestions:
        if services.get("google_calendar"):
            suggestions.append({
                "action": "Check calendar",
                "service": "google_calendar",
                "description": "Review your upcoming events and schedule",
                "priority": 2
            })
        if services.get("notion"):
            suggestions.append({
                "action": "Browse Notion",
                "service": "notion", 
                "description": "Explore your Notion workspace for inspiration",
                "priority": 2
            })
    
    suggestions.sort(key=lambda x: x["priority"], reverse=True)
    return suggestions[:3]

def generate_follow_up_questions(intent: str, message: str) -> List[str]:
    """Generate relevant follow-up questions to continue the conversation"""
    questions = []
    
    if intent == "schedule_meeting":
        questions = [
            "What time works best for this meeting?",
            "Who should be invited to this meeting?",
            "How long should the meeting be?"
        ]
    elif intent == "send_email":
        questions = [
            "Who should receive this email?",
            "What's the main topic or subject?",
            "Is this urgent or can it wait?"
        ]
    elif intent == "create_document":
        questions = [
            "What type of document are you creating?",
            "What's the main purpose of this document?",
            "Do you need to collaborate with others on this?"
        ]
    elif intent == "general_question":
        questions = [
            "What specific task would you like help with?",
            "Are you looking to schedule something or send a message?",
            "What's your main goal right now?"
        ]
    else:
        questions = [
            "Would you like me to help you get started?",
            "Do you need any additional information?",
            "Is there anything else I can assist you with?"
        ]
    
    return questions[:2]

def create_zoom_meeting_logic(data, user_id):
    topic = data.get('topic', 'AI Meeting')
    start_time = data.get('start_time')
    duration = data.get('duration', 30)

    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")

    tokens = load_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="Tokens not found for this user")
    access_token = tokens.get("zoom", {}).get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Zoom token not found for this user. Please authenticate via /auth/zoom.")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    meeting_data = {
        "topic": topic,
        "type": 2,
        "start_time": start_time,
        "duration": duration,
        "timezone": "Asia/Kolkata",
        "settings": {
            "join_before_host": True,
            "waiting_room": False
        }
    }

    try:
        response = requests.post(
            "https://api.zoom.us/v2/users/me/meetings",
            headers=headers,
            json=meeting_data
        )

        if response.status_code == 401 and response.json().get("code") == 124:
            access_token = refresh_zoom_token(user_id)
            headers["Authorization"] = f"Bearer {access_token}"
            response = requests.post(
                "https://api.zoom.us/v2/users/me/meetings",
                headers=headers,
                json=meeting_data
            )

        if response.status_code != 201:
            raise HTTPException(status_code=500, detail={"error": "Zoom API error", "details": response.json()})

        result = response.json()
        return {
            "message": "Meeting created",
            "zoom_link": result["join_url"],
            "meeting_id": result["id"],
            "start_time": result["start_time"]
        }
    except Exception as e:
        logger.error(f"Error creating Zoom meeting for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating Zoom meeting: {str(e)}")

# Route Endpoints
@router.get("/ping")
def ping():
    return {"message": "pong"}

# In app/routes.py - Replace your existing /chat endpoint with this:

# In app/routes.py - Replace your existing /chat endpoint

# In app/routes.py - Replace your /chat endpoint with this safer version

@# Update in app/routes.py - Replace your existing /chat endpoint with this:

@router.post("/chat")
async def enhanced_chat_endpoint(request: Request, current_user: User = Depends(get_current_user)):
    """Enhanced chat endpoint with Claude AI and function calling"""
    try:
        user_id = str(current_user.id)
        data = await request.json()
        message = data.get("message", "").strip()

        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        logger.info(f"Processing enhanced message for user {user_id}: {message}")

        # Import the enhanced AI service
        from app.services.ai_service import ai_service
        
        # Process message with enhanced AI
        result = await ai_service.process_message(user_id, message)
        
        if not result["success"]:
            logger.error(f"AI processing failed for user {user_id}: {result.get('error')}")
            return {
                "message": message,
                "intent": "error",
                "confidence": 0.5,
                "response": result.get("response", "I encountered an error processing your request."),
                "suggestions": [],
                "follow_up_questions": ["How else can I help you today?"],
                "notion_pages": []
            }

        logger.info(f"Enhanced AI response generated for user {user_id}")
        
        return {
            "message": message,
            "intent": "ai_response",
            "confidence": 0.95,
            "response": result["response"],
            "suggestions": result.get("suggestions", []),
            "follow_up_questions": result.get("follow_up_questions", []),
            "function_results": result.get("function_results", []),
            "notion_pages": [],  # Will be populated by function calls if needed
            "metadata": result.get("metadata", {})
        }
        
    except Exception as e:
        logger.error(f"Error in enhanced chat processing for user {current_user.id}: {str(e)}")
        # Safe fallback response
        return {
            "message": message if 'message' in locals() else "",
            "intent": "error",
            "confidence": 0.5,
            "response": "I'm having trouble right now, but I'm still here to help! 😊 Please try again.",
            "suggestions": [
                {
                    "action": "Try again",
                    "service": "system",
                    "description": "Please rephrase your question",
                    "priority": 5
                }
            ],
            "follow_up_questions": ["What would you like me to help you with?"],
            "notion_pages": []
        }

# Add this fallback function to app/routes.py
def generate_simple_fallback_response(message: str, services: Dict[str, bool]) -> Dict[str, Any]:
    """Simple fallback response when enhanced logic fails"""
    message_lower = message.lower()
    
    # Handle calendar requests
    if any(word in message_lower for word in ["calendar", "events", "schedule"]):
        if services.get("google_calendar"):
            return {
                "response": "I can show you your calendar events!",
                "suggestions": [{
                    "action": "Check calendar",
                    "service": "google_calendar",
                    "description": "View your upcoming events",
                    "priority": 5
                }],
                "follow_up_questions": ["Would you like to see specific dates?"],
                "intent": "calendar_request",
                "confidence": 0.8
            }
        else:
            return {
                "response": "To view your calendar, please connect your Google Calendar first.",
                "suggestions": [{
                    "action": "Connect Google Calendar",
                    "service": "google_calendar",
                    "description": "Enable calendar integration",
                    "priority": 5
                }],
                "follow_up_questions": [],
                "intent": "calendar_not_connected",
                "confidence": 0.8
            }
    
    # Handle email requests
    elif any(word in message_lower for word in ["email", "gmail", "inbox"]):
        if services.get("gmail"):
            return {
                "response": "I can help you with your emails!",
                "suggestions": [{
                    "action": "List Gmail messages",
                    "service": "gmail",
                    "description": "Check your recent emails",
                    "priority": 5
                }],
                "follow_up_questions": ["Would you like to compose a new email?"],
                "intent": "email_request",
                "confidence": 0.8
            }
        else:
            return {
                "response": "To access your emails, please connect your Gmail first.",
                "suggestions": [{
                    "action": "Connect Gmail",
                    "service": "gmail",
                    "description": "Enable email integration",
                    "priority": 5
                }],
                "follow_up_questions": [],
                "intent": "email_not_connected",
                "confidence": 0.8
            }
    
    # Default response
    else:
        available_suggestions = []
        if services.get("google_calendar"):
            available_suggestions.append({
                "action": "Check calendar",
                "service": "google_calendar",
                "description": "View your upcoming events",
                "priority": 5
            })
        if services.get("gmail"):
            available_suggestions.append({
                "action": "List Gmail messages", 
                "service": "gmail",
                "description": "Check your recent emails",
                "priority": 4
            })
        
        return {
            "response": "I can help you with your calendar, emails, or other productivity tasks. What would you like to do?",
            "suggestions": available_suggestions[:2],  # Limit to 2 suggestions
            "follow_up_questions": ["What would you like me to help you with?"],
            "intent": "general_help",
            "confidence": 0.7
        }

@router.post('/create_zoom_meeting')
async def create_zoom_meeting(request: Request, current_user: User = Depends(get_current_user)):
    try:
        data = await request.json()
        user_id = str(current_user.id)
        return create_zoom_meeting_logic(data, user_id)
    except Exception as e:
        logger.error(f"Error in create_zoom_meeting endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/list_notion_pages')
async def list_notion_pages_endpoint(current_user: User = Depends(get_current_user)):
    try:
        user_id = str(current_user.id)
        pages = list_notion_pages(user_id)  # Pass user_id
        return {'pages': pages}
    except Exception as e:
        logger.error(f"Error listing Notion pages: {str(e)}")
        if "notion not connected" in str(e).lower() or "notion access token not found" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"
            })
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get('/search_notion_pages')
async def search_notion_pages_endpoint(
    query: str, 
    current_user: User = Depends(get_current_user)
):
    try:
        user_id = str(current_user.id)
        pages = search_notion_pages(user_id, query)
        return {'pages': pages}
    except Exception as e:
        logger.error(f"Error searching Notion pages: {str(e)}")
        if "notion not connected" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"
            })
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/list_notion_tasks')
async def list_notion_tasks_endpoint(current_user: User = Depends(get_current_user)):
    try:
        tasks = [
            {"title": "updating the company's mission statement", "section": "Projects"}
        ]
        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"Error listing Notion tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/list_drive_deadlines')
async def list_drive_deadlines_endpoint(request: Request, current_user: User = Depends(get_current_user)):
    try:
        deadlines = [
            {"title": "the quarterly report", "folder": "Quarterly Reports"}
        ]
        return {"deadlines": deadlines}
    except Exception as e:
        logger.error(f"Error listing Google Drive deadlines: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/list_calendar_events')
@router.post('/list_calendar_events')
async def list_calendar_events_endpoint(request: Request, current_user: User = Depends(get_current_user)):
    try:
        start_date = end_date = event_type = attendees = date_param = None

        if request.method == 'GET':
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            event_type = request.query_params.get('event_type')
            attendees = request.query_params.get('attendees')
            date_param = request.query_params.get('date')
        else:
            data = await request.json()
            start_date = data.get('start_date', request.query_params.get('start_date'))
            end_date = data.get('end_date', request.query_params.get('end_date'))
            event_type = data.get('event_type', request.query_params.get('event_type'))
            attendees = data.get('attendees', request.query_params.get('attendees'))
            date_param = data.get('date', request.query_params.get('date'))

        if not start_date and date_param:
            start_date = end_date = date_param

        user_id = str(current_user.id)
        events = list_calendar_events(user_id, start_date, end_date, event_type, attendees)
        return {'events': events}
    except Exception as e:
        logger.error(f"Error listing calendar events: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={'action': 'Requires authentication', 'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"})
        raise HTTPException(status_code=500, detail=f"Error listing calendar events: {str(e)}")

@router.get('/download_slides/{filename}')
async def download_slides(filename: str):
    try:
        directory = os.path.join(os.getcwd(), "presentations")
        mimetype_guess = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(path=os.path.join(directory, filename), media_type=mimetype_guess, filename=filename)
    except Exception as e:
        logger.error(f"Error downloading slides: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/execute_task")
def execute_task_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    body: dict = Body(...)
):
    action = body.get("action", "")
    event_summary = body.get("event_summary", "")
    parent_page_id = body.get("parent_page_id", None)
    start_time = body.get("start_time", None)
    duration = body.get("duration", 30)
    recipient = body.get("recipient", "")
    slack_channel = body.get("slack_channel", "")

    user_id = str(current_user.id)
    tokens = load_tokens(user_id)

    try:
        # Updated Notion section with improved handling
        if action in ["Write important notes in Notion", "Create Notion page"]:
            if not tokens.get("notion"):
                raise HTTPException(status_code=401, detail="Notion not connected. Please authenticate via /auth/notion.")
            
            # Get parent page ID from request or use user's first available page
            selected_page_id = body.get("parent_page_id")
            result = create_notion_page(
                event_summary=event_summary,
                parent_page_id=selected_page_id,
                user_id=user_id,
                extra_text=body.get("extra_text"),
                drive_link=body.get("drive_link")
            )
            return {"message": "Notion page created", "notion": result}

        elif action == "Setup full Zoom meeting" or action == "Create a Zoom Meeting":
            if not tokens.get("zoom"):
                raise HTTPException(status_code=401, detail="Zoom not connected. Please authenticate via /auth/zoom.")
            zoom_data = create_zoom_meeting_logic({
                "topic": event_summary,
                "start_time": start_time if start_time else datetime.now().isoformat(),
                "duration": duration
            }, user_id)
            calendar_event = create_calendar_event_with_zoom(
                topic=event_summary,
                start_time=start_time if start_time else datetime.now().isoformat(),
                duration=duration,
                zoom_link=zoom_data["zoom_link"],
                user_id=user_id
            )
            return {"message": "Zoom meeting and calendar event created", "zoom": zoom_data, "calendar_event": calendar_event}

        elif action == "Write email to colleague":
            if not tokens.get("google"):
                raise HTTPException(status_code=401, detail="Google not connected. Please authenticate via /auth/google.")
            email_body = f"Meeting scheduled: {event_summary}"
            return send_gmail(recipient, f"Regarding: {event_summary}", email_body, user_id)

        elif action in ["Post update on Slack", "Send a Slack Reminder"]:
            if not tokens.get("slack"):
                raise HTTPException(status_code=401, detail="Slack not connected. Please authenticate via /auth/slack.")
            return post_to_slack(f"Update: {event_summary}", user_id=user_id)

        else:
            return {"message": f"No handler implemented for action '{action}'"}
            
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={'action': 'Requires authentication', 'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"})
        if "notion token not found" in str(e).lower():
            raise HTTPException(status_code=401, detail={'action': 'Requires authentication', 'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"})
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get('/list_gmail_messages')
async def list_gmail_messages(
    max_results: int = 10,
    query: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """List Gmail messages for the user"""
    try:
        user_id = str(current_user.id)
        service = get_gmail_service(user_id)
        
        # Build query parameters
        search_query = query if query else "in:inbox"
        
        # Get message list
        messages_result = service.users().messages().list(
            userId='me',
            q=search_query,
            maxResults=max_results
        ).execute()
        
        messages = messages_result.get('messages', [])
        
        # Get detailed message info
        detailed_messages = []
        for message in messages:
            msg = service.users().messages().get(
                userId='me', 
                id=message['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            
            # Extract headers
            headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
            
            detailed_messages.append({
                'id': message['id'],
                'from': headers.get('From', 'Unknown'),
                'subject': headers.get('Subject', 'No Subject'),
                'date': headers.get('Date', ''),
                'snippet': msg.get('snippet', '')
            })
        
        logger.info(f"Retrieved {len(detailed_messages)} Gmail messages for user {user_id}")
        return {'messages': detailed_messages, 'total': len(detailed_messages)}
        
    except Exception as e:
        logger.error(f"Error listing Gmail messages for user {current_user.id}: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"
            })
        raise HTTPException(status_code=500, detail=f"Error listing Gmail messages: {str(e)}")

@router.post('/compose_gmail')
async def compose_gmail(
    email_data: ComposeEmailRequest,
    current_user: User = Depends(get_current_user)
):
    """Compose (draft) an email in Gmail"""
    try:
        user_id = str(current_user.id)
        service = get_gmail_service(user_id)
        
        # Create message
        from email.mime.text import MIMEText
        message = MIMEText(email_data.body)
        message['to'] = email_data.to
        message['subject'] = email_data.subject
        if email_data.cc:
            message['cc'] = email_data.cc
        if email_data.bcc:
            message['bcc'] = email_data.bcc
        
        # Create draft
        import base64
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        draft_body = {
            'message': {
                'raw': raw_message
            }
        }
        
        draft = service.users().drafts().create(userId='me', body=draft_body).execute()
        
        logger.info(f"Created Gmail draft for user {user_id}: {draft['id']}")
        return {
            'message': 'Email draft created successfully',
            'draft_id': draft['id'],
            'to': email_data.to,
            'subject': email_data.subject
        }
        
    except Exception as e:
        logger.error(f"Error composing Gmail for user {current_user.id}: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"
            })
        raise HTTPException(status_code=500, detail=f"Error composing Gmail: {str(e)}")

@router.post('/send_gmail')
async def send_gmail_direct(
    email_data: SendEmailRequest,
    current_user: User = Depends(get_current_user)
):
    """Send an email directly via Gmail"""
    try:
        user_id = str(current_user.id)
        result = send_gmail(
            to=email_data.to,
            subject=email_data.subject, 
            body=email_data.body,
            user_id=user_id
        )
        
        logger.info(f"Sent Gmail for user {user_id} to {email_data.to}")
        return {
            'message': 'Email sent successfully',
            'details': result,
            'to': email_data.to,
            'subject': email_data.subject
        }
        
    except Exception as e:
        logger.error(f"Error sending Gmail for user {current_user.id}: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"
            })
        raise HTTPException(status_code=500, detail=f"Error sending Gmail: {str(e)}")
    

# Calendar APIs
@router.post('/create_calendar_event')
async def create_calendar_event_direct(
    event_data: CreateEventRequest,
    current_user: User = Depends(get_current_user)
):
    """Create a Google Calendar event directly"""
    try:
        user_id = str(current_user.id)
        service = get_calendar_service(user_id)
        
        # Parse start time
        start_dt = datetime.fromisoformat(event_data.start_time.replace('Z', '+00:00'))
        
        # Calculate end time if not provided
        if event_data.end_time:
            end_dt = datetime.fromisoformat(event_data.end_time.replace('Z', '+00:00'))
        else:
            end_dt = start_dt + timedelta(hours=1)
        
        # Build attendees list
        attendees_list = []
        for email in event_data.attendees:
            attendees_list.append({'email': email})
        
        # Create event object
        event = {
            'summary': event_data.summary,
            'description': event_data.description,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': event_data.timezone,
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': event_data.timezone,
            },
            'attendees': attendees_list,
            'location': event_data.location,
            'reminders': {
                'useDefault': True
            }
        }
        
        # Create the event
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        
        logger.info(f"Created calendar event for user {user_id}: {created_event['id']}")
        return {
            'message': 'Calendar event created successfully',
            'event_id': created_event['id'],
            'summary': event_data.summary,
            'start_time': event_data.start_time,
            'html_link': created_event.get('htmlLink'),
            'hangout_link': created_event.get('hangoutLink')
        }
        
    except Exception as e:
        logger.error(f"Error creating calendar event for user {current_user.id}: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"
            })
        raise HTTPException(status_code=500, detail=f"Error creating calendar event: {str(e)}")

@router.get('/calendar_events/{event_id}')
async def get_calendar_event(
    event_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get a specific calendar event by ID"""
    try:
        user_id = str(current_user.id)
        service = get_calendar_service(user_id)
        
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        
        return {
            'id': event['id'],
            'summary': event.get('summary', 'No Title'),
            'description': event.get('description', ''),
            'start': event['start'],
            'end': event['end'],
            'location': event.get('location', ''),
            'attendees': event.get('attendees', []),
            'html_link': event.get('htmlLink'),
            'created': event.get('created'),
            'updated': event.get('updated')
        }
        
    except Exception as e:
        logger.error(f"Error getting calendar event for user {current_user.id}: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"
            })
        raise HTTPException(status_code=500, detail=f"Error getting calendar event: {str(e)}")

@router.delete('/calendar_events/{event_id}')
async def delete_calendar_event(
    event_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a calendar event"""
    try:
        user_id = str(current_user.id)
        service = get_calendar_service(user_id)
        
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        
        logger.info(f"Deleted calendar event {event_id} for user {user_id}")
        return {
            'message': 'Calendar event deleted successfully',
            'event_id': event_id
        }
        
    except Exception as e:
        logger.error(f"Error deleting calendar event for user {current_user.id}: {str(e)}")
        if "google authentication required" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/google"
            })
        raise HTTPException(status_code=500, detail=f"Error deleting calendar event: {str(e)}")
    
@router.put('/update_notion_page')
async def update_notion_page(
    update_data: UpdateNotionPageRequest,
    current_user: User = Depends(get_current_user)
):
    """Update a Notion page"""
    try:
        user_id = str(current_user.id)
        notion = get_notion_client(user_id)
        
        # Clean the page ID
        page_id = update_data.page_id.replace("-", "")
        if "?" in page_id:
            page_id = page_id.split("?")[0]
        
        updates = {}
        
        # Update title if provided
        if update_data.title:
            updates["properties"] = {
                "title": {
                    "title": [{
                        "type": "text",
                        "text": {"content": update_data.title}
                    }]
                }
            }
        
        # Update page properties
        if updates:
            notion.pages.update(page_id=page_id, **updates)
            logger.info(f"Updated page properties for {page_id}")
        
        # Append content if provided
        if update_data.content:
            new_block = {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": update_data.content}
                    }]
                }
            }
            
            notion.blocks.children.append(
                block_id=page_id,
                children=[new_block]
            )
            logger.info(f"Appended content to page {page_id}")
        
        # Get updated page info
        updated_page = notion.pages.retrieve(page_id=page_id)
        
        logger.info(f"Updated Notion page for user {user_id}: {page_id}")
        return {
            'message': 'Notion page updated successfully',
            'page_id': page_id,
            'title': update_data.title,
            'url': updated_page['url'],
            'last_edited': updated_page.get('last_edited_time')
        }
        
    except Exception as e:
        logger.error(f"Error updating Notion page for user {current_user.id}: {str(e)}")
        if "notion not connected" in str(e).lower() or "notion access token not found" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"
            })
        raise HTTPException(status_code=500, detail=f"Error updating Notion page: {str(e)}")

@router.delete('/delete_notion_page/{page_id}')
async def delete_notion_page(
    page_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete (archive) a Notion page"""
    try:
        user_id = str(current_user.id)
        notion = get_notion_client(user_id)
        
        # Clean the page ID
        clean_page_id = page_id.replace("-", "")
        if "?" in clean_page_id:
            clean_page_id = clean_page_id.split("?")[0]
        
        # Archive the page (Notion doesn't allow true deletion)
        notion.pages.update(
            page_id=clean_page_id,
            archived=True
        )
        
        logger.info(f"Archived Notion page for user {user_id}: {clean_page_id}")
        return {
            'message': 'Notion page archived successfully',
            'page_id': clean_page_id,
            'note': 'Page has been archived (moved to trash) as Notion does not support permanent deletion'
        }
        
    except Exception as e:
        logger.error(f"Error deleting Notion page for user {current_user.id}: {str(e)}")
        if "notion not connected" in str(e).lower() or "notion access token not found" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"
            })
        raise HTTPException(status_code=500, detail=f"Error deleting Notion page: {str(e)}")

@router.get('/notion_page/{page_id}')
async def get_notion_page(
    page_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get detailed information about a Notion page"""
    try:
        user_id = str(current_user.id)
        notion = get_notion_client(user_id)
        
        # Clean the page ID
        clean_page_id = page_id.replace("-", "")
        if "?" in clean_page_id:
            clean_page_id = clean_page_id.split("?")[0]
        
        # Get page details
        page = notion.pages.retrieve(page_id=clean_page_id)
        
        # Get page title
        title = "Untitled"
        if page.get("properties", {}).get("title", {}).get("title"):
            title_array = page["properties"]["title"]["title"]
            if title_array and len(title_array) > 0:
                title = title_array[0]["plain_text"]
        
        # Get page content (blocks)
        blocks = notion.blocks.children.list(block_id=clean_page_id)
        
        content_text = ""
        for block in blocks.get("results", []):
            if block["type"] == "paragraph":
                for rich_text in block["paragraph"]["rich_text"]:
                    content_text += rich_text["plain_text"] + "\n"
        
        logger.info(f"Retrieved Notion page details for user {user_id}: {clean_page_id}")
        return {
            'id': page['id'],
            'title': title,
            'url': page['url'],
            'created_time': page.get('created_time'),
            'last_edited_time': page.get('last_edited_time'),
            'archived': page.get('archived', False),
            'content_preview': content_text[:500] + "..." if len(content_text) > 500 else content_text,
            'block_count': len(blocks.get("results", []))
        }
        
    except Exception as e:
        logger.error(f"Error getting Notion page for user {current_user.id}: {str(e)}")
        if "notion not connected" in str(e).lower() or "notion access token not found" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"
            })
        raise HTTPException(status_code=500, detail=f"Error getting Notion page: {str(e)}")

@router.post('/create_notion_page_direct')
async def create_notion_page_direct(
    page_data: dict = Body(...),
    current_user: User = Depends(get_current_user)
):
    """Create a new Notion page directly"""
    try:
        user_id = str(current_user.id)
        
        result = create_notion_page(
            event_summary=page_data.get("title", "New Page"),
            parent_page_id=page_data.get("parent_page_id"),
            user_id=user_id,
            extra_text=page_data.get("content", ""),
            drive_link=page_data.get("drive_link")
        )
        
        logger.info(f"Created Notion page for user {user_id}")
        return result
        
    except Exception as e:
        logger.error(f"Error creating Notion page for user {current_user.id}: {str(e)}")
        if "notion not connected" in str(e).lower() or "notion access token not found" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                'action': 'Requires authentication', 
                'auth_url': f"{os.getenv('BASE_URL', 'http://localhost:8000')}/auth/notion"
            })
        raise HTTPException(status_code=500, detail=f"Error creating Notion page: {str(e)}")