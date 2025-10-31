import os
import json
import logging
import time
import difflib
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import requests
from openai import OpenAI as OpenAIClient # NEW: Import the client
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# Google Calendar imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# -------------------- Configuration & Logging --------------------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON_PATH")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"] # Removed trailing space
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

# NEW: Create a client instance
openai_client = OpenAIClient(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Safety: simple rate limiter per user
USER_LAST_REQUEST = {}
RATE_LIMIT_SECONDS = 1.0

# -------------------- Utilities --------------------

def rate_limit_ok(user_id: int) -> bool:
    now = time.time()
    last = USER_LAST_REQUEST.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return False
    USER_LAST_REQUEST[user_id] = now
    return True


def clean_text(text: str) -> str:
    return text.strip()


# -------------------- Notion Integration (Fetch All Titles) --------------------
NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

def notion_query_database() -> List[Dict[str, Any]]:
    """Fetch all pages from the Notion database."""
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        logger.warning("Notion API credentials not set.")
        return []
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    url = f"{NOTION_BASE_URL}/databases/{NOTION_DATABASE_ID}/query"
    try:
        res = requests.post(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        results = data.get("results", [])
        pages = []
        for p in results:
            title = None
            content_text = ""
            properties = p.get("properties", {})
            for k, v in properties.items():
                if v.get("type") == "title":
                    title_parts = v.get("title", [])
                    title = "".join([t.get("plain_text", "") for t in title_parts])
                if v.get("type") == "rich_text":
                    content_text = "".join([t.get("plain_text", "") for t in v.get("rich_text", [])])
            if not title:
                title = p.get("id")
            pages.append({"id": p.get("id"), "title": title, "content": content_text, "raw": p})
        return pages
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from Notion: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching from Notion: {e}")
        return []

def get_notion_titles() -> List[str]:
    """Extract titles from Notion pages."""
    pages = notion_query_database()
    return [page["title"] for page in pages if page["title"]]

def get_notion_content_by_title(title: str) -> Optional[str]:
    """Find a page by its exact title and return its content."""
    pages = notion_query_database()
    for p in pages:
        if p["title"] == title:
            return p.get("content", "")
    return None


# -------------------- Google Calendar Integration (search + helpers) --------------------
TOKEN_PICKLE = "token.json"

def get_calendar_service():
    creds = None
    logger.info(f"Looking for token file: {TOKEN_PICKLE}")
    logger.info(f"Using credentials file: {GOOGLE_CREDENTIALS_JSON}")

    if os.path.exists(TOKEN_PICKLE):
        logger.info("Found existing token file")
        creds = Credentials.from_authorized_user_file(TOKEN_PICKLE, SCOPES)
    else:
        logger.info("No token file found")

    if not creds or not creds.valid:
        logger.info(f"Credentials valid: {creds.valid if creds else 'No creds'}")
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials")
            creds.refresh(Request())
        else:
            logger.info("Starting OAuth flow")
            if not GOOGLE_CREDENTIALS_JSON or not os.path.exists(GOOGLE_CREDENTIALS_JSON):
                raise FileNotFoundError(f"Google credentials file not found: {GOOGLE_CREDENTIALS_JSON}")
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_JSON, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PICKLE, "w") as token:
                token.write(creds.to_json())
            logger.info("OAuth flow completed, token saved")

    logger.info("Building calendar service")
    service = build("calendar", "v3", credentials=creds)
    return service


def normalize_subject_variants(subject: str) -> List[str]:
    """Return a list of normalized subject variants to match abbreviations."""
    s = subject.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    variants = {s}
    # common expansions
    variants.add(s.replace("&", " and "))
    variants.add(s.replace("ml", "machine learning"))
    variants.add(s.replace("ai", "artificial intelligence"))
    variants.add(s.replace("dbms", "database management"))
    # split tokens and join subsets (to allow "ai ml" vs "aiml")
    tokens = [t for t in re.findall(r"\w+", s) if t]
    if tokens:
        variants.add(" ".join(tokens))
    return list(variants)


def search_calendar_events(subject_name: str, lookahead_days: int = 90, max_results: int = 200) -> Dict[str, Any]: # Return type changed to Dict
    """
    Return a dictionary containing 'found' (bool) and 'events' (List[Dict]).
    Matching requires token overlap or normalized-match to accept an event.
    This prevents unrelated generic exam events from being picked.
    """
    logger.info(f"Attempting to fetch calendar events for subject: {subject_name}")
    try:
        service = get_calendar_service()
        logger.info("Calendar service built successfully")
    except Exception as e:
        logger.exception("Calendar auth failed: %s", e)
        # Return an empty result object as expected by the caller
        return {"found": False, "events": []}

    try:
        now = datetime.utcnow().isoformat() + "Z"
        max_time = (datetime.utcnow() + timedelta(days=lookahead_days)).isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary", timeMin=now, timeMax=max_time, singleEvents=True, orderBy="startTime", maxResults=max_results
        ).execute()
        events = events_result.get("items", [])
        logger.info(f"Fetched {len(events)} events from Google Calendar")
    except Exception as e:
        logger.exception("Failed to fetch calendar events: %s", e)
        # Return an empty result object as expected by the caller
        return {"found": False, "events": []}

    subject_lower = subject_name.lower()
    subject_tokens = set(re.findall(r"\w+", subject_lower))
    keywords = {"exam", "test", "midterm", "final", "viva", "quiz", "paper", "assessment", "evaluation"}
    # IMPORTANT: Use the subject_name passed to the function for normalization
    normalized_variants = normalize_subject_variants(subject_name)

    scored = []
    for e in events:
        summary = (e.get("summary") or "").lower()
        if not summary:
            continue

        # tokenize summary
        summary_tokens = set(re.findall(r"\w+", summary))

        # token overlap (strict requirement for match)
        token_overlap = len(subject_tokens & summary_tokens)

        # normalized matching (variant present in summary)
        normalized_match = any(variant in summary for variant in normalized_variants)

        # direct substring match
        direct_match = subject_lower in summary or any(v in summary for v in normalized_variants)

        # similarity ratio (fallback)
        ratio = difflib.SequenceMatcher(None, subject_lower, summary).ratio()

        # keyword presence
        keyword_bonus = sum(0.2 for k in keywords if k in summary)

        # Decide whether this event should be considered at all.
        # REQUIRE: token_overlap >= 1 OR normalized_match OR direct_match
        if token_overlap < 1 and not normalized_match and not direct_match:
            # skip this event: likely unrelated (e.g., a generic "exam" event for a different subject)
            logger.debug(f"Skipping event '{summary}' due to no token overlap/normalized match (tokens overlap={token_overlap})")
            continue

        # compute score
        # token_overlap contributes significantly; ratio + keyword bonus refine ranking
        score = 0.0
        score += 0.5 * (token_overlap)  # token overlap strong signal
        score += 0.5 * ratio
        score += keyword_bonus

        # keep event
        e_copy = dict(e)
        e_copy["score"] = score
        scored.append(e_copy)

    # sort by score desc
    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Found {len(scored)} candidate matching events for '{subject_name}' after filtering")
    # Return the structured result as expected by the caller
    return {"found": True, "events": scored} if scored else {"found": False, "events": []}


