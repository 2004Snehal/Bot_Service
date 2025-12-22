import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages running bot sessions (Docker containers)."""
    
    def __init__(self):
        self.running_bots: Dict[str, Dict[str, Any]] = {}

    def add_bot(self, bot_id: str, container, thread=None):
        """Add a running bot to the session manager."""
        self.running_bots[bot_id] = {
            "container": container,
            "thread": thread
        }
        logger.info(f"Bot {bot_id} added to session manager.")

    def remove_bot(self, bot_id: str):
        """Remove a bot from the session manager."""
        if bot_id in self.running_bots:
            del self.running_bots[bot_id]
            logger.info(f"Bot {bot_id} removed from session manager.")

    def get_bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """Get a running bot's data."""
        return self.running_bots.get(bot_id)

    def stop_bot(self, bot_id: str) -> bool:
        """Stop a running bot's container or subprocess."""
        bot_data = self.get_bot(bot_id)
        if bot_data:
            proc_or_container = bot_data.get("container")
            if proc_or_container:
                try:
                    # Docker container has a stop() method; subprocess has terminate()
                    if hasattr(proc_or_container, "stop"):
                        logger.info(f"Stopping bot {bot_id} container...")
                        proc_or_container.stop(timeout=10)
                    elif hasattr(proc_or_container, "terminate"):
                        logger.info(f"Terminating bot {bot_id} process...")
                        proc_or_container.terminate()
                        try:
                            proc_or_container.wait(timeout=5)
                        except Exception:
                            pass
                    else:
                        logger.warning(f"Unknown session type for {bot_id}; removing without stop")
                    return True
                except Exception as e:
                    logger.error(f"Error stopping session for bot {bot_id}: {e}")
                    return False
        return False

    def list_running_bots(self) -> Dict[str, Dict[str, Any]]:
        """List all running bots."""
        return {
            bot_id: {"status": "running"} 
            for bot_id in self.running_bots.keys()
        }


session_manager = SessionManager()
