import logging
import asyncio
import traceback
import re
import random
from datetime import date, timedelta
from typing import Dict, List, Any, Optional
from .mistral_api import call_mistral_api
from .calendar_api import list_calendar_events
from .notion_api import list_notion_pages
from cachetools import TTLCache
from utils.token_store import load_tokens
from fastapi import HTTPException

logger = logging.getLogger(__name__)

notion_pages_cache = TTLCache(maxsize=100, ttl=300)

# Enhanced context-aware additions
PRODUCTIVITY_KEYWORDS = [
    "meeting", "schedule", "calendar", "email", "task", "project", "deadline",
    "work", "office", "team", "collaboration", "planning", "organize", "remind",
    "appointment", "event", "zoom", "slack", "notion", "document", "note",
    "productivity", "manage", "time", "busy", "focus", "goal", "priority"
]

INAPPROPRIATE_KEYWORDS = [
    "sex", "dating", "relationship", "love", "personal", "private", "intimate",
    "nsfw", "adult", "inappropriate", "orgy", "lesbian"
]

REJECTION_PATTERNS = [
    r"i don\'t want\b", r"no thanks\b", r"not interested\b", r"don\'t need\b",
    r"already did\b", r"not now\b", r"maybe later\b", r"\bskip\b", r"\bpass\b"
]

class DataAIPersonalityEnhancer:
    """Adds personality to existing responses without breaking current logic"""
    
    def __init__(self):
        self.name = "DATA-AI"
        self.conversation_counts: Dict[str, int] = {}
    
    def enhance_greeting(self, user_id: str, original_response: str) -> str:
        """Enhance greeting responses with DATA-AI personality"""
        count = self.conversation_counts.get(user_id, 0) + 1
        self.conversation_counts[user_id] = count
        
        if count == 1:
            greetings = [
                f"Hey there! 👋 I'm {self.name}, your productivity companion! " + original_response.replace("Hi! I", "I"),
                f"Hello! ✨ {self.name} here, ready to supercharge your day! " + original_response.replace("Hi! I", "I"),
                f"Hi! 🌟 {self.name} at your service! " + original_response.replace("Hi! I", "I")
            ]
            return random.choice(greetings)
        else:
            repeat_greetings = [
                f"Hey again! 😊 {self.name} here - what's next on our productivity adventure?",
                f"Back for more? 🚀 {self.name} is ready to help you conquer your tasks!",
                f"Hello again! ⚡ {self.name} here - let's make things happen!",
                f"Hey there! 🎯 {self.name} ready to boost your productivity!"
            ]
            return random.choice(repeat_greetings)
    
    def enhance_service_response(self, message: str, original_response: str, intent: str) -> str:
        """Enhance service-specific responses with emojis and personality"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ["calendar", "events", "schedule", "upcoming"]):
            if "can show you" in original_response:
                return f"Absolutely! 📅 {self.name} loves helping with calendars! " + original_response.replace("I can show you", "Let me show you")
            elif "connect your Google Calendar" in original_response:
                return f"To unleash my calendar superpowers 📅, " + original_response.lower()
        
        elif any(word in message_lower for word in ["email", "gmail", "inbox", "messages"]):
            if "can help you with your emails" in original_response:
                return f"Perfect! 📧 {self.name} is excellent with email management! " + original_response.replace("I can help you", "Let me help you")
            elif "connect your Gmail" in original_response:
                return f"To access your email superpowers 📧, " + original_response.lower()
        
        elif any(word in message_lower for word in ["notion", "notes", "document", "page"]):
            if "notion" in original_response.lower():
                return f"Great choice! 📝 {self.name} loves working with Notion! " + original_response
        
        elif any(word in message_lower for word in ["slack", "channel", "post"]):
            if "slack" in original_response.lower():
                return f"Awesome! 💬 {self.name} is ready to connect your team on Slack! " + original_response
        
        elif any(word in message_lower for word in ["zoom", "video call", "meeting link"]):
            if "zoom" in original_response.lower():
                return f"Let's get that call set up! 🎥 {self.name} loves Zoom meetings! " + original_response
        
        if original_response.startswith("I can help"):
            return f"Absolutely! 💡 {self.name} is here to help! " + original_response.replace("I can help", "Let me help")
        
        return original_response
    
    def enhance_connection_status(self, original_response: str) -> str:
        """Enhance connection status responses"""
        if "✅" in original_response:
            return f"Awesome! 🎉 " + original_response
        elif "❌" in original_response:
            return f"No worries! 🔧 " + original_response
        return original_response
    
    def enhance_general_response(self, message: str, original_response: str) -> str:
        """Add general personality enhancements"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ["thank", "thanks"]):
            return f"You're so welcome! 😊 {self.name} loves helping awesome people like you! ✨"
        
        elif any(word in message_lower for word in ["good", "great", "awesome", "amazing"]):
            return f"That's fantastic! 🎉 I love your positive energy! How can {self.name} help you keep that momentum going? 💪"
        
        elif any(phrase in message_lower for phrase in ["help", "what can", "how to"]):
            if "productivity tasks" in original_response:
                return original_response.replace("productivity tasks", "productivity tasks with style! ✨")
        
        if original_response.startswith("I can help you with"):
            return original_response.replace("I can help", f"{self.name} can help")
        
        return original_response
    
    def detect_service_intent_smart(self, message: str) -> bool:
        """Smart detection - only suggest services when user explicitly wants them"""
        message_lower = message.lower()
        
        service_words = [
            "calendar", "events", "schedule", "meeting", "appointment", "upcoming",
            "email", "gmail", "inbox", "message", "mail", "messages",
            "notion", "notes", "document", "page", "write", "create",
            "slack", "team", "channel", "post",
            "zoom", "video call", "meeting link"
        ]
        
        action_words = [
            "list", "show", "check", "view", "see", "get", "find",
            "create", "make", "send", "schedule", "want", "need",
            "help", "assist", "display", "fetch", "retrieve", "access"
        ]
        
        has_service = any(service in message_lower for service in service_words)
        has_action = any(action in message_lower for action in action_words)
        
        calendar_phrases = [
            "upcoming events", "my events", "calendar events", "what's on my calendar",
            "show events", "see events", "check calendar", "view calendar"
        ]
        
        email_phrases = [
            "check email", "see emails", "inbox", "recent emails", "gmail messages",
            "show messages", "email list"
        ]
        
        notion_phrases = [
            "notion pages", "my notes", "show pages", "list pages", "create page"
        ]
        
        slack_phrases = [
            "slack channels", "post to slack", "send slack message"
        ]
        
        zoom_phrases = [
            "create zoom", "zoom meeting", "video call"
        ]
        
        has_calendar_phrase = any(phrase in message_lower for phrase in calendar_phrases)
        has_email_phrase = any(phrase in message_lower for phrase in email_phrases)
        has_notion_phrase = any(phrase in message_lower for phrase in notion_phrases)
        has_slack_phrase = any(phrase in message_lower for phrase in slack_phrases)
        has_zoom_phrase = any(phrase in message_lower for phrase in zoom_phrases)
        
        return (has_service and has_action) or has_calendar_phrase or has_email_phrase or has_notion_phrase or has_slack_phrase or has_zoom_phrase

