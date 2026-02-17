"""Quick test to verify your OpenAI API key and GPT-4 access."""

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

key = os.getenv("OPENAI_API_KEY", "")
if not key:
    print("ERROR: No OPENAI_API_KEY found in .env file.")
    exit(1)

print(f"Key loaded: {key[:12]}...{key[-4:]}")
print("Calling GPT-4...")

try:
    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "Say hello in one sentence."}],
        max_tokens=50,
    )
    print("SUCCESS:", response.choices[0].message.content)
except Exception as e:
    print("FAILED:", e)
