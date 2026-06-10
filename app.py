from datetime import datetime
import os
import subprocess
from ddgs import DDGS
from flask import Flask, render_template, request, jsonify, session
from google import genai
from google.genai import types
from dotenv import load_dotenv
from flask_session import Session

CURRENTTIME = datetime.now()

load_dotenv()

app = Flask(__name__)
# Secret key needed to securely sign Flask client-side sessions
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-dev-key")

# The SDK automatically targets GEMINI_API_KEY from environment variables
client = genai.Client()


# --- SERVER-SIDE SESSION CONFIGURATION ---
app.config["SESSION_TYPE"] = "filesystem"  # Saves session data as local files
app.config["SESSION_PERMANENT"] = False     # Session expires when browser closes
Session(app)                               # <--- Initialize the extension
# ----------------------------------------

# Using the performant gemini-3.5-flash as the base driver 3.1 flash lite for attitude
MODEL_ID = "gemini-3.1-flash-lite"

# ==========================================
# 1. CLEANED SEARCH API
# ==========================================

def web_search(query: str) -> list[dict]:
    """
    Searches the live web for general information, guides, and articles. 
    Returns a list of dictionaries with title, href, and body.
    """
    print("Gemini is searching text:", query)
    try:
        return DDGS().text(query, max_results=22)
    except Exception as e:
        print(f"Text search failed: {e}")
        return []

def web_news_search(query: str) -> list[dict]:
    """
    Searches the live web specifically for recent news articles, breaking updates, 
    and press releases. Use this if the user asks for 'news', 'latest events', or 'recent updates'.
    """
    print("Gemini is searching NEWS:", query)
    try:
        # DDGS().news returns results with 'title', 'url', 'body', 'date', and 'source'
        results = DDGS().news(query, max_results=10)
        
        # Format it cleanly so Gemini gets a uniform list of results
        formatted_results = []
        for r in results:
            formatted_results.append({
                "title": r.get("title"),
                "href": r.get("url"), # Renamed url to href to keep it consistent for your UI links
                "body": r.get("body")
            })
        return formatted_results
    except Exception as e:
        print(f"News search failed: {e}")
        return []

import shlex

def cmd(command: str) -> list[dict]:
    """
    Runs a command on linux like timedatectl, uptime, date etc.
    Do not run dangerous, destructive, or file manipulation commands!
    """
    # 1. Block shell chaining and redirection symbols entirely
    DANGEROUS_SYMBOLS = [";", "&&", "||", "|", "`", "$", ">", "<"]
    if any(symbol in command for symbol in DANGEROUS_SYMBOLS):
        return [{"error": "Execution denied: Shell chaining or redirection symbols are forbidden."}]

    # 2. Parse the command safely to isolate the primary executable
    try:
        parsed_command = shlex.split(command)
        if not parsed_command:
            return [{"error": "Empty command."}]
        base_binary = parsed_command[0].lower()
    except Exception:
        return [{"error": "Invalid command formatting."}]

    # 3. Comprehensive Blacklist of forbidden binaries
    FORBIDDEN_BINARIES = {
        # File destruction / modification
        "rm", "shred", "dd", "chmod", "chown", "mkfs", "fdisk", "parted",
        # Shell spawning / Escaping
        "sh", "bash", "zsh", "csh", "tcsh", "tmux", "screen", "python", "perl",
        # Privilege escalation
        "sudo", "su", "passwd", "chsh",
        # Network / Exfiltration hazards
        "curl", "wget", "nc", "netcat", "nmap", "ssh", "ftp", "scp", "rsync",
        # Package managers (to prevent unwanted installs/removals)
        "pacman", "yay", "paru", "apt", "dnf", "pip",
        # Text editors (which hang the terminal waiting for user input)
        "nano", "vim", "vi", "emacs", "neovim"
    }

    if base_binary in FORBIDDEN_BINARIES:
        return [{"error": f"Execution denied: '{base_binary}' is a forbidden command."}]

    print("Gemini is running:", command)
    
    # CRITICAL: Drop shell=True. Passing the parsed list to subprocess.run
    # ensures that even if something slips through, it won't execute as a shell string.
    try:
        result = subprocess.run(
            parsed_command,
            capture_output=True,
            text=True,
            timeout=5 # Add a timeout so it doesn't hang your app indefinitely
        )
        
        output = result.stdout if result.stdout else result.stderr
        
        return [
            {"command": command, "output": line}
            for line in output.splitlines()
        ]
    except subprocess.TimeoutExpired:
        return [{"error": "Command timed out."}]
    except Exception as e:
        return [{"error": f"Execution failed: {str(e)}"}]


@app.route('/')
def index():
    chat_history = session.get('chat_history', [])
    return render_template('index.html', chat_history=chat_history)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': 'Message content cannot be empty.'}), 400

    if 'chat_history' not in session:
        session['chat_history'] = []

    try:
        # Ai Instruction
        with open("./config/gemini-chan.txt", "r", encoding="utf-8") as e:
            linux_instructions = e.read()

        # Reconstruct the chat with Google GenAI
        chat_session = client.chats.create(
            model=MODEL_ID,
            history=session['chat_history'],
            config=types.GenerateContentConfig(
                system_instruction=linux_instructions,
                tools=[web_search, web_news_search, cmd],
            )
        )

        response = chat_session.send_message(user_message)
        
        # Serialize history back to storage
        updated_history = []
        for content in chat_session.get_history():
            parts_list = [{'text': part.text} for part in content.parts if part.text]
            updated_history.append({
                'role': content.role,
                'parts': parts_list
            })
            
        # This now saves to your local disk storage instead of a 4KB cookie header!
        session['chat_history'] = updated_history
        return jsonify({'response': response.text})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear', methods=['POST'])
def clear():
    session.pop('chat_history', None)
    return jsonify({'status': 'cleared'})

if __name__ == '__main__':
    app.run(debug=True)