dataai_enhancer = DataAIPersonalityEnhancer()

def enhance_mistral_response_with_dataai(original_response: str, message: str) -> str:
    """Add DATA-AI personality to Mistral responses"""
    message_lower = message.lower()
    
    if len(original_response) < 50 and not any(emoji in original_response for emoji in ["😊", "👋", "🎯", "✨"]):
        if any(word in original_response.lower() for word in ["great", "good", "excellent"]):
            return f"That's awesome! 🎉 " + original_response + " How can DATA-AI help you make it even better? ✨"
        elif any(word in original_response.lower() for word in ["difficult", "hard", "challenge"]):
            return f"I hear you! 💪 " + original_response + " DATA-AI is here to help you tackle this! 🚀"
        else:
            return f"Absolutely! 😊 " + original_response + " What's your next move? 🎯"
    
    return original_response

class ConversationContext:
    """Track conversation context to avoid repetitive suggestions"""
    
    def __init__(self):
        self.rejected_services: set = set()
        self.suggested_actions: set = set()
        self.conversation_count: int = 0
        self.last_intent: Optional[str] = None
    
    def add_rejection(self, service: str) -> None:
        self.rejected_services.add(service.lower())
    
    def add_suggested_action(self, action: str) -> None:
        self.suggested_actions.add(action.lower())
    
    def is_rejected(self, service: str) -> bool:
        return service.lower() in self.rejected_services
    
    def already_suggested(self, action: str) -> bool:
        return action.lower() in self.suggested_actions

user_contexts: Dict[str, ConversationContext] = {}

def get_user_context(user_id: str) -> ConversationContext:
    """Get or create conversation context for user"""
    if not user_id or not isinstance(user_id, str):
        raise ValueError("Invalid user_id")
    if user_id not in user_contexts:
        user_contexts[user_id] = ConversationContext()
    return user_contexts[user_id]

def is_productivity_related(message: str) -> bool:
    """Check if message is related to productivity/work"""
    message_lower = message.lower()
    
    for keyword in INAPPROPRIATE_KEYWORDS:
        if keyword in message_lower:
            return False
    
    for keyword in PRODUCTIVITY_KEYWORDS:
        if keyword in message_lower:
            return True
    
    productivity_phrases = [
        "what should i do", "help me with", "how to", "need to",
        "have to", "should i", "can you help", "assist me", "updates", "events"
    ]
    
    return any(phrase in message_lower for phrase in productivity_phrases)

def detect_rejection(message: str) -> bool:
    """Detect if user is rejecting suggestions"""
    message_lower = message.lower()
    
    for pattern in REJECTION_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return True
    
    negative_words = ["no", "nope", "nah", "never", "stop", "enough", "annoying"]
    return any(word in message_lower for word in negative_words)

def extract_rejected_service(message: str) -> Optional[str]:
    """Extract which service the user is rejecting"""
    message_lower = message.lower()
    services = ["notion", "calendar", "slack", "zoom", "email", "gmail"]
    
    for service in services:
        if service in message_lower:
            return service
    return None

POSITIVE_KEYWORDS = ["good", "great", "fantastic", "amazing", "success", "achieve", "milestone", "celebrate", "happy", "awesome", "excellent", "wonderful"]
NEGATIVE_KEYWORDS = ["bad", "terrible", "fail", "overwhelm", "stress", "problem", "issue", "difficult", "sad", "frustrate", "struggle", "delay"]

async def fetch_calendar_events(start_date: Optional[str] = None, end_date: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict]:
    """Fetch calendar events using internal Google Calendar API"""
    try:
        if not user_id:
            raise ValueError("User ID is required")
        
        tokens = load_tokens(user_id)
        if not tokens.get("google") or not tokens.get("google").get("access_token"):
            raise HTTPException(status_code=401, detail={
                "action": "Requires authentication",
                "auth_url": "http://localhost:8000/auth/google"
            })
        
        events = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: list_calendar_events(user_id, start_date, end_date)
        )
        
        if not isinstance(events, list):
            logger.error(f"Unexpected response format for calendar events: {events}")
            return []
        
        logger.info(f"Fetched {len(events)} calendar events for user {user_id}")
        return events
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching calendar events for user {user_id}: {str(e)}")
        if "invalid_scope" in str(e).lower():
            raise HTTPException(status_code=401, detail={
                "action": "Invalid scope",
                "auth_url": "http://localhost:8000/auth/google/force-reauth"
            })
        raise HTTPException(status_code=500, detail=f"Failed to fetch calendar events: {str(e)}")

async def fetch_notion_pages(user_id: Optional[str] = None) -> List[Dict]:
    """Fetch Notion pages using internal API"""
    cache_key = f"notion_pages_{user_id}"
    if cache_key in notion_pages_cache:
        logger.info(f"Returning cached Notion pages for user {user_id}")
        return notion_pages_cache[cache_key]
    
    try:
        if not user_id:
            raise ValueError("User ID is required")
        
        tokens = load_tokens(user_id)
        if not tokens.get("notion") or not tokens.get("notion").get("access_token"):
            raise HTTPException(status_code=401, detail={
                "action": "Requires authentication",
                "auth_url": "http://localhost:8000/auth/notion"
            })
        
        pages = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: list_notion_pages(user_id)
        )
        
        if not isinstance(pages, list):
            logger.error(f"Unexpected response format for Notion pages: {pages}")
            return []
        
        notion_pages_cache[cache_key] = pages
        logger.info(f"Fetched {len(pages)} Notion pages for user {user_id}")
        return pages
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching Notion pages for user {user_id}: {str(e)}")
        return []

async def fetch_notion_tasks(user_id: Optional[str] = None) -> List[Dict]:
    """Mock implementation for Notion tasks (replace with actual API call if available)"""
    try:
        if not user_id:
            raise ValueError("User ID is required")
        return [{"id": "task1", "title": "Update mission statement", "section": "Projects"}]
    except Exception as e:
        logger.error(f"Error fetching Notion tasks for user {user_id}: {str(e)}")
        return []

