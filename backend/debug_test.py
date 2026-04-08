import asyncio
import traceback
from app.brain.http_client import HttpBrainClient
from app.config import get_settings

async def test():
    try:
        s = get_settings()
        print(f"Brain URL: {s.brain_base_url}")
        c = HttpBrainClient(s)
        
        # Test next_action
        next_action_result = await c.next_action(
            goal="open https://example.com verify h1 contains Example",
            page={
                "url": "https://example.com",
                "title": "Example Domain",
                "text_excerpt": "This domain is for use in examples.",
                "interactive_elements": [],
                "screenshot_base64": "",
                "screenshot_mime_type": "image/png"
            },
            history=[],
            remaining_steps=10,
            memory={}
        )
        print(f"Next action result: {next_action_result}")
    except Exception as e:
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception: {e}")
        traceback.print_exc()

asyncio.run(test())
