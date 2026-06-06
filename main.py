import sys
import os
import dotenv
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                             QTextBrowser, QTextEdit, QPushButton, QHBoxLayout)
from PySide6.QtCore import QThread, Signal, Slot, QEvent, Qt
from PySide6.QtGui import QFont, QDesktopServices
from google import genai
from google.genai import types
from ddgs import DDGS
import subprocess
import shlex

# --- Tell python-dotenv to look inside PyInstaller's temporary path ---
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
else:
    bundle_dir = os.path.dirname(os.path.abspath(__file__))

dotenv_path = os.path.join(bundle_dir, '.env')
dotenv.load_dotenv(dotenv_path)

# Initialize client globally after loading environment variables
client = genai.Client()


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
        return DDGS().text(query, max_results=10)
    except Exception as e:
        print(f"Text search failed: {e}")
        return []

def web_news_search(query: str) -> list[dict]:
    """
    Searches the live web specifically for recent news articles, breaking updates, 
    and press releases. Use this if the user asks for 'news', 'latest events', or 'recent updates'.
    Returns a list of dictionaries with title, url, and body.
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

# ==========================================
# 2. STANDARD WORKER THREAD (NON-STREAMING)
# ==========================================
class ChatWorker(QThread):
    # Signals to communicate results safely back to the GUI
    response_received = Signal(str)
    finished = Signal()

    def __init__(self, chat_session, prompt):
        super().__init__()
        self.chat_session = chat_session
        self.prompt = prompt

    def run(self):
        try:
            # Use standard non-streaming send_message to completely avoid the SDK tool-stream bug
            response = self.chat_session.send_message(self.prompt)
            
            if response.text:
                self.response_received.emit(response.text)
            else:
                self.response_received.emit("\n*Gemini completed the action but returned empty text.*")
        except Exception as e:
            self.response_received.emit(f"\n*Error:* {str(e)}")
            
        self.finished.emit()


# ==========================================
# 3. MAIN GUI APPLICATON
# ==========================================
class GeminiChatGUI(QWidget):
    def __init__(self):
        super().__init__()
        
        linux_instructions = """You are a useful assistant named 'Gemini-Chan' A female AI living on my laptop. Stay in the Linux world only for your answers. Do not mention or provide instructions for Windows because I'm allergic to it.
        if user still insist for WIndows questions just dump a reason why use linux lmao
        
        Only search if you do not know the context of a factual question. Do NOT search for simple or basic questions.
        """
        
        # Create chat session with web search tools bundled natively
        self.chat = client.chats.create(
            model='gemini-3.1-flash-lite',
            config=types.GenerateContentConfig(
                system_instruction=linux_instructions,
                tools=[web_search, web_news_search, cmd],
            )
        )
        
        self.chat_history_markdown = "### Assistant\n*chat engine ready and web browsing active.*\n\n"
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Sway Assistant")
        self.resize(600, 700)
        
        main_layout = QVBoxLayout()
        input_layout = QHBoxLayout()
        
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenLinks(False)  # Intercept clicks to prevent raw web frame rendering inside Qt
        self.chat_display.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url)) 
        self.chat_display.setFont(QFont("Monospace", 10))
        
        # Apply CSS style for Markdown code blocks
        doc = self.chat_display.document()
        doc.setDefaultStyleSheet("""
            pre { background-color: #2d2d2d; color: #f8f8f2; font-family: 'Monospace'; padding: 10px; border-radius: 4px; }
            code { background-color: #2d2d2d; color: #f8f8f2; font-family: 'Monospace'; }
        """)
        self.chat_display.setMarkdown(self.chat_history_markdown)
        
        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("Type a message... (Shift+Enter for new line)")
        self.input_field.setMaximumHeight(80)  
        self.input_field.setFont(QFont("Monospace", 10))
        self.input_field.installEventFilter(self)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        
        main_layout.addWidget(self.chat_display)
        main_layout.addLayout(input_layout)
        self.setLayout(main_layout)

    def eventFilter(self, obj, event):
        if obj is self.input_field and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                # If Shift is held down, inject a newline character explicitly 
                # at the current cursor position, then tell Qt we handled it.
                if event.modifiers() & Qt.ShiftModifier:
                    self.input_field.insertPlainText("\n")
                    return True
                
                # If Enter alone is pressed, trigger the message send
                else:
                    self.send_message()
                    return True  # Swallows the enter event so it doesn't leave an empty line behind
                    
        return super().eventFilter(obj, event)

    def send_message(self):
        user_text = self.input_field.toPlainText().strip()
        if not user_text:
            return
            
        # UI Feedback: Show user input and hint that background actions are happening
        self.chat_history_markdown += f"\n\n---\n\n**You:** {user_text}\n\n---\n\n**Gemini:** *Thinking/Searching...*\n"
        self.chat_display.setMarkdown(self.chat_history_markdown)
        self.input_field.clear()
        
        # Lock UI components so users can't trigger multiple overlaps
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        
        # Dispatch task execution safely inside the background worker
        self.worker = ChatWorker(self.chat, user_text)
        self.worker.response_received.connect(self.display_response)
        self.worker.finished.connect(self.stream_finished)
        self.worker.start()

    @Slot(str)
    def display_response(self, text):
        # Strip out the placeholder indicator and paste the complete text payload
        if "*Thinking/Searching...*" in self.chat_history_markdown:
            self.chat_history_markdown = self.chat_history_markdown.replace("*Thinking/Searching...*\n", "")
            
        self.chat_history_markdown += text
        self.chat_display.setMarkdown(self.chat_history_markdown)
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    @Slot()
    def stream_finished(self):
        # Release the UI locks
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = GeminiChatGUI()
    gui.show()
    sys.exit(app.exec())