async def fetch_drive_deadlines(user_id: Optional[str] = None) -> List[Dict]:
    """Mock implementation for Google Drive deadlines (replace with actual API call if available)"""
    try:
        if not user_id:
            raise ValueError("User ID is required")
        return [{"id": "deadline1", "title": "Quarterly Report", "folder": "Reports"}]
    except Exception as e:
        logger.error(f"Error fetching Google Drive deadlines for user {user_id}: {str(e)}")
        return []

def generate_action_suggestions(message: str, mistral_response: str = "") -> List[Dict]:
    message_lower = message.lower()
    mistral_lower = mistral_response.lower()
    suggestions = []

    if 'meeting' in message_lower or 'conference' in message_lower or 'meeting' in mistral_lower:
        suggestions.extend([
            {"action": "Write important notes in Notion", "service": "notion", "description": "Create a Notion page to jot down key points.", "priority": 5},
            {"action": "Write up an email for the meeting", "service": "gmail", "description": "Draft an email about meeting details.", "priority": 4},
            {"action": "Create Zoom meeting", "service": "zoom", "description": "Generate a Zoom link for the meeting.", "priority": 3}
        ])
    elif 'deadline' in message_lower or 'project' in message_lower or 'deadline' in mistral_lower:
        suggestions.extend([
            {"action": "Break down tasks in Notion", "service": "notion", "description": "Outline tasks for the project.", "priority": 5},
            {"action": "Set a calendar reminder", "service": "calendar", "description": "Add a reminder to Google Calendar.", "priority": 4}
        ])
    elif 'appointment' in message_lower or 'doctor' in message_lower or 'appointment' in mistral_lower:
        suggestions.extend([
            {"action": "Send a reminder email", "service": "gmail", "description": "Draft an email reminder.", "priority": 5},
            {"action": "Add to calendar", "service": "calendar", "description": "Add the appointment to Google Calendar.", "priority": 4}
        ])
    elif 'celebrate' in message_lower or 'milestone' in message_lower or 'success' in mistral_lower:
        suggestions.extend([
            {"action": "Schedule a team celebration", "service": "calendar", "description": "Schedule a celebration meeting.", "priority": 5},
            {"action": "Share achievement on Slack", "service": "slack", "description": "Post a message on Slack.", "priority": 4}
        ])
    elif 'overwhelmed' in message_lower or 'stress' in message_lower or 'overwhelmed' in mistral_lower:
        suggestions.extend([
            {"action": "Organize thoughts in Notion", "service": "notion", "description": "Create a Notion page to reduce stress.", "priority": 5},
            {"action": "Request support via email", "service": "gmail", "description": "Draft an email for support.", "priority": 4}
        ])
    else:
        suggestions.append({"action": "Plan your day", "service": "calendar", "description": "Schedule your tasks on Google Calendar.", "priority": 3})

    return suggestions

def generate_sentiment_based_suggestions(message: str, sentiment: str, mistral_response: str = "") -> List[Dict]:
    message_lower = message.lower()
    mistral_lower = mistral_response.lower()
    suggestions = []

    if sentiment == "positive":
        if 'celebrate' in message_lower or 'milestone' in message_lower or 'success' in mistral_lower:
            suggestions.extend([
                {"action": "Schedule a team celebration", "service": "calendar", "description": "Schedule a celebration meeting.", "priority": 5},
                {"action": "Share achievement on Slack", "service": "slack", "description": "Post a message on Slack.", "priority": 4}
            ])
        elif 'project' in message_lower or 'progress' in mistral_lower:
            suggestions.extend([
                {"action": "Document progress in Notion", "service": "notion", "description": "Create a Notion page for progress.", "priority": 5},
                {"action": "Schedule a follow-up meeting", "service": "calendar", "description": "Keep the momentum going.", "priority": 4}
            ])
        else:
            suggestions.append({"action": "Celebrate with a team email", "service": "gmail", "description": "Send a celebratory email.", "priority": 3})
    else:
        if 'project' in message_lower or 'deadline' in mistral_lower:
            suggestions.extend([
                {"action": "Break down tasks in Notion", "service": "notion", "description": "Outline tasks for the project.", "priority": 5},
                {"action": "Set a calendar reminder", "service": "calendar", "description": "Add a reminder to Google Calendar.", "priority": 4}
            ])
        elif 'overwhelmed' in message_lower or 'stress' in message_lower or 'overwhelmed' in mistral_lower:
            suggestions.extend([
                {"action": "Organize thoughts in Notion", "service": "notion", "description": "Create a Notion page to reduce stress.", "priority": 5},
                {"action": "Request support via email", "service": "gmail", "description": "Draft an email for support.", "priority": 4}
            ])
        else:
            suggestions.extend([
                {"action": "Schedule a break", "service": "calendar", "description": "Add a break to your Google Calendar.", "priority": 3},
                {"action": "Discuss concerns on Slack", "service": "slack", "description": "Share challenges on Slack.", "priority": 3}
            ])

    return suggestions

def detect_sentiment(message: str, mistral_response: str = "") -> str:
    message_lower = message.lower()
    mistral_lower = mistral_response.lower()

    if "positive" in mistral_lower:
        return "positive"
    if "negative" in mistral_lower:
        return "negative"

    positive_score = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in message_lower or keyword in mistral_lower)
    negative_score = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in message_lower or keyword in mistral_lower)

    return "positive" if positive_score >= negative_score else "negative"

def extract_crisp_response(mistral_response: str, sentiment: str) -> str:
    """Extract the first sentence from Mistral's response as a crisp line."""
    try:
        sentences = mistral_response.split('.')
        crisp_response = sentences[0].strip()
        if crisp_response and not crisp_response.endswith('!'):
            crisp_response += '!'
        return crisp_response
    except Exception as e:
        logger.error(f"Error extracting crisp response: {str(e)}")
        return "Congratulations on your achievement!" if sentiment == "positive" else "Sorry to hear you're facing challenges!"

def generate_contextual_response(message_lower: str, suggestions: List[Dict], sentiment: str) -> str:
    """Generate a contextual follow-up based on the sentiment, suggestions, and message context."""
    if not suggestions:
        return "Consider planning your next steps to stay on track."

    primary_suggestion = suggestions[0]
    action = primary_suggestion["action"]
    service = primary_suggestion["service"]

    is_celebratory = any(keyword in message_lower for keyword in ["celebrate", "milestone", "success", "achieve"])

    action_lower = action.lower()
    action_phrase = action_lower.replace(service.lower(), "").strip() if service.lower() in action_lower else action_lower

    if sentiment == "positive":
        return f"To celebrate, try to {action_phrase} using {service.capitalize()}." if is_celebratory else f"To stay on track, try to {action_phrase} using {service.capitalize()}."
    return f"To manage this, try to {action_phrase} using {service.capitalize()}."

