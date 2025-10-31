# 📚 AI Study Companion Telegram Bot

An AI-powered Telegram bot that integrates with **Notion** to fetch study notes and **Google Calendar** to find exam dates, then uses **OpenAI (GPT-4o-mini)** to generate concise summaries or multi-day study plans.

## ✨ Features

* **Notion Integration**: Fetch a list of all note titles from a specified Notion database.
* **AI Summaries**: Generate a concise summary (with bullet points and key takeaways) for any selected Notion note.
* **AI Study Plans**: Create a customized, multi-day study plan for a subject, referencing the content of a Notion note.
* **Google Calendar Exam Detection**: Automatically search Google Calendar for upcoming exams/tests related to the selected subject to determine the time available for planning.
* **Manual Date Input**: Allows manual input of the exam date if no calendar event is found.
* **Rate Limiting**: Simple user-based rate limiting to prevent abuse.
* **Moderation**: OpenAI moderation check is performed on content before processing.

## ⚙️ Prerequisites

1.  **Python 3.9+**
2.  **Telegram Bot Token**: Get one from [@BotFather](https://t.me/BotFather).
3.  **OpenAI API Key**: For generating summaries and plans.
4.  **Notion Integration**:
    * Create an integration on [Notion's developer page](https://www.notion.so/my-integrations).
    * Find your **Notion API Key** (Secret).
    * Share your study database with the new integration.
    * Get your **Notion Database ID**.
5.  **Google Calendar API**:
    * Enable the Google Calendar API in the [Google Cloud Console](https://console.cloud.google.com/).
    * Download the `credentials.json` file for an **OAuth 2.0 Client ID** (Desktop application type is easiest for local setup).

## 🚀 Setup & Installation

### 1. Clone the repository

git clone <repository-url>
cd ai-study-companion-bot

### 2\. Install dependencies

pip install -r requirements.txt
# NOTE: The provided code only shows imports. A complete requirements.txt should contain:
# python-telegram-bot
# openai
# python-dotenv
# requests
# google-auth-oauthlib
# google-api-python-client
# google-auth-httplib2
# google-auth-transport-requests


### 3\. Configure Environment Variables

Create a file named `.env` in the root directory and fill in your credentials:

# .env file content
TELEGRAM_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
OPENAI_API_KEY="sk-YOUR_OPENAI_API_KEY"

# Notion Credentials
NOTION_API_KEY="secret_YOUR_NOTION_API_KEY"
NOTION_DATABASE_ID="YOUR_NOTION_DATABASE_ID"

# Google Calendar Credentials
# Path to the downloaded Google Cloud credentials file (e.g., /path/to/client_secret.json)
GOOGLE_CREDENTIALS_JSON_PATH="./credentials.json"

# Admin ID for moderation alerts (optional, set to 0 to disable)
ADMIN_TELEGRAM_ID="YOUR_ADMIN_TELEGRAM_USER_ID"


### 4\. Run the Bot
python bot.py
# Assuming your main file is named bot.py based on the code structure

The first time you run the bot, the Google Calendar integration will launch a browser window for you to authenticate and authorize access to your calendar. A `token.json` file will then be created to store the credentials for subsequent runs.

## 🤖 Bot Commands

| Command | Description | Flow |
| :--- | :--- | :--- |
| `/start` | Greets the user and introduces the bot. | Start |
| `/summary` | Fetches Notion notes and prompts the user to select one for summarization. | User selects note -\> Bot fetches content -\> Bot generates summary -\> Bot replies |
| `/plan` | Fetches Notion notes and prompts the user to select one for creating a study plan. | User selects note -\> Bot searches Calendar -\> (If multiple events) User selects event -\> Bot generates plan -\> Bot replies |
| `/test` | Simple connectivity check. | Bot replies with "✅ Bot is working\!" |
| `/debug_calendar` | Tests the connection to Google Calendar. | Bot replies with connection status and a count of upcoming events. |

## 📐 Data Flow (Plan Generation Example)

1.  User sends `/plan`.
2.  Bot calls `Tools.get_notion_titles()`.
3.  User selects a note (e.g., "**Data Science**") via inline button.
4.  Bot calls `Tools.fetch_notion_content_by_title("Data Science")` to get notes content.
5.  Bot calls `Tools.fetch_exam_candidates("Data Science")` to search Google Calendar.
      * If **one** exam is found: Directly proceed to plan generation using that date.
      * If **multiple** exams are found: Display inline buttons for the user to select the correct event/date.
      * If **no** exam is found: Prompt the user to manually reply with the exam date (YYYY-MM-DD).
6.  Once the exam date is determined (either from Calendar or manual input), the bot calls `Tools.create_plan("Data Science", content, exam_date_iso)`.
7.  The AI generates the custom study plan based on the number of days left and the provided content.
8.  Bot replies to the user with the final study plan.

## ⚠️ Important Notes

  * **Security**: Ensure your `.env` file is secured and not committed to a public repository.
  * **Google Calendar**: The bot uses the `primary` calendar. Ensure your exam events are on that calendar.
  * **Rate Limits**: The simple rate limiter is set to **1 request per second** per user.
  * **Content**: Study notes with sensitive content may be flagged by the OpenAI moderation API and will not be processed. An alert will be sent to the `ADMIN_TELEGRAM_ID` if set.
