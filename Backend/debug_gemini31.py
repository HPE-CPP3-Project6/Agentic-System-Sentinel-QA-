#!/usr/bin/env python3
"""Debug script to test Gemini 3.1 Pro Preview response format."""

import os
import json
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from utils import get_local_llm, parse_llm_json, stringify_response

load_dotenv()

# Simple test to check what Gemini 3.1 returns
print("=" * 60)
print("Testing Gemini 3.1 Pro Preview Response Format")
print("=" * 60)

model = os.getenv("SENTINEL_LLM_MODEL", "gemini-2.5-flash")
location = os.getenv("VERTEX_AI_LOCATION", "us-central1")
print(f"\n✓ Model: {model}")
print(f"✓ Location: {location}")

# Create a simple LLM instance
llm = get_local_llm(temperature=0.1, json_mode=True, location=location)

# Test 1: Simple JSON request
print("\n" + "=" * 60)
print("Test 1: Simple JSON Response")
print("=" * 60)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant that returns JSON."),
    ("user", "Return a JSON object with fields: name (string), age (integer). Example: {\"name\": \"John\", \"age\": 30}")
])

chain = prompt | llm
response = chain.invoke({})

print(f"\nResponse type: {type(response)}")
print(f"Response: {response}")
print(f"Response.content type: {type(response.content)}")
print(f"Response.content: {response.content}")

# Try to parse it
try:
    text = stringify_response(response.content)
    print(f"\nStringified text type: {type(text)}")
    print(f"Stringified text: {text}")
    
    parsed = parse_llm_json(response.content)
    print(f"\nParsed JSON: {json.dumps(parsed, indent=2)}")
except Exception as e:
    print(f"\n❌ Error parsing: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Structured JSON request (like Critic)
print("\n" + "=" * 60)
print("Test 2: Structured JSON Response (Critic-like)")
print("=" * 60)

critic_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a requirements critic. Return ONLY a valid JSON object with:
{
  "requirements": [{"requirement_id": "REQ-001", "statement": "User login", "severity_score": 8}],
  "risks": [{"risk_id": "RISK-001", "description": "SQL injection"}]
}"""),
    ("user", "Analyze this user story: User can log in with email and password")
])

chain = critic_prompt | llm
response = chain.invoke({})

print(f"\nResponse type: {type(response)}")
print(f"Response.content type: {type(response.content)}")
print(f"Response.content (first 500 chars): {str(response.content)[:500]}")

try:
    text = stringify_response(response.content)
    print(f"\nStringified text type: {type(text)}")
    print(f"Stringified text (first 500 chars): {text[:500]}")
    
    parsed = parse_llm_json(response.content)
    print(f"\nParsed JSON: {json.dumps(parsed, indent=2)}")
except Exception as e:
    print(f"\n❌ Error parsing: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Debug Complete")
print("=" * 60)