def generate_contextual_response_enhanced(
    message: str, 
    user_id: str, 
    services: Dict[str, bool]
) -> Dict[str, Any]:
    """Enhanced version with DATA-AI personality and internal API integration"""
    
    try:
        if not message or not isinstance(message, str):
            message = "help"
        if not user_id or not isinstance(user_id, str):
            raise ValueError("Invalid user_id")
        if services is None:
            services = {}
        
        context = get_user_context(user_id)
        context.conversation_count += 1
        message_lower = message.lower()
        
        if any(word in message_lower for word in ["hi", "hello", "hey", "sup"]):
            original_response = "Hi! I can help you with your calendar, emails, and productivity tasks. What would you like to do?"
            enhanced_response = dataai_enhancer.enhance_greeting(user_id, original_response)
            
            suggestions = generate_safe_suggestions(services) if dataai_enhancer.detect_service_intent_smart(message) else []
            
            return {
                "response": enhanced_response,
                "suggestions": suggestions,
                "follow_up_questions": ["What's your main priority today? 🎯"],
                "intent": "greeting",
                "confidence": 0.9
            }
        
        elif any(phrase in message_lower for phrase in ["connected", "connection", "linked", "authenticated"]):
            original_result = handle_connection_status_request(message, services, context)
            original_result["response"] = dataai_enhancer.enhance_connection_status(original_result["response"])
            return original_result
        
        elif dataai_enhancer.detect_service_intent_smart(message):
            if any(phrase in message_lower for phrase in [
                "calendar", "events", "schedule", "upcoming", "my events", "calendar events", "show events"
            ]):
                if services.get("google_calendar"):
                    original_response = "I can show you your calendar events!"
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "calendar")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Check calendar", "service": "google_calendar", "description": "View your upcoming events 📅", "priority": 5}],
                        "follow_up_questions": ["Would you like to see specific dates? 📆"],
                        "intent": "calendar_request",
                        "confidence": 0.9
                    }
                else:
                    original_response = "To view your calendar, please connect your Google Calendar first."
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "calendar")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Connect Google Calendar", "service": "google_calendar", "description": "Enable calendar integration 🔗", "priority": 5}],
                        "follow_up_questions": [],
                        "intent": "calendar_not_connected",
                        "confidence": 0.9
                    }
            
            elif any(phrase in message_lower for phrase in [
                "email", "gmail", "inbox", "messages", "check email", "see emails", "recent emails"
            ]):
                if services.get("gmail"):
                    original_response = "I can help you with your emails!"
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "email")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "List Gmail messages", "service": "gmail", "description": "Check your recent emails 📧", "priority": 5}],
                        "follow_up_questions": ["Would you like to compose a new email? ✍️"],
                        "intent": "email_request",
                        "confidence": 0.9
                    }
                else:
                    original_response = "To access your emails, please connect your Gmail first."
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "email")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Connect Gmail", "service": "gmail", "description": "Enable email integration 🔗", "priority": 5}],
                        "follow_up_questions": [],
                        "intent": "email_not_connected",
                        "confidence": 0.9
                    }
            
            elif any(phrase in message_lower for phrase in [
                "notion", "notes", "document", "page", "notion pages", "my notes", "show pages"
            ]):
                if services.get("notion"):
                    original_response = "I can show you your Notion pages!"
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "notion")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "List Notion pages", "service": "notion", "description": "View your workspace 📝", "priority": 5}],
                        "follow_up_questions": ["Which page would you like to work on? 📄"],
                        "intent": "notion_request",
                        "confidence": 0.9   
                    }
                else:
                    original_response = "To access your Notion workspace, please connect Notion first."
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "notion")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Connect Notion", "service": "notion", "description": "Enable Notion integration 🔗", "priority": 5}],
                        "follow_up_questions": [],
                        "intent": "notion_not_connected",
                        "confidence": 0.9
                    }
            
            elif any(phrase in message_lower for phrase in [
                "slack", "channels", "post to slack", "send slack message"
            ]):
                if services.get("slack"):
                    original_response = "I can help you with Slack!"
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "slack")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "List Slack channels", "service": "slack", "description": "View your Slack channels 💬", "priority": 5}],
                        "follow_up_questions": ["Which channel would you like to post to? 💬"],
                        "intent": "slack_request",
                        "confidence": 0.9
                    }
                else:
                    original_response = "To use Slack, please connect your Slack workspace first."
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "slack")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Connect Slack", "service": "slack", "description": "Enable Slack integration 🔗", "priority": 5}],
                        "follow_up_questions": [],
                        "intent": "slack_not_connected",
                        "confidence": 0.9
                    }
            
            elif any(phrase in message_lower for phrase in [
                "zoom", "video call", "zoom meeting", "create zoom"
            ]):
                if services.get("zoom"):
                    original_response = "I can help you create a Zoom meeting!"
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "zoom")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Create Zoom meeting", "service": "zoom", "description": "Generate a Zoom link 🎥", "priority": 5}],
                        "follow_up_questions": ["When would you like to schedule the meeting? 📅"],
                        "intent": "zoom_request",
                        "confidence": 0.9
                    }
                else:
                    original_response = "To create Zoom meetings, please connect your Zoom account first."
                    enhanced_response = dataai_enhancer.enhance_service_response(message, original_response, "zoom")
                    return {
                        "response": enhanced_response,
                        "suggestions": [{"action": "Connect Zoom", "service": "zoom", "description": "Enable Zoom integration 🔗", "priority": 5}],
                        "follow_up_questions": [],
                        "intent": "zoom_not_connected",
                        "confidence": 0.9
                    }
        
        else:
            original_response = "I can help you with your calendar, emails, or other productivity tasks. What would you like to do?"
            enhanced_response = dataai_enhancer.enhance_general_response(message, original_response)
            
            return {
                "response": enhanced_response,
                "suggestions": [],
                "follow_up_questions": ["What would you like me to help you with? 💡"],
                "intent": "general_help",
                "confidence": 0.7
            }
            
    except Exception as e:
        logger.error(f"Error in generate_contextual_response_enhanced: {str(e)}")
        return {
            "response": f"Oops! 😅 {dataai_enhancer.name} had a tiny hiccup there. I'm still here and ready to help though! What can I do for you? 💪",
            "suggestions": [],
            "follow_up_questions": ["How can I assist you today? ✨"],
            "intent": "fallback",
            "confidence": 0.5
        }