def extract_iso_from_event(e: Dict[str, Any]) -> Optional[str]:
    start = e.get("start", {})
    if start.get("dateTime"):
        return start["dateTime"]
    if start.get("date"):
        return start["date"] + "T00:00:00Z"
    return None


# -------------------- OpenAI Integration (summary & plan) --------------------
def openai_moderation_check(text: str) -> bool:
    try:
        # NEW: Use the client instance
        resp = openai_client.moderations.create(input=text)
        results = resp.results[0] # Access the first result from the list
        flagged = results.flagged
        logger.warning(f"[MODERATION] flagged={flagged} | categories={results.categories.model_dump()}")
        dangerous = results.category_scores.self_harm > 0.7 or results.category_scores.violence > 0.8
        return not dangerous
    except Exception as e:
        logger.exception("Moderation check failed: %s", e)
        # fail-open for study content
        return True


def generate_summary(page_title: str, page_content: str) -> str:
    prompt = f"Summarize the following study notes titled: {page_title}\n\n{page_content}\n\nProduce a concise summary with bullet points and 3 key takeaways. Do not use ** for formatting."
    if not openai_moderation_check(page_content):
        raise ValueError("Content failed moderation.")
    # NEW: Use the client instance
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an efficient study assistant. Output should be plain text, no markdown formatting like **."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
        temperature=0.2,
    )
    summary_text = resp.choices[0].message.content.strip()
    # Remove ** formatting if present
    import re
    summary_text = re.sub(r'\*\*(.*?)\*\*', r'\1', summary_text)
    return summary_text


