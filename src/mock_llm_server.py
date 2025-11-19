"""
Mock LLM server for testing the pipeline without GPU.

This provides OpenAI-compatible API endpoints for testing.
"""

from flask import Flask, request, jsonify
import time
import re

app = Flask(__name__)

def extract_financial_info(text: str) -> str:
    """Extract key financial information from text."""
    # Simple extraction logic for demo
    info = []
    
    # Extract revenue/earnings
    revenue_match = re.search(r'\$?([\d,]+\.?\d*)\s*(?:billion|B|million|M)', text, re.IGNORECASE)
    if revenue_match:
        info.append(f"Revenue: ${revenue_match.group(1)}")
    
    # Extract company name
    company_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Inc|Corp|LLC|Ltd)', text)
    if company_match:
        info.append(f"Company: {company_match.group(1)}")
    
    # Extract percentage changes
    pct_match = re.search(r'([+-]?\d+\.?\d*)%', text)
    if pct_match:
        info.append(f"Change: {pct_match.group(1)}%")
    
    # Extract quarters/dates
    quarter_match = re.search(r'Q[1-4]\s+\d{4}', text, re.IGNORECASE)
    if quarter_match:
        info.append(f"Period: {quarter_match.group(0)}")
    
    if not info:
        return "Key financial metrics extracted from document."
    
    return " | ".join(info)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200

@app.route('/v1/completions', methods=['POST'])
def completions():
    """OpenAI-compatible completions endpoint."""
    data = request.json
    
    prompt = data.get('prompt', '')
    max_tokens = data.get('max_tokens', 100)
    temperature = data.get('temperature', 0.7)
    
    # Simulate processing time
    time.sleep(0.5)
    
    # Extract information
    response_text = extract_financial_info(prompt)
    
    # Truncate to max_tokens (rough estimate)
    if len(response_text) > max_tokens:
        response_text = response_text[:max_tokens] + "..."
    
    response = {
        "id": f"mock-{int(time.time() * 1000)}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": data.get('model', 'mock-llm'),
        "choices": [
            {
                "text": response_text,
                "index": 0,
                "logprobs": None,
                "finish_reason": "length"
            }
        ],
        "usage": {
            "prompt_tokens": len(prompt.split()),
            "completion_tokens": len(response_text.split()),
            "total_tokens": len(prompt.split()) + len(response_text.split())
        }
    }
    
    return jsonify(response), 200

@app.route('/v1/models', methods=['GET'])
def models():
    """List available models."""
    return jsonify({
        "object": "list",
        "data": [
            {
                "id": "mock-llm",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mock"
            }
        ]
    }), 200

if __name__ == '__main__':
    print("Starting Mock LLM Server on http://0.0.0.0:8000")
    print("Endpoints:")
    print("  GET  /health")
    print("  POST /v1/completions")
    print("  GET  /v1/models")
    app.run(host='0.0.0.0', port=8000, debug=False)