def generate_safe_suggestions(services: Dict[str, bool]) -> List[Dict]:
    """Generate safe suggestions without context tracking"""
    suggestions = []
    
    if services.get("google_calendar"):
        suggestions.append({"action": "Check calendar", "service": "google_calendar", "description": "View your upcoming events", "priority": 5})
    
    if services.get("gmail"):
        suggestions.append({"action": "List Gmail messages", "service": "gmail", "description": "Check your recent emails", "priority": 4})
    
    if services.get("notion"):
        suggestions.append({"action": "List Notion pages", "service": "notion", "description": "View your workspace", "priority": 3})
    
    if services.get("slack"):
        suggestions.append({"action": "List Slack channels", "service": "slack", "description": "View your team channels", "priority": 3})
    
    if services.get("zoom"):
        suggestions.append({"action": "Create Zoom meeting", "service": "zoom", "description": "Generate a Zoom link", "priority": 3})
    
    return suggestions[:2]

def handle_connection_status_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Simplified connection status handler"""
    try:
        if context is None:
            context = ConversationContext()
        
        message_lower = message.lower()
        
        if "calendar" in message_lower:
            if services.get("google_calendar"):
                return {
                    "response": "✅ Yes! Your Google Calendar is connected and ready to use.",
                    "suggestions": [{"action": "Check calendar", "service": "google_calendar", "description": "View your upcoming events", "priority": 5}],
                    "follow_up_questions": ["Would you like to see your events?"],
                    "intent": "calendar_connected",
                    "confidence": 0.9
                }
            else:
                return {
                    "response": "❌ No, your Google Calendar isn't connected yet.",
                    "suggestions": [{"action": "Connect Google Calendar", "service": "google_calendar", "description": "Connect your calendar", "priority": 5}],
                    "follow_up_questions": [],
                    "intent": "calendar_not_connected",
                    "confidence": 0.9
                }
        
        elif "email" in message_lower or "gmail" in message_lower:
            if services.get("gmail"):
                return {
                    "response": "✅ Yes! Your Gmail is connected and ready to use.",
                    "suggestions": [{"action": "List Gmail messages", "service": "gmail", "description": "Check your recent emails", "priority": 5}],
                    "follow_up_questions": ["Would you like to check your inbox?"],
                    "intent": "gmail_connected",
                    "confidence": 0.9
                }
            else:
                return {
                    "response": "❌ No, your Gmail isn't connected yet.",
                    "suggestions": [{"action": "Connect Gmail", "service": "gmail", "description": "Connect your email", "priority": 5}],
                    "follow_up_questions": [],
                    "intent": "gmail_not_connected",
                    "confidence": 0.9
                }
        
        elif "notion" in message_lower:
            if services.get("notion"):
                return {
                    "response": "✅ Yes! Your Notion workspace is connected and ready to use.",
                    "suggestions": [{"action": "List Notion pages", "service": "notion", "description": "View your workspace", "priority": 5}],
                    "follow_up_questions": ["Would you like to see your pages?"],
                    "intent": "notion_connected",
                    "confidence": 0.9
                }
            else:
                return {
                    "response": "❌ No, your Notion workspace isn't connected yet.",
                    "suggestions": [{"action": "Connect Notion", "service": "notion", "description": "Connect your workspace", "priority": 5}],
                    "follow_up_questions": [],
                    "intent": "notion_not_connected",
                    "confidence": 0.9
                }
        
        elif "slack" in message_lower:
            if services.get("slack"):
                return {
                    "response": "✅ Yes! Your Slack workspace is connected and ready to use.",
                    "suggestions": [{"action": "List Slack channels", "service": "slack", "description": "View your channels", "priority": 5}],
                    "follow_up_questions": ["Would you like to post a message?"],
                    "intent": "slack_connected",
                    "confidence": 0.9
                }
            else:
                return {
                    "response": "❌ No, your Slack workspace isn't connected yet.",
                    "suggestions": [{"action": "Connect Slack", "service": "slack", "description": "Connect your workspace", "priority": 5}],
                    "follow_up_questions": [],
                    "intent": "slack_not_connected",
                    "confidence": 0.9
                }
        
        elif "zoom" in message_lower:
            if services.get("zoom"):
                return {
                    "response": "✅ Yes! Your Zoom account is connected and ready to use.",
                    "suggestions": [{"action": "Create Zoom meeting", "service": "zoom", "description": "Generate a Zoom link", "priority": 5}],
                    "follow_up_questions": ["Would you like to schedule a meeting?"],
                    "intent": "zoom_connected",
                    "confidence": 0.9
                }
            else:
                return {
                    "response": "❌ No, your Zoom account isn't connected yet.",
                    "suggestions": [{"action": "Connect Zoom", "service": "zoom", "description": "Connect your account", "priority": 5}],
                    "follow_up_questions": [],
                    "intent": "zoom_not_connected",
                    "confidence": 0.9
                }
        
        connected_count = sum(1 for connected in services.values() if connected)
        if connected_count > 0:
            return {
                "response": f"✅ You have {connected_count} service(s) connected.",
                "suggestions": generate_safe_suggestions(services),
                "follow_up_questions": ["What would you like to do?"],
                "intent": "connection_status",
                "confidence": 0.9
            }
        else:
            return {
                "response": "❌ No services are connected yet.",
                "suggestions": [{"action": "Connect Google Calendar", "service": "google_calendar", "description": "Connect your calendar", "priority": 5}],
                "follow_up_questions": [],
                "intent": "no_connections",
                "confidence": 0.9
            }
            
    except Exception as e:
        logger.error(f"Error in handle_connection_status_request: {str(e)}")
        return {
            "response": "I can help you check your service connections.",
            "suggestions": [],
            "follow_up_questions": [],
            "intent": "connection_error",
            "confidence": 0.5
        }

def handle_user_frustration(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle when user expresses frustration with responses"""
    if context is None:
        context = ConversationContext()
    
    return {
        "response": "I apologize for the confusion! Let me be more helpful. What specific question can I answer for you?",
        "suggestions": [
            {"action": "Check calendar", "service": "google_calendar", "description": "View your events", "priority": 5},
            {"action": "List Gmail messages", "service": "gmail", "description": "Check your emails", "priority": 4},
            {"action": "List Notion pages", "service": "notion", "description": "View your notes", "priority": 3}
        ],
        "follow_up_questions": ["What specific information do you need?", "How can I better assist you?"],
        "intent": "user_frustration",
        "confidence": 0.9
    }

