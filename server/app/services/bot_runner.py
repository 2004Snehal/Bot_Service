import logging
import os
import threading
import subprocess
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================================
# DOCKER CLIENT
# ============================================================================
# Lazy import docker to allow the module to load even if docker isn't installed
docker_client = None

def get_docker_client():
    global docker_client
    if docker_client is None:
        import docker
        docker_client = docker.from_env()
    return docker_client





# ============================================================================
# DOCKER VERSION (COMMENTED OUT)
# ============================================================================
# def run_bot_logic(user_id: str, bot_id: str, meetlink: str, min_record_time: int, bot_name: str, system_prompt: str = None):
#     """
#     Launches a Docker container to run the bot.
#     
#     Args:
#         user_id: The owner's user ID (for multi-tenant storage isolation)
#         bot_id: The bot configuration ID
#         meetlink: Google Meet URL to join
#         min_record_time: Minimum recording time in seconds
#         bot_name: Display name for the bot
#         system_prompt: Custom system prompt for the bot
#     """
#     from server.app.db.database import SessionLocal
#     from server.app.db.models import Meeting
#     from server.app.services.session_manager import session_manager
#     
#     db = SessionLocal()
#     
#     # Create user storage directory
#     user_storage = get_user_storage_path(user_id)
#     
#     meeting_record = Meeting(
#         user_id=user_id,
#         bot_id=bot_id,
#         status="starting",
#         start_time=datetime.utcnow()
#     )
#     db.add(meeting_record)
#     db.commit()
#     db.refresh(meeting_record)
#     meeting_id = meeting_record.id

#     try:
#         logger.info(f"Launching Docker container for bot {bot_id} (user: {user_id})...")
#         
#         client = get_docker_client()
#         
#         # Build environment variables
#         env_vars = {
#             "BOT_ID": bot_id,
#             "USER_ID": user_id,  # Pass user_id to container for storage paths
#             "MEETING_ID": meeting_id,
#             "TTS_MICROSERVICE_URL": os.getenv("TTS_MICROSERVICE_URL", "https://smolservice.onrender.com"),
#             "DEEPGRAM_API_KEY": os.getenv("DEEPGRAM_API_KEY"),
#             "GROQ_API_KEY": os.getenv("GROQ_API_KEY"),
#         }
#         
#         # Add system prompt if provided
#         if system_prompt:
#             env_vars["SYSTEM_PROMPT"] = system_prompt
#         
#         # Build command
#         command = [
#             meetlink,
#             "--bot-name", bot_name,
#             "--min-record-time", str(min_record_time)
#         ]
#         
#         # Mount user storage directory
#         volumes = {
#             user_storage: {"bind": "/app/out", "mode": "rw"}
#         }
#         
#         container = client.containers.run(
#             image="cuemeet-bot:latest",
#             detach=True,
#             auto_remove=True,
#             name=f"bot_{bot_id}_{meeting_id[:8]}",
#             environment=env_vars,
#             command=command,
#             shm_size="2g",  # Critical for Chrome
#             volumes=volumes,  # User-specific storage mount
#         )
#         
#         logger.info(f"Container started: {container.id}")
#         meeting_record.status = "running"
#         
#         # Store expected file paths
#         meeting_record.transcript_file = os.path.join(user_storage, "transcripts", f"{meeting_id}_transcript.json")
#         meeting_record.recording_file = os.path.join(user_storage, "recordings", f"{meeting_id}.opus")
#         meeting_record.screenshots_dir = os.path.join(user_storage, "screenshots", meeting_id)
#         db.commit()
#         
#         # Track the container
#         session_manager.add_bot(bot_id, container, None)
#         
#         # Wait for container to finish
#         result = container.wait()
#         exit_code = result.get("StatusCode", -1)
#         
#         if exit_code == 0:
#             meeting_record.status = "completed"
#         else:
#             meeting_record.status = "failed"
#             logger.error(f"Container exited with code {exit_code}")
#         
#         meeting_record.end_time = datetime.utcnow()
#         db.commit()