def generate_plan(subject: str, content: Optional[str], exam_date_iso: Optional[str]) -> str: # Removed hours_per_day parameter
    if exam_date_iso:
        try:
            exam_dt = datetime.fromisoformat(exam_date_iso.replace("Z", "+00:00"))
            days_left = max(1, (exam_dt.date() - datetime.utcnow().date()).days)
        except Exception:
            days_left = 14
    else:
        days_left = 14

    prompt = (
        f"Create a concise {days_left}-day study plan for '{subject}'.\n"
        # Removed: f"Student can study {hours_per_day} hours/day.\n"
    )

    if content and len(content.strip()) > 10:
        prompt += f"CRITICAL: Your plan MUST be derived EXCLUSIVELY from the following specific notes provided for '{subject}'. IGNORE any general knowledge about '{subject}' and ONLY use the topics/concepts found in the notes below:\n---\n{content}\n---\n"
        prompt += f"Structure the {days_left}-day plan to cover the topics/concepts from the provided notes sequentially or logically over the available days. Assign specific topics from the notes to each day. Each day's entry should be one line: 'Day X: [Topic from notes] - [Suggested action based on notes, e.g., Review, Practice, Read, etc.]'."
    else:
        prompt += f"No specific notes were provided for '{subject}'. Create a general study plan based on common curriculum topics for this subject. Each day's entry should be one line: 'Day X: [General Topic] - [Suggested action, e.g., Review, Practice, Read, etc.]'."

    prompt += "\nDo not use ** for formatting."

    if not openai_moderation_check(prompt):
        raise ValueError("Plan request failed moderation.")
    # NEW: Use the client instance
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are an experienced study coach. Output should be plain text, no markdown formatting like **."}, {"role": "user", "content": prompt}],
        max_tokens=650,
        temperature=0.25,
    )
    plan_text = resp.choices[0].message.content.strip()
    # Remove ** formatting if present
    import re
    plan_text = re.sub(r'\*\*(.*?)\*\*', r'\1', plan_text)
    return plan_text


# -------------------- Tools --------------------
class Tools:
    @staticmethod
    def fetch_notion_content_by_title(title: str) -> Optional[str]:
        # Use the new function
        return get_notion_content_by_title(title)

    @staticmethod
    def get_notion_titles() -> List[str]:
        # Use the new function
        return get_notion_titles()

    @staticmethod
    def fetch_exam_candidates(subject: str) -> Dict[str, Any]: # Return type updated
        # Call the corrected search function
        return search_calendar_events(subject_name=subject)

    @staticmethod
    def create_summary(page_title: str, page_content: str) -> Dict[str, Any]:
        try:
            summary = generate_summary(page_title, page_content)
            return {"ok": True, "summary": summary}
        except ValueError:
            return {"ok": False, "reason": "moderation_failed"}
        except Exception as exc:
            logger.exception("Summary generation failed")
            return {"ok": False, "reason": str(exc)}

    @staticmethod
    def create_plan(subject: str, content: Optional[str], exam_start_iso: Optional[str]) -> Dict[str, Any]: # Removed hours_per_day parameter
        try:
            plan = generate_plan(subject, content, exam_start_iso) # Removed hours_per_day argument
            return {"ok": True, "plan": plan}
        except ValueError:
            return {"ok": False, "reason": "moderation_failed"}
        except Exception as exc:
            logger.exception("Plan generation failed")
            return {"ok": False, "reason": str(exc)}


# -------------------- Telegram Handlers --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I'm your AI Study Companion. Use /summary or /plan to select from your notes.")


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is working! Commands are being received.")