def generate_service_suggestions(service_key: str, context: Optional[ConversationContext] = None) -> List[Dict]:
    """Generate suggestions for a specific connected service"""
    if context is None:
        context = ConversationContext()
    
    if service_key == "google_calendar":
        return [{"action": "Check calendar", "service": "google_calendar", "description": "View your upcoming events", "priority": 5}]
    elif service_key == "gmail":
        return [{"action": "List Gmail messages", "service": "gmail", "description": "Check your recent emails", "priority": 5}]
    elif service_key == "notion":
        return [{"action": "List Notion pages", "service": "notion", "description": "View your workspace", "priority": 5}]
    elif service_key == "slack":
        return [{"action": "List Slack channels", "service": "slack", "description": "View your channels", "priority": 5}]
    elif service_key == "zoom":
        return [{"action": "Create Zoom meeting", "service": "zoom", "description": "Generate a Zoom link", "priority": 5}]
    return []

def generate_fresh_suggestions(
    services: Dict[str, bool], 
    context: Optional[ConversationContext] = None,
    max_suggestions: int = 2
) -> List[Dict]:
    """Generate suggestions that haven't been rejected or repeated"""
    if context is None:
        context = ConversationContext()
    
    suggestions = []
    
    if services.get("google_calendar") and not context.is_rejected("calendar"):
        if not context.already_suggested("check calendar"):
            suggestions.append({"action": "Check calendar", "service": "google_calendar", "description": "Review your upcoming events", "priority": 5})
            context.add_suggested_action("check calendar")
    
    if services.get("gmail") and not context.is_rejected("email"):
        if not context.already_suggested("list gmail messages"):
            suggestions.append({"action": "List Gmail messages", "service": "gmail", "description": "Check your recent emails", "priority": 4})
            context.add_suggested_action("list gmail messages")
    
    if services.get("notion") and not context.is_rejected("notion"):
        if not context.already_suggested("list notion pages"):
            suggestions.append({"action": "List Notion pages", "service": "notion", "description": "View your Notion workspace", "priority": 3})
            context.add_suggested_action("list notion pages")
    
    if services.get("slack") and not context.is_rejected("slack"):
        if not context.already_suggested("list slack channels"):
            suggestions.append({"action": "List Slack channels", "service": "slack", "description": "View your team channels", "priority": 3})
            context.add_suggested_action("list slack channels")
    
    if services.get("zoom") and not context.is_rejected("zoom"):
        if not context.already_suggested("create zoom meeting"):
            suggestions.append({"action": "Create Zoom meeting", "service": "zoom", "description": "Generate a Zoom link", "priority": 3})
            context.add_suggested_action("create zoom meeting")
    
    return sorted(suggestions, key=lambda x: x["priority"], reverse=True)[:max_suggestions]

def generate_minimal_suggestions(
    services: Dict[str, bool], 
    context: Optional[ConversationContext] = None
) -> List[Dict]:
    """Generate only 1-2 most relevant suggestions"""
    return generate_fresh_suggestions(services, context, max_suggestions=1)

def handle_scheduling_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle meeting/scheduling requests specifically"""
    if context is None:
        context = ConversationContext()
    
    if services.get("google_calendar"):
        return {
            "response": "I can help you schedule that meeting! Let me show you your calendar first.",
            "suggestions": [{"action": "Check calendar", "service": "google_calendar", "description": "View available time slots", "priority": 5}],
            "follow_up_questions": ["What time works best for your meeting?"],
            "intent": "schedule_meeting",
            "confidence": 0.9
        }
    return {
        "response": "To help with scheduling, I'll need access to your Google Calendar.",
        "suggestions": [{"action": "Connect Google Calendar", "service": "google_calendar", "description": "Enable calendar integration", "priority": 5}],
        "follow_up_questions": [],
        "intent": "schedule_meeting",
        "confidence": 0.9
    }

def handle_email_management_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle email management requests with Gmail APIs"""
    if context is None:
        context = ConversationContext()
    
    message_lower = message.lower()
    
    if services.get("gmail"):
        if any(phrase in message_lower for phrase in ["list", "show", "inbox", "messages"]):
            return {
                "response": "I'll show you your recent Gmail messages!",
                "suggestions": [{"action": "List Gmail messages", "service": "gmail", "description": "View your recent emails", "priority": 5}],
                "follow_up_questions": ["Would you like to compose a new email?"],
                "intent": "list_gmail_messages",
                "confidence": 0.9
            }
        elif any(phrase in message_lower for phrase in ["compose", "write", "send", "new email"]):
            return {
                "response": "I can help you compose an email!",
                "suggestions": [{"action": "Compose email", "service": "gmail", "description": "Create a new email draft", "priority": 5}],
                "follow_up_questions": ["Who would you like to send this email to?"],
                "intent": "compose_email",
                "confidence": 0.9
            }
        else:
            return {
                "response": "I can help you with your Gmail! What would you like to do?",
                "suggestions": [
                    {"action": "List Gmail messages", "service": "gmail", "description": "View your recent emails", "priority": 5},
                    {"action": "Compose email", "service": "gmail", "description": "Create a new email", "priority": 4}
                ],
                "follow_up_questions": ["Would you like to check your inbox or compose a new email?"],
                "intent": "email_management",
                "confidence": 0.9
            }
    return {
        "response": "To help with emails, please connect your Gmail account first.",
        "suggestions": [{"action": "Connect Gmail", "service": "gmail", "description": "Enable Gmail integration", "priority": 5}],
        "follow_up_questions": [],
        "intent": "email_management",
        "confidence": 0.9
    }

