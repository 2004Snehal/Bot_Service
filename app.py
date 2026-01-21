# Load environment variables FIRST before any other imports
from dotenv import load_dotenv
load_dotenv()  # This loads .env from root directory

import os
import sys

# Debug: Print loaded env vars (remove in production)
print(f"[ENV] DEEPGRAM_API_KEY loaded: {'Yes' if os.getenv('DEEPGRAM_API_KEY') else 'No'}")
print(f"[ENV] GROQ_API_KEY loaded: {'Yes' if os.getenv('GROQ_API_KEY') else 'No'}")
print(f"[ENV] TTS_MICROSERVICE_URL: {os.getenv('TTS_MICROSERVICE_URL', 'Not set')}")

# Wrap imports in try-except to catch import errors
try:
    print("[IMPORT] Loading google_meet.bot...")
    from google_meet.bot import JoinGoogleMeet
    print("[IMPORT] Loading utils...")
    from utils import clean_meeting_link, convert_timestamp_to_utc
    print("[IMPORT] Loading config...")
    from config import get_settings
    print("[IMPORT] Loading logger...")
    from logger import LogConfig
    print("[IMPORT] All imports successful!")
except Exception as e:
    print(f"[IMPORT ERROR] Failed to import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

import argparse
import logging
import signal


if __name__ == "__main__":
    print("[MAIN] Starting argument parsing...")
    try: 
        parser = argparse.ArgumentParser(description="Join a Google Meeting to record audio.")
        parser.add_argument("meetlink", help="The Google Meet link to join")
        parser.add_argument("--start-time", type=int, default=None, help="Meeting start time (JavaScript timestamp in milliseconds)")
        parser.add_argument("--end-time", type=int, default=None, help="Meeting end time (JavaScript timestamp in milliseconds)")
        parser.add_argument("--min-record-time", type=int, default=7200, help="Minimum recording time in seconds (Default: 2 hours)")
        parser.add_argument("--bot-name", default="CueMeet Assistant", help="Name of the bot in the meeting (Default: 'CueMeet Assistant')")
        parser.add_argument("--max-waiting-time", type=int, default=1800, help="Maximum waiting time in seconds (Default: 30 minutes)")
        parser.add_argument("--speak", type=str, default=None, help="Enable voice assistant with Pipecat (Default: False)")

        args = parser.parse_args()
        print(f"[MAIN] Arguments parsed. Meeting link: {args.meetlink}")
        
        # Determine enable_speak from argument OR environment variable
        # Priority: --speak argument > ENABLE_SPEAK env var > default (False)
        if args.speak is not None:
            # Argument was provided
            enable_speak = args.speak.lower() in ('true', '1', 'yes')
        else:
            # Check environment variable
            env_speak = os.getenv('ENABLE_SPEAK', 'False')
            enable_speak = env_speak.lower() in ('true', '1', 'yes')
        
        print(f"[MAIN] --speak arg: {args.speak}")
        print(f"[MAIN] ENABLE_SPEAK env: {os.getenv('ENABLE_SPEAK', 'Not set')}")
        print(f"[MAIN] Final enable_speak value: {enable_speak}")

        print("[MAIN] Creating JoinGoogleMeet instance...")
        print(f"[MAIN] Voice assistant enabled: {enable_speak}")
        meet_bot = JoinGoogleMeet(
            meetlink=clean_meeting_link(args.meetlink),
            start_time_utc=convert_timestamp_to_utc(args.start_time) if args.start_time else None,
            end_time_utc = convert_timestamp_to_utc(args.end_time) if args.end_time else None,
            min_record_time=args.min_record_time,
            bot_name=args.bot_name,
            max_waiting_time=args.max_waiting_time,
            enable_speak=enable_speak,
            project_settings=get_settings(),
            logger=LogConfig().get_logger("Google Meet Bot")
        )

        def signal_handler(sig, frame):
            # Use logging instead of print for better visibility in docker logs
            logging.info(f"Received signal {sig}. Stopping bot gracefully...")
            try:
                meet_bot.end_session()
            except Exception as e:
                logging.error(f"Error during graceful shutdown: {e}")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print("[MAIN] Starting bot.run()...")
        meet_bot.run()
        print("[MAIN] Bot completed successfully.")
    except Exception as e:
        print(f"[MAIN ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        logging.info("Bot has finished running. Exiting the application.")