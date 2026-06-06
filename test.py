from google import genai
from google.genai import types

# Initialize the client
client = genai.Client()

# Define the Google Search grounding tool
search_tool = types.Tool(
    google_search=types.GoogleSearch()
)

# Attach the tool to your configuration
config = types.GenerateContentConfig(
    tools=[search_tool],
    temperature=1.0  # Recommended setting for optimal search grounding behavior
)

# Call Gemini 3.1 Flash-Lite
response = client.models.generate_content(
    model="gemini-3.1-flash-lite",
    contents="On touhou 8, guess these characters: TRoll rabbit lunatic rabbit MEdicine rabbit Lunatic princess",
    config=config
)

print(response.text)