def handle_slack_management_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle Slack management requests with Slack APIs"""
    if context is None:
        context = ConversationContext()
    
    message_lower = message.lower()
    
    if services.get("slack"):
        if any(phrase in message_lower for phrase in ["channels", "list", "show"]):
            return {
                "response": "I'll show you your Slack channels!",
                "suggestions": [{"action": "List Slack channels", "service": "slack", "description": "View your Slack channels", "priority": 5}],
                "follow_up_questions": ["Which channel would you like to post to?"],
                "intent": "list_slack_channels",
                "confidence": 0.9
            }
        elif any(phrase in message_lower for phrase in ["post", "send", "message"]):
            return {
                "response": "I can help you post a message to Slack!",
                "suggestions": [{"action": "Post to Slack", "service": "slack", "description": "Send a message to a channel", "priority": 5}],
                "follow_up_questions": ["What message would you like to send?"],
                "intent": "post_slack_message",
                "confidence": 0.9
            }
        else:
            return {
                "response": "I can help you with Slack! What would you like to do?",
                "suggestions": [
                    {"action": "List Slack channels", "service": "slack", "description": "View your channels", "priority": 5},
                    {"action": "Post to Slack", "service": "slack", "description": "Send a message", "priority": 4}
                ],
                "follow_up_questions": ["Would you like to see your channels or post a message?"],
                "intent": "slack_management",
                "confidence": 0.9
            }
    return {
        "response": "To help with Slack, please connect your Slack workspace first.",
        "suggestions": [{"action": "Connect Slack", "service": "slack", "description": "Enable Slack integration", "priority": 5}],
        "follow_up_questions": [],
        "intent": "slack_management",
        "confidence": 0.9
    }

def handle_email_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """DEPRECATED: Use handle_email_management_request instead"""
    if context is None:
        context = ConversationContext()
    
    logger.warning("handle_email_request is deprecated; use handle_email_management_request")
    return handle_email_management_request(message, services, context)

def handle_document_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle document/note creation requests"""
    if context is None:
        context = ConversationContext()
    
    if services.get("notion"):
        return {
            "response": "I can help you create that document in Notion!",
            "suggestions": [{"action": "Create Notion page", "service": "notion", "description": "Start a new document", "priority": 5}],
            "follow_up_questions": ["What's the document about?"],
            "intent": "create_document",
            "confidence": 0.9
        }
    return {
        "response": "To create documents, please connect your Notion workspace first.",
        "suggestions": [{"action": "Connect Notion", "service": "notion", "description": "Enable document creation", "priority": 5}],
        "follow_up_questions": [],
        "intent": "create_document",
        "confidence": 0.9
    }

