"""Quick test: what does Firecrawl search actually return?"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from firecrawl import FirecrawlApp

api_key = os.getenv("FIRECRAWL_API_KEY", "")
print(f"API key present: {bool(api_key)}")
print(f"API key prefix: {api_key[:8]}...")

app = FirecrawlApp(api_key=api_key)

# Test with a simple Chinese query
query = "DJI drone pricing 2025"
print(f"\nQuery: {query}")
result = app.search(query=query, limit=5)

print(f"\nResult type: {type(result)}")
print(f"Result dir: {[a for a in dir(result) if not a.startswith('_')]}")

# Try different access patterns
if hasattr(result, "data"):
    print(f"\nresult.data type: {type(result.data)}")
    print(f"result.data: {repr(result.data)[:1000]}")

if isinstance(result, list):
    print(f"\nResult is list, len={len(result)}")
    if result:
        print(f"First item: {repr(result[0])[:500]}")

if hasattr(result, "__iter__") and not isinstance(result, (str, dict)):
    print("\nResult is iterable, iterating:")
    for i, item in enumerate(result):
        print(f"  [{i}] type={type(item)}")
        if hasattr(item, "url"):
            print(f"       url={item.url}")
            print(f"       title={getattr(item, 'title', 'N/A')}")
        elif isinstance(item, dict):
            print(f"       keys={list(item.keys())}")
            print(f"       url={item.get('url', 'N/A')}")
        else:
            print(f"       repr={repr(item)[:200]}")
        if i >= 5:
            break

print(f"\nFull repr (first 3000 chars):\n{repr(result)[:3000]}")
