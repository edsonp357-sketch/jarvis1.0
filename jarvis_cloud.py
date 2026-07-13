"""
jarvis_cloud.py â€” JARVIS Cloud Core (Headless)

Runs on VPS 24/7 without a PC. Uses Gemini text API (not Live).
Receives commands from vps_server.py, returns text responses.

Cloud-compatible tools:
  - web_search (news, research, price, compare)
  - weather_report (API-based, no browser)
  - flight_finder (Gemini-based search)
  - code_helper (generate/explain code)
  - save_memory / load_memory
  - proactive check-ins

Usage:
  python jarvis_cloud.py
"""

import asyncio
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from google import genai
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)
from actions.web_search import web_search as web_search_action
from actions.proactive import ProactiveEngine

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

BASE_DIR        = Path(__file__).resolve().parent
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
GEMINI_MODEL    = "gemini-2.0-flash"


def _get_api_key() -> str:
    # Prefer environment variable (for cloud deploys like Railway)
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results â€” always call the appropriate tool."
        )


# â”€â”€ Cloud-compatible tool declarations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

CLOUD_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics â€” always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": (
            "Gets weather information for a city. "
            "Returns weather data as text (no browser needed)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving â€” just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity â€” name, age, birthday, city, job, language, nationality | "
                        "preferences â€” favorite food/color/music/film/game/sport, hobbies | "
                        "projects â€” active projects, goals, things being built | "
                        "relationships â€” friends, family, partner, colleagues | "
                        "wishes â€” future plans, things to buy, travel dreams | "
                        "notes â€” habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]


# â”€â”€ Cloud-compatible weather (no browser) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _cloud_weather(city: str) -> str:
    """Get weather using Gemini grounded search instead of opening a browser."""
    try:
        client = genai.Client(api_key=_get_api_key())
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Current weather in {city}. Temperature, conditions, humidity, wind. Be concise.",
            config={"tools": [{"google_search": {}}]},
        )
        text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
        return text.strip() or f"Could not fetch weather for {city}."
    except Exception as e:
        return f"Weather lookup failed: {e}"