def handle_notion_pages_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle Notion pages listing requests specifically"""
    if context is None:
        context = ConversationContext()
    
    if services.get("notion"):
        return {
            "response": "I'll show you your Notion pages right away!",
            "suggestions": [{"action": "List Notion pages", "service": "notion", "description": "View all your Notion pages", "priority": 5}],
            "follow_up_questions": ["Which page would you like to work on?"],
            "intent": "list_notion_pages",
            "confidence": 0.9
        }
    return {
        "response": "To view your Notion pages, I'll need access to your Notion workspace first.",
        "suggestions": [{"action": "Connect Notion", "service": "notion", "description": "Enable Notion integration to view your pages", "priority": 5}],
        "follow_up_questions": [],
        "intent": "list_notion_pages",
        "confidence": 0.9
    }

def handle_calendar_events_request(message: str, services: Dict[str, bool], context: Optional[ConversationContext] = None) -> Dict:
    """Handle calendar events listing requests specifically"""
    if context is None:
        context = ConversationContext()
    
    if services.get("google_calendar"):
        return {
            "response": "Let me fetch your calendar events for you!",
            "suggestions": [{"action": "Check calendar", "service": "google_calendar", "description": "View your upcoming events", "priority": 5}],
            "follow_up_questions": ["Would you like to see events for a specific date range?"],
            "intent": "list_calendar_events",
            "confidence": 0.9
        }
    return {
        "response": "To view your calendar events, I'll need access to your Google Calendar first.",
        "suggestions": [{"action": "Connect Google Calendar", "service": "google_calendar", "description": "Enable Google Calendar integration", "priority": 5}],
        "follow_up_questions": [],
        "intent": "list_calendar_events",
        "confidence": 0.9
    }

async def chat_with_mistral(message: str, user_id: str) -> Dict[str, Any]:
    """Chat with Mistral API with DATA-AI enhancement"""
    mistral_response = "I couldn't process the request due to an error."
    suggestions = []
    notion_pages = []
    message_lower = message.lower()

    try:
        messages = [
            {
                "role": "system",
                "content": "You are DATA-AI, a helpful and cheerful productivity assistant. Analyze the user's message, determine their sentiment (positive or negative), and provide a conversational response with actionable suggestions to improve their productivity. Add appropriate emojis and maintain an enthusiastic tone. Suggestions should involve services like Google Calendar, Notion, Gmail, or Slack."
            },
            {"role": "user", "content": message}
        ]

        start_time = asyncio.get_event_loop().time()

        try:
            suggestions = generate_action_suggestions(message)
        except Exception as e:
            logger.error(f"Error generating initial suggestions for user {user_id}: {str(e)}")
            suggestions = []

        try:
            mistral_task = asyncio.create_task(call_mistral_api(messages))
        except Exception as e:
            logger.error(f"Error creating Mistral API task for user {user_id}: {str(e)}")
            mistral_task = asyncio.create_task(asyncio.sleep(0))
            mistral_response = "Failed to initiate Mistral API request."

        try:
            notion_task = asyncio.create_task(fetch_notion_pages(user_id=user_id)) if any(s["service"] == "notion" for s in suggestions) else asyncio.ensure_future(asyncio.sleep(0))
        except Exception as e:
            logger.error(f"Error creating Notion pages task for user {user_id}: {str(e)}")
            notion_task = asyncio.ensure_future(asyncio.sleep(0))

        try:
            response, notion_pages = await asyncio.gather(mistral_task, notion_task, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error gathering async tasks for user {user_id}: {str(e)}")
            response = None

        if isinstance(response, Exception):
            logger.error(f"Mistral API task failed for user {user_id}: {str(response)}")
            mistral_response = "I couldn't process the request due to a server error."
        else:
            try:
                if response is None:
                    logger.error(f"Mistral API response is None for user {user_id}")
                    mistral_response = "Mistral API returned no response."
                else:
                    mistral_response = response.get("choices", [{}])[0].get("message", {}).get("content", "I couldn't process the response from the assistant.")
                    if not isinstance(mistral_response, str):
                        logger.error(f"Mistral response content is not a string for user {user_id}: {mistral_response}")
                        mistral_response = "I couldn't process the response from the assistant."
            except (KeyError, TypeError, IndexError) as e:
                logger.error(f"Error parsing Mistral API response for user {user_id}: {str(e)}")
                mistral_response = "I couldn't process the response from the assistant."

        end_time = asyncio.get_event_loop().time()
        logger.info(f"chat_with_mistral parallel tasks completed in {end_time - start_time:.2f} seconds for user {user_id}")

        sentiment = detect_sentiment(message, mistral_response)
        confidence = 0.9

        try:
            suggestions = generate_sentiment_based_suggestions(message, sentiment, mistral_response)
        except Exception as e:
            logger.error(f"Error generating sentiment-based suggestions for user {user_id}: {str(e)}")

        if any(s["service"] == "notion" for s in suggestions) and not isinstance(notion_task, asyncio.Future):
            try:
                notion_pages = await fetch_notion_pages(user_id=user_id)
            except Exception as e:
                logger.error(f"Error fetching Notion pages after suggestions refined for user {user_id}: {str(e)}")
                notion_pages = []

        if not isinstance(notion_pages, list):
            logger.warning(f"notion_pages is not a list for user {user_id}: {notion_pages}")
            notion_pages = []
        notion_page_options = [{"id": page.get("id", ""), "title": page.get("title", "")} for page in notion_pages if isinstance(page, dict)]

        crisp_response = extract_crisp_response(mistral_response, sentiment)
        enhanced_mistral = enhance_mistral_response_with_dataai(mistral_response, message)
        contextual_response = generate_contextual_response(message_lower, suggestions, sentiment)
        final_response = f"{enhanced_mistral} {contextual_response}"

        return {
            "message": message,
            "sentiment": sentiment,
            "confidence": confidence,
            "response": final_response,
            "suggestions": suggestions,
            "notion_pages": notion_page_options
        }
    
    except Exception as e:
        logger.error(f"Error in chat_with_mistral for user {user_id}: {str(e)}")
        suggestions = generate_action_suggestions(message)
        try:
            notion_pages = await fetch_notion_pages(user_id=user_id) if any(s["service"] == "notion" for s in suggestions) else []
        except Exception as e:
            logger.error(f"Error fetching Notion pages in fallback for user {user_id}: {str(e)}")
            notion_pages = []

        if not isinstance(notion_pages, list):
            logger.warning(f"notion_pages is not a list in fallback for user {user_id}: {notion_pages}")
            notion_pages = []
        notion_page_options = [{"id": page.get("id", ""), "title": page.get("title", "")} for page in notion_pages if isinstance(page, dict)]

        sentiment = detect_sentiment(message)
        confidence = 0.9

        try:
            suggestions = generate_sentiment_based_suggestions(message, sentiment)
        except Exception as e:
            logger.error(f"Error generating sentiment-based suggestions in fallback for user {user_id}: {str(e)}")

        crisp_response = f"Oops! 😅 DATA-AI had a small hiccup, but I'm still here to help! 💪"
        contextual_response = generate_contextual_response(message_lower, suggestions, sentiment)
        final_response = f"{crisp_response} {contextual_response}"

        return {
            "message": message,
            "sentiment": sentiment,
            "confidence": confidence,
            "response": final_response,
            "suggestions": suggestions,
            "notion_pages": notion_page_options
        }

async def process_user_message(message: str, user_id: str) -> Dict[str, Any]:
    """Process user message and return structured response"""
    try:
        message_lower = message.lower()
        updates = []

        start_date = None
        end_date = None
        if "today's events" in message_lower or "what are my events today" in message_lower:
            start_date = date.today().strftime('%Y-%m-%d')
            end_date = start_date
            date_range = "today"
        elif "tomorrow" in message_lower:
            tomorrow = date.today() + timedelta(days=1)
            start_date = tomorrow.strftime('%Y-%m-%d')
            end_date = start_date
            date_range = "tomorrow"
        elif "all the available events" in message_lower:
            start_date = date.today().strftime('%Y-%m-%d')
            end_date = (date.today() + timedelta(days=30)).strftime('%Y-%m-%d')
            date_range = "the next 30 days"
        else:
            date_range = "tomorrow"

        if "updates" in message_lower or "events" in message_lower:
            start_time = asyncio.get_event_loop().time()
            events = await fetch_calendar_events(start_date, end_date, user_id=user_id)
            end_time = asyncio.get_event_loop().time()
            logger.info(f"fetch_calendar_events completed in {end_time - start_time:.2f} seconds for user {user_id}")

            suggestions = []
            if events:
                response = f"Here's a summary of your updates for {date_range}:\n\n"
                for idx, event in enumerate(events, 1):
                    event_summary = event.get("summary", "Untitled Event").strip()
                    start_time = event.get("start", "Unknown Time")
                    updates.append(f"{idx}. Meeting: {event_summary} at {start_time}. You can join via the link: {event.get('link', 'No link available')}.")
                    event_suggestions = generate_action_suggestions(event_summary)
                    for suggestion in event_suggestions:
                        suggestion["event_summary"] = event_summary
                        suggestion["calendar_link"] = event.get("link", "")
                    suggestions.extend(event_suggestions)
            else:
                updates.append(f"No calendar events found for {date_range}.")

            start_time = asyncio.get_event_loop().time()
            notion_tasks = await fetch_notion_tasks(user_id=user_id)
            end_time = asyncio.get_event_loop().time()
            logger.info(f"fetch_notion_tasks completed in {end_time - start_time:.2f} seconds for user {user_id}")

            if notion_tasks:
                for idx, task in enumerate(notion_tasks, len(updates) + 1):
                    title = task.get("title", "Untitled Task")
                    section = task.get("section", "Unknown Section")
                    updates.append(f"{idx}. In Notion, there's a task assigned to you for {title}. Details in the \"{section}\" section.")

            start_time = asyncio.get_event_loop().time()
            drive_deadlines = await fetch_drive_deadlines(user_id=user_id)
            end_time = asyncio.get_event_loop().time()
            logger.info(f"fetch_drive_deadlines completed in {end_time - start_time:.2f} seconds for user {user_id}")

            if drive_deadlines:
                for idx, deadline in enumerate(drive_deadlines, len(updates) + 1):
                    title = deadline.get("title", "Untitled Deadline")
                    folder = deadline.get("folder", "Unknown Folder")
                    updates.append(f"{idx}. Don't forget about the deadline for {title}. Work on it in the Google Drive folder '{folder}'.")

            if updates:
                response = "\n\n".join(updates)
                response += "\n\nRemember, it's always a good idea to check your Gmail inbox for any last-minute updates or changes. If you need help managing your tasks or scheduling, feel free to ask. DATA-AI is here to assist you! 🚀"
            else:
                response = f"No updates found for {date_range}."

            notion_pages = await fetch_notion_pages(user_id=user_id) if any(s["service"] == "notion" for s in suggestions) else []
            if not isinstance(notion_pages, list):
                logger.warning(f"notion_pages is not a list in process_user_message for user {user_id}: {notion_pages}")
                notion_pages = []
            notion_page_options = [{"id": page.get("id", ""), "title": page.get("title", "")} for page in notion_pages if isinstance(page, dict)]

            return {
                "response": response.strip(),
                "suggestions": suggestions,
                "notion_pages": notion_page_options if suggestions else []
            }

        return await chat_with_mistral(message, user_id)
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing user message for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")