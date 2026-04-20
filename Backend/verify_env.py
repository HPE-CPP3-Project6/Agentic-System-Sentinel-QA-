#!/usr/bin/env python
"""Quick verification of environment variables."""

from dotenv import load_dotenv
import os

load_dotenv()

print(f"✓ Model: {os.getenv('SENTINEL_LLM_MODEL')}")
print(f"✓ Location: {os.getenv('VERTEX_AI_LOCATION')}")
print(f"✓ Project: {os.getenv('VERTEX_AI_PROJECT_ID')}")
print("\nReady to test with Gemini 3.1 Pro Preview!")