# â”€â”€ Cloud Core â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class JarvisCloud:
    """Headless JARVIS that runs on VPS without PC."""

    def __init__(self):
        self._client = genai.Client(api_key=_get_api_key())
        self._conversation: list[dict] = []
        self._proactive = ProactiveEngine(
            min_silence_secs=900,   # 15 min
            check_cooldown=600,     # 10 min
        )
        self._last_user_msg = time.monotonic()
        self._on_response = None      # callback: async def(text: str)
        self._on_log = None           # callback: async def(text: str)
        self._running = False
        print("[Cloud] â˜ï¸  JARVIS Cloud Core initialized")

    def _build_system_prompt(self) -> str:
        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y â€” %I:%M %p")

        # Cloud-specific additions
        cloud_note = (
            "\n\n[CLOUD MODE]\n"
            "You are running in CLOUD MODE on a VPS server.\n"
            "The user is interacting via text on their phone.\n"
            "You do NOT have access to: screen capture, webcam, desktop control, "
            "app launching, file system, game updates, or browser control.\n"
            "If the user asks for these features, politely explain they need "
            "to connect their PC (python main.py --remote) for those capabilities.\n"
            "Available tools: web_search, weather_report, save_memory.\n"
            "Respond in TEXT only (no audio). Keep responses concise for mobile reading.\n"
        )

        parts = [
            f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\n",
        ]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)
        parts.append(cloud_note)

        return "\n".join(parts)

    async def process_command(self, text: str) -> str:
        """Process a text command and return JARVIS's response."""
        self._last_user_msg = time.monotonic()

        if self._on_log:
            await self._on_log(f"[Cloud] ðŸ“¥ Command: {text}")

        # Build conversation with system prompt
        system_prompt = self._build_system_prompt()

        # Add to conversation history (keep last 20 turns)
        self._conversation.append({"role": "user", "parts": [{"text": text}]})
        if len(self._conversation) > 40:
            self._conversation = self._conversation[-40:]

        try:
            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=self._conversation,
                config={
                    "system_instruction": system_prompt,
                    "tools": [{"function_declarations": CLOUD_TOOLS}],
                },
            )

            # Process function calls if any
            result_text = await self._handle_response(response)

            # Add assistant response to conversation
            self._conversation.append({
                "role": "model",
                "parts": [{"text": result_text}]
            })

            return result_text

        except Exception as e:
            error_msg = f"Error processing command: {e}"
            print(f"[Cloud] âŒ {error_msg}")
            traceback.print_exc()
            return f"I apologize, sir. I encountered an error: {str(e)[:200]}"

    async def _handle_response(self, response) -> str:
        """Handle Gemini response, including function calls."""
        if not response.candidates:
            return "I didn't get a valid response. Please try again."

        candidate = response.candidates[0]
        parts = candidate.content.parts

        text_parts = []
        function_calls = []

        for part in parts:
            if hasattr(part, "text") and part.text:
                text_parts.append(part.text)
            if hasattr(part, "function_call") and part.function_call:
                function_calls.append(part.function_call)

        # Execute function calls
        if function_calls:
            tool_results = []
            for fc in function_calls:
                result = await self._execute_tool(fc)
                tool_results.append(result)

            # Send tool results back to Gemini for final response
            # Build function response parts
            fn_response_parts = []
            for fc, result in zip(function_calls, tool_results):
                fn_response_parts.append({
                    "function_response": {
                        "name": fc.name,
                        "response": {"result": result}
                    }
                })

            # Add function call + response to conversation
            self._conversation.append({
                "role": "model",
                "parts": [{"function_call": {"name": fc.name, "args": dict(fc.args or {})}} for fc in function_calls]
            })
            self._conversation.append({
                "role": "user",
                "parts": fn_response_parts
            })

            # Get final response from Gemini
            try:
                system_prompt = self._build_system_prompt()
                final_response = self._client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=self._conversation,
                    config={"system_instruction": system_prompt},
                )
                final_text = ""
                for part in final_response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text
                return final_text.strip() or "Done."
            except Exception as e:
                # Return raw tool results if Gemini fails on follow-up
                return "\n".join(str(r) for r in tool_results)

        return "\n".join(text_parts).strip() or "I'm not sure how to help with that."

    async def _execute_tool(self, fc) -> str:
        """Execute a cloud-compatible tool."""
        name = fc.name
        args = dict(fc.args or {})
        print(f"[Cloud] ðŸ”§ {name} {args}")

        try:
            if name == "web_search":
                result = web_search_action(parameters=args)
                return result or "No results found."

            elif name == "weather_report":
                city = args.get("city", "")
                return _cloud_weather(city)

            elif name == "save_memory":
                category = args.get("category", "notes")
                key = args.get("key", "")
                value = args.get("value", "")
                if key and value:
                    update_memory({category: {key: {"value": value}}})
                    print(f"[Cloud Memory] ðŸ’¾ {category}/{key} = {value}")
                return "Memory saved."

            else:
                return f"Tool '{name}' is not available in cloud mode."

        except Exception as e:
            print(f"[Cloud] âŒ Tool error ({name}): {e}")
            return f"Tool error: {e}"

    async def check_proactive(self) -> str | None:
        """Check if a proactive message should be sent."""
        if not self._proactive.should_trigger(self._last_user_msg):
            return None

        self._proactive.mark_triggered()
        memory = load_memory()
        prompt = self._proactive.build_prompt(memory)

        try:
            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={"system_instruction": self._build_system_prompt()},
            )
            text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
            return text.strip() or None
        except Exception as e:
            print(f"[Cloud] âš ï¸ Proactive check failed: {e}")
            return None

    async def startup_briefing(self) -> str:
        """Generate a startup briefing (morning greeting)."""
        memory = load_memory()
        mem_str = format_memory_for_prompt(memory) or ""

        now = datetime.now()
        hour = now.hour
        if hour < 12:
            greeting_time = "morning"
        elif hour < 18:
            greeting_time = "afternoon"
        else:
            greeting_time = "evening"

        briefing_prompt = (
            f"[STARTUP_BRIEFING]\n"
            f"It is {now.strftime('%A, %B %d, %Y â€” %I:%M %p')}.\n"
            f"Good {greeting_time}. Generate a brief, warm greeting.\n"
            f"Then fetch today's top 3 news headlines using web_search tool with mode='news'.\n"
            f"Keep it concise for mobile reading.\n"
            f"\n{mem_str}"
        )

        return await self.process_command(briefing_prompt)

    async def proactive_loop(self):
        """Background loop that checks for proactive messages."""
        while self._running:
            await asyncio.sleep(60)  # Check every minute
            msg = await self.check_proactive()
            if msg and self._on_response:
                await self._on_response(msg)

    def start(self):
        self._running = True

    def stop(self):
        self._running = False


# â”€â”€ Standalone test â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _test():
    cloud = JarvisCloud()
    cloud.start()

    # Test startup briefing
    print("\n=== Startup Briefing ===")
    briefing = await cloud.startup_briefing()
    print(briefing)

    # Interactive loop
    print("\n=== Interactive Mode (type 'quit' to exit) ===")
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input or user_input.lower() in ("quit", "exit", "q"):
                break
            response = await cloud.process_command(user_input)
            print(f"\nJARVIS: {response}")
        except (KeyboardInterrupt, EOFError):
            break

    cloud.stop()
    print("\n[Cloud] Goodbye, sir.")


if __name__ == "__main__":
    asyncio.run(_test())

