#!/usr/bin/env python3
"""
Test script for vLLM serving
"""
import requests
import json
import time

def test_llm_completion(prompt: str, model: str = "mistralai/Mistral-7B-Instruct-v0.2"):
    """
    Test LLM completion endpoint
    """
    url = "http://localhost:8000/v1/completions"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": 100,
        "temperature": 0.7
    }
    
    print(f"Sending request to {url}")
    print(f"Prompt: {prompt[:50]}...")
    
    start_time = time.time()
    try:
        response = requests.post(url, json=payload, timeout=30)
        elapsed_time = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ Success! Response time: {elapsed_time:.2f}s")
            print(f"Response: {result['choices'][0]['text']}")
            return result
        else:
            print(f"\n❌ Error: {response.status_code}")
            print(f"Response: {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Connection error. Is vLLM server running?")
        print("Start it with: docker run -p 8000:8000 vllm/vllm-openai:latest --model mistralai/Mistral-7B-Instruct-v0.2")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None

def test_health():
    """
    Test if server is healthy
    """
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Server is healthy")
            return True
    except:
        print("❌ Server is not responding")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("vLLM Test Script")
    print("=" * 60)
    
    # Test health first
    print("\n1. Testing server health...")
    if not test_health():
        print("\n⚠️  Server not healthy. Make sure vLLM is running.")
        exit(1)
    
    # Test completion
    print("\n2. Testing LLM completion...")
    test_prompt = "Extract key information from: Apple reported Q4 revenue of $89.5B, up 1% YoY"
    result = test_llm_completion(test_prompt)
    
    if result:
        print("\n✅ All tests passed!")
    else:
        print("\n❌ Tests failed")