async def debug_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not rate_limit_ok(user_id):
        await update.message.reply_text("You're sending commands too fast — please wait a moment.")
        return
    await update.message.reply_text("Testing Google Calendar connection...")
    try:
        result = test_calendar_connection()
        if result["success"]:
            await update.message.reply_text(f"✅ Calendar connection successful! Found {result['event_count']} events in the next 30 days.")
        else:
            await update.message.reply_text(f"❌ Calendar connection failed: {result['error']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error during calendar test: {str(e)}")


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not rate_limit_ok(user_id):
        await update.message.reply_text("You're sending commands too fast — please wait a moment.")
        return

    # Fetch all available titles from Notion
    await update.message.reply_text("Fetching your notes from Notion...")
    titles = Tools.get_notion_titles()

    if not titles:
        await update.message.reply_text("No notes found in your Notion database.")
        return

    # Create inline keyboard with titles
    keyboard = []
    for title in titles:
        keyboard.append([InlineKeyboardButton(title, callback_data=f"select_summary_note||{title}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a note to summarize:", reply_markup=reply_markup)


async def plan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not rate_limit_ok(user_id):
        await update.message.reply_text("You're sending commands too fast — please wait a moment.")
        return

    # Fetch all available titles from Notion
    await update.message.reply_text("Fetching your notes from Notion...")
    titles = Tools.get_notion_titles()

    if not titles:
        await update.message.reply_text("No notes found in your Notion database.")
        return

    # Create inline keyboard with titles
    keyboard = []
    for title in titles:
        keyboard.append([InlineKeyboardButton(title, callback_data=f"select_plan_note||{title}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a note to create a study plan:", reply_markup=reply_markup)


def split_text_into_chunks(text: str, max_len: int = 3500) -> List[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start: start + max_len])
        start += max_len
    return chunks


# Callback query handler - unified
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    logger.info("Callback data received: %s", data)

    # Handle selection of a note for summary
    if data.startswith("select_summary_note||"):
        title = data.split("||", 1)[1]
        await query.edit_message_text(f"Selected note: {title}. Fetching content...")
        
        content = Tools.fetch_notion_content_by_title(title)
        if not content or not content.strip():
            await query.message.reply_text(f"Found the note '{title}' but it has no extractable content.")
            return

        await query.message.reply_text(f"Generating summary for: {title}...")
        result = Tools.create_summary(title, content)
        if not result.get("ok"):
            reason = result.get("reason")
            if reason == "moderation_failed":
                await query.message.reply_text("The content appears sensitive and cannot be processed by the bot. I'll notify the admin for manual review.")
                if ADMIN_TELEGRAM_ID:
                    await context.bot.send_message(ADMIN_TELEGRAM_ID, f"User {update.effective_user.id} attempted to summarize sensitive content titled: {title}")
                return
            else:
                await query.message.reply_text(f"Failed to generate summary: {reason}")
                return
        summary = result["summary"]
        for chunk in split_text_into_chunks(summary, 3500):
            await query.message.reply_text(chunk)
        # Optional: Add a button to create a plan for the same subject
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Create study plan for this note", callback_data=f"plan_after_summary_note||{title}")]])
        await query.message.reply_text("What next?", reply_markup=keyboard)
        return

    # Handle selection of a note for plan
    if data.startswith("select_plan_note||"):
        title = data.split("||", 1)[1]
        await query.edit_message_text(f"Selected note: {title}. Fetching content and checking calendar...")
        
        content = Tools.fetch_notion_content_by_title(title)
        if not content:
            content = "" # Provide empty string if not found

        context.user_data["plan_notion_content"] = content
        context.user_data["plan_subject"] = title # Store the selected title as subject
        logger.info(f"Fetched Notion content for '{title}': {repr(content[:100])}...") # Log the first 100 chars of content for debugging

        # Use Tools class method which calls search_calendar_events
        candidates = Tools.fetch_exam_candidates(title) # Use the selected title as the search subject
        logger.info(f"Calendar search result for '{title}': {candidates}") # Add logging here

        # Check the structure returned by Tools.fetch_exam_candidates
        if not candidates.get("found"):
            await query.message.reply_text(f"No upcoming calendar event found for '{title}'. Please reply with your exam date in YYYY-MM-DD format.")
            context.user_data["awaiting_exam_date_for"] = title
            return

        events = candidates.get("events", []) # Get events from the dictionary

        if not events:
            await query.message.reply_text(f"No matching calendar events found for '{title}'. Please reply with your exam date in YYYY-MM-DD format.")
            context.user_data["awaiting_exam_date_for"] = title
            return

        if len(events) == 1:
            e = events[0]
            iso = extract_iso_from_event(e)
            context.user_data["plan_exam_date_iso"] = iso
            await query.edit_message_text(f"Found event: {e.get('summary')} on {iso.split('T')[0]}")
            # NEW: Directly proceed to plan generation
            await query.edit_message_text("Generating plan — please wait...")
            content = context.user_data.get("plan_notion_content", "")
            result = Tools.create_plan(title, content, iso) # Removed hours_per_day argument
            if not result.get("ok"):
                if result.get("reason") == "moderation_failed":
                    await query.message.reply_text("The request seems to be blocked by safety checks. Admin alerted.")
                    if ADMIN_TELEGRAM_ID:
                        await context.bot.send_message(ADMIN_TELEGRAM_ID, f"User {update.effective_user.id} attempted create_plan but failed moderation for subject {title}.")
                    return
                else:
                    await query.message.reply_text(f"Failed to generate plan: {result.get('reason')}")
                    return
            plan = result["plan"]
            await query.edit_message_text(f"📘 Study Plan for {title}\n\n{plan}")
            return

        # Multiple events found
        context.user_data["last_search_events"] = events
        buttons = []
        for idx, e in enumerate(events[:6]):
            iso = extract_iso_from_event(e) or "unknown"
            label = f"{e.get('summary')[:40]} — {iso.split('T')[0]}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"select_event||{idx}||{title}")])
        buttons.append([InlineKeyboardButton("None of these — I'll type date", callback_data=f"select_event||manual||{title}")])
        await query.edit_message_text("Multiple matches found. Please pick the correct event:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Handle plan_after_summary for a selected note
    if data.startswith("plan_after_summary_note||"):
        title = data.split("||", 1)[1]
        await query.edit_message_text(f"Creating plan for: {title}. Checking calendar...")
        
        content = Tools.fetch_notion_content_by_title(title)
        if not content:
            content = "" # Provide empty string if not found
        context.user_data["plan_notion_content"] = content
        context.user_data["plan_subject"] = title
        logger.info(f"Fetched Notion content for '{title}' (after summary): {repr(content[:100])}...") # Log the first 100 chars of content for debugging

        candidates = Tools.fetch_exam_candidates(title) # Use the selected title as the search subject
        logger.info(f"Calendar search result for '{title}' (after summary): {candidates}") # Add logging here

        if not candidates.get("found") or not candidates.get("events"):
            context.user_data["awaiting_exam_date_for"] = title
            await query.message.reply_text("No calendar event found. Please reply with exam date (YYYY-MM-DD).")
            return

        events = candidates.get("events", []) # Get events from the dictionary
        if len(events) == 1:
            iso = extract_iso_from_event(events[0])
            context.user_data["plan_exam_date_iso"] = iso
            await query.edit_message_text("Generating plan — please wait...")
            content = context.user_data.get("plan_notion_content", "")
            result = Tools.create_plan(title, content, iso) # Removed hours_per_day argument
            if not result.get("ok"):
                if result.get("reason") == "moderation_failed":
                    await query.message.reply_text("The request seems to be blocked by safety checks. Admin alerted.")
                    if ADMIN_TELEGRAM_ID:
                        await context.bot.send_message(ADMIN_TELEGRAM_ID, f"User {update.effective_user.id} attempted create_plan but failed moderation for subject {title}.")
                    return
                else:
                    await query.message.reply_text(f"Failed to generate plan: {result.get('reason')}")
                    return
            plan = result["plan"]
            await query.edit_message_text(f"📘 Study Plan for {title}\n\n{plan}")
            return

        # Multiple events found
        context.user_data["last_search_events"] = events
        buttons = []
        for idx, e in enumerate(events[:6]):
            iso = extract_iso_from_event(e) or "unknown"
            label = f"{e.get('summary')[:40]} — {iso.split('T')[0]}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"select_event||{idx}||{title}")])
        buttons.append([InlineKeyboardButton("None of these — I'll type date", callback_data=f"select_event||manual||{title}")])
        await query.edit_message_text("Multiple matches found. Please pick the correct event:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # choose event from list
    if data.startswith("select_event||"):
        parts = data.split("||", 2)
        choice = parts[1]
        subject = parts[2] if len(parts) > 2 else context.user_data.get("plan_subject")
        if choice == "manual":
            context.user_data["awaiting_exam_date_for"] = subject
            await query.edit_message_text("Please reply in chat with your exam date in YYYY-MM-DD format.")
            return
        try:
            idx = int(choice)
        except Exception:
            await query.edit_message_text("Selection invalid. Please /plan again.")
            return
        events = context.user_data.get("last_search_events", [])
        if idx < 0 or idx >= len(events):
            await query.edit_message_text("Selection out of range. Please /plan again.")
            return
        chosen = events[idx]
        iso = extract_iso_from_event(chosen)
        context.user_data["plan_exam_date_iso"] = iso
        context.user_data["plan_subject"] = subject
        await query.edit_message_text(f"Selected: {chosen.get('summary')} on {iso.split('T')[0]}")
        # NEW: Directly proceed to plan generation
        await query.edit_message_text("Generating plan — please wait...")
        content = context.user_data.get("plan_notion_content", "")
        result = Tools.create_plan(subject, content, iso) # Removed hours_per_day argument
        if not result.get("ok"):
            if result.get("reason") == "moderation_failed":
                await query.message.reply_text("The request seems to be blocked by safety checks. Admin alerted.")
                if ADMIN_TELEGRAM_ID:
                    await context.bot.send_message(ADMIN_TELEGRAM_ID, f"User {update.effective_user.id} attempted create_plan but failed moderation for subject {subject}.")
                return
            else:
                await query.message.reply_text(f"Failed to generate plan: {result.get('reason')}")
                return
        plan = result["plan"]
        await query.edit_message_text(f"📘 Study Plan for {subject}\n\n{plan}")
        return

    # hours selection REMOVED
    # if data.startswith("hours_select||"):
    #     # ... old logic ...

    await query.message.reply_text("I didn't recognise that action. Please retry or send /plan or /summary.")


# Catch replies for exam date manual input
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_exam_date_for" in context.user_data:
        subject = context.user_data.pop("awaiting_exam_date_for")
        text = clean_text(update.message.text)
        try:
            dt = datetime.fromisoformat(text)
            iso = dt.date().isoformat() + "T00:00:00Z"
        except Exception:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d")
                iso = dt.date().isoformat() + "T00:00:00Z"
            except Exception:
                await update.message.reply_text("Could not parse date. Please send in YYYY-MM-DD format.")
                context.user_data["awaiting_exam_date_for"] = subject
                return
        # Retrieve content stored earlier
        content = context.user_data.get("plan_notion_content", "")
        context.user_data["plan_exam_date_iso"] = iso
        context.user_data["plan_subject"] = subject
        # NEW: Directly proceed to plan generation
        await update.message.reply_text("Generating plan — please wait...")
        result = Tools.create_plan(subject, content, iso) # Removed hours_per_day argument
        if not result.get("ok"):
            if result.get("reason") == "moderation_failed":
                await update.message.reply_text("The request seems to be blocked by safety checks. Admin alerted.")
                if ADMIN_TELEGRAM_ID:
                    await context.bot.send_message(ADMIN_TELEGRAM_ID, f"User {update.effective_user.id} attempted create_plan but failed moderation for subject {subject}.")
                return
            else:
                await update.message.reply_text(f"Failed to generate plan: {result.get('reason')}")
                return
        plan = result["plan"]
        await update.message.reply_text(f"📘 Study Plan for {subject}\n\n{plan}")
        return

    await update.message.reply_text("I didn't understand that. Use /summary or /plan to select from your notes.")


# -------------------- Debug/Test Helpers --------------------
def test_calendar_connection() -> Dict[str, Any]:
    try:
        service = get_calendar_service()
        now = datetime.utcnow().isoformat() + "Z"
        max_time = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary", timeMin=now, timeMax=max_time, singleEvents=True, orderBy="startTime", maxResults=10
        ).execute()
        events = events_result.get("items", [])
        return {
            "success": True,
            "event_count": len(events),
            "events": [
                {"summary": e.get("summary", "No title"), "start": e.get("start", {}), "id": e.get("id", "No ID")}
                for e in events
            ],
        }
    except Exception as e:
        logger.exception("Calendar test failed: %s", e)
        return {"success": False, "error": str(e)}


# -------------------- Main --------------------
def main():
    print("🚀 Starting AI Study Companion Bot...")
    print(f"🔑 TELEGRAM_TOKEN: {'✅ Set' if TELEGRAM_TOKEN else '❌ Missing'}")
    if GOOGLE_CREDENTIALS_JSON:
        print(f"📅 GOOGLE_CREDENTIALS_JSON: {GOOGLE_CREDENTIALS_JSON} ({'found' if os.path.exists(GOOGLE_CREDENTIALS_JSON) else 'NOT found'})")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CommandHandler("plan", plan_handler))
    app.add_handler(CommandHandler("debug_calendar", debug_calendar))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()