#     except Exception as e:
#         logger.error(f"Bot {bot_id} failed: {e}")
#         meeting_record.status = "failed"
#         meeting_record.end_time = datetime.utcnow()
#         db.commit()
#     finally:
#         session_manager.remove_bot(bot_id)
#         db.close()


# ============================================================================
# NEW SUBPROCESS VERSION (WITHOUT DOCKER)
# ============================================================================
def run_bot_logic(user_id: str, bot_id: str, meeting_id: str, meetlink: str, min_record_time: int, bot_name: str, system_prompt: str = None, enable_recording: bool = True, enable_transcript: bool = True, enable_speak: bool = False):
    """
    Launch the bot. Preferred mode: Docker container (image 'bot:voice' or specific ID).
    Falls back to subprocess if Docker is unavailable.
    
    Args:
        user_id: The owner's user ID (for multi-tenant storage isolation)
        bot_id: The bot configuration ID
        meeting_id: The meeting record ID (client-provided)
        meetlink: Google Meet URL to join
        min_record_time: Minimum recording time in seconds
        bot_name: Display name for the bot
        system_prompt: Custom system prompt for the bot
        enable_recording: Enable video/audio recording
        enable_transcript: Enable transcript extraction
        enable_speak: Enable bot voice responses
    """
    from server.app.db.database import SessionLocal
    from server.app.db.models import Meeting
    from server.app.services.session_manager import session_manager
    
    db = SessionLocal()
    
    # Get existing meeting record
    meeting_record = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
    if not meeting_record:
        logger.error(f"Meeting record {meeting_id} not found")
        return

    process = None
    try:
        # Try Docker first
        try:
            client = get_docker_client()
            image_ref = os.getenv("BOT_DOCKER_IMAGE", "bot:voice")  # default to given ID
            logger.info(f"Launching Docker container for bot {bot_id} (user: {user_id}) with image {image_ref}...")

            # Build environment variables (container)
            env_vars = {
                "BOT_ID": str(bot_id),
                "USER_ID": str(user_id),
                "MEETING_ID": str(meeting_id),
                "TTS_MICROSERVICE_URL": os.getenv("TTS_MICROSERVICE_URL", "https://smolservice.onrender.com"),
                "DEEPGRAM_API_KEY": os.getenv("DEEPGRAM_API_KEY", ""),
                "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
                "ENABLE_RECORDING": str(enable_recording),
                "ENABLE_TRANSCRIPT": str(enable_transcript),
                "ENABLE_SPEAK": str(enable_speak),
                # AWS S3 - using IAM roles from EC2 instance (no explicit credentials needed)
                "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
                "S3_BUCKET_NAME": os.getenv("S3_BUCKET_NAME", "hicapy"),
            }
            if system_prompt:
                env_vars["SYSTEM_PROMPT"] = system_prompt

            # Build command passed to entrypoint
            command = [
                meetlink,
                "--bot-name", bot_name,
                "--min-record-time", str(min_record_time)
            ]

            container_name = f"bot_{bot_id}_{str(meeting_id)[:8]}"
            container = client.containers.run(
                image=image_ref,
                detach=True,
                auto_remove=True,
                name=container_name,
                environment=env_vars,
                command=command,
                shm_size="2g"
            )

            logger.info(f"Container started: {container.id}")
            meeting_record.status = "running"
            db.commit()

            # Track container (store container object)
            from server.app.services.session_manager import session_manager
            session_manager.add_bot(bot_id, container, None)

            # Wait for container to finish
            result = container.wait()
            exit_code = result.get("StatusCode", -1)

            if exit_code == 0:
                meeting_record.status = "completed"
                logger.info(f"Bot {bot_id} completed successfully (container)")
            else:
                meeting_record.status = "failed"
                logger.error(f"Container exited with code {exit_code}")
                # Log some container stderr
                try:
                    logs = container.logs(tail=200)
                    if logs:
                        logger.error(f"Container logs: {logs.decode(errors='ignore')[:1000]}")
                except Exception:
                    pass

            meeting_record.end_time = datetime.utcnow()
            db.commit()
            return
        except Exception as docker_err:
            logger.warning(f"Docker launch failed, falling back to subprocess: {docker_err}")

        # Fallback: subprocess on host
        logger.info(f"Launching bot subprocess for bot {bot_id} (user: {user_id})...")

        # Temp directory for bot to use (bot handles S3 uploads directly)
        # Force /tmp/cuemeet to ensure we don't use project directory
        temp_dir = "/tmp/cuemeet"
        # Do not create any local storage folder outside /tmp/cuemeet
        
        # Build environment variables (merge with current env)
        env_vars = os.environ.copy()
        env_vars.update({
            "BOT_ID": str(bot_id),
            "USER_ID": str(user_id),
            "MEETING_ID": str(meeting_id),
            "TTS_MICROSERVICE_URL": os.getenv("TTS_MICROSERVICE_URL", "https://smolservice.onrender.com"),
            "DEEPGRAM_API_KEY": os.getenv("DEEPGRAM_API_KEY", ""),
            "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
            "OUTPUT_DIR": temp_dir,  # Temp directory (bot uploads to S3 directly)
            "ENABLE_RECORDING": str(enable_recording),
            "ENABLE_TRANSCRIPT": str(enable_transcript),
            "ENABLE_SPEAK": str(enable_speak),
            # AWS S3 - using IAM roles (no explicit credentials)
            "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
            "S3_BUCKET_NAME": os.getenv("S3_BUCKET_NAME", ""),
        })
        if system_prompt:
            env_vars["SYSTEM_PROMPT"] = system_prompt

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        app_py_path = os.path.join(project_root, "app.py")

        command = [
            "python",
            app_py_path,
            meetlink,
            "--bot-name", bot_name,
            "--min-record-time", str(min_record_time)
        ]

        process = subprocess.Popen(
            command,
            env=env_vars,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_root,
            text=True
        )
        logger.info(f"Bot process started: PID {process.pid}")
        meeting_record.status = "running"
        
        # S3 URLs will be set by the bot directly - we just track expected paths
        s3_bucket = os.getenv("S3_BUCKET_NAME", "")
        aws_region = os.getenv("AWS_REGION", "us-east-1")
        if s3_bucket:
            base_s3_url = f"https://{s3_bucket}.s3.{aws_region}.amazonaws.com/meetings/meet_{meeting_id}"
            meeting_record.recording_s3_url = f"{base_s3_url}/video/recording.mp4"
            meeting_record.transcript_s3_url = f"{base_s3_url}/transcript/transcript.json"
        db.commit()
        
        # Track the process (store PID instead of container)
        session_manager.add_bot(bot_id, process, None)
        
        # Wait for process to finish
        exit_code = process.wait()
        
        # Capture output for debugging
        stdout, stderr = process.communicate() if process.poll() is None else ("", "")
        
        if exit_code == 0:
            meeting_record.status = "completed"
            logger.info(f"Bot {bot_id} completed successfully")
            # Bot handles S3 uploads directly, no need to upload here
            db.commit()
        else:
            meeting_record.status = "failed"
            logger.error(f"Bot {bot_id} exited with code {exit_code}")
            if stderr:
                logger.error(f"Bot stderr: {stderr[:500]}")  # Log first 500 chars
        
        meeting_record.end_time = datetime.utcnow()
        db.commit()

    except Exception as e:
        logger.error(f"Bot {bot_id} failed: {e}")
        meeting_record.status = "failed"
        meeting_record.end_time = datetime.utcnow()
        db.commit()
        
        # Kill process if still running
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                
    finally:
        session_manager.remove_bot(bot_id)
        db.close()


def start_bot_thread(user_id: str, bot_id: str, meeting_id: str, meetlink: str, min_record_time: int, bot_name: str, system_prompt: str = None, enable_recording: bool = True, enable_transcript: bool = True, enable_speak: bool = True):
    """Start a bot in a background thread."""
    thread = threading.Thread(
        target=run_bot_logic,
        args=(user_id, bot_id, meeting_id, meetlink, min_record_time, bot_name, system_prompt, enable_recording, enable_transcript, enable_speak),
        daemon=True
    )
    thread.start()
    return thread