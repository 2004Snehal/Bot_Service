import asyncio
import os
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

# Mock API Key if not present
if not os.getenv("DEEPGRAM_API_KEY"):
    os.environ["DEEPGRAM_API_KEY"] = "test_key"

async def main():
    try:
        client = DeepgramClient(api_key="test_key")
        print(f"Client type: {type(client)}")
        
        # Check if client.listen exists
        if hasattr(client, "listen"):
            print("client.listen exists")
            
            # Check client.listen.live
            if hasattr(client.listen, "live"):
                 print("client.listen.live exists")
                 print(f"client.listen.live type: {type(client.listen.live)}")
                 
                 # Check v1
                 if hasattr(client.listen.live, "v"):
                     v1 = client.listen.live.v("1")
                     print(f"client.listen.live.v('1') type: {type(v1)}")
            else:
                 print("client.listen.live DOES NOT exist")

        else:
            print("client.listen DOES NOT exist")
             
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
