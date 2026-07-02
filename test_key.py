import os
from dotenv import load_dotenv
from google import genai

# Force prioritize the .env file
load_dotenv(override=True)

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: Your .env file is NOT being read, or GEMINI_API_KEY is empty.")
    exit()

print(f"🔑 Key found in environment: {api_key[:5]}...{api_key[-4:]}")
print("Initializing modern Google GenAI SDK...")

try:
    # Initialize the modern client
    client = genai.Client(api_key=api_key)
    
    # Use the supported production model
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Reply with strictly the word "SUCCESS" if you receive this message.'
    )
    
    print("✅ SUCCESS: API KEY CONFIGURATION APPROVED BY GOOGLE!")
    print(f"🤖 Agent response: {response.text.strip()}")

except Exception as e:
    print(f"❌ API KEY CONFIGURATION REJECTED. Details: {e}")
    