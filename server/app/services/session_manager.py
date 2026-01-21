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
        """Stop a running bot's container or subprocess with verification."""
        bot_data = self.get_bot(bot_id)
        stopped = False
        
        if bot_data:
            proc_or_container = bot_data.get("container")
            if proc_or_container:
                try:
                    # Docker container
                    if hasattr(proc_or_container, "stop"):
                        logger.info(f"Stopping bot {bot_id} container...")
                        
                        # Check container status before stopping
                        try:
                            proc_or_container.reload()  # Refresh container info
                            status = proc_or_container.status
                            logger.info(f"Container status before stop: {status}")
                            
                            # Log last 50 lines to verify it's actually running
                            try:
                                logs = proc_or_container.logs(tail=50)
                                logger.info(f"Container logs (last 50 lines): {logs.decode(errors='ignore')[:500]}")
                            except Exception as log_err:
                                logger.warning(f"Could not fetch container logs: {log_err}")
                        except Exception as reload_err:
                            logger.warning(f"Could not reload container status: {reload_err}")
                        
                        # Stop the container
                        proc_or_container.stop(timeout=10)
                        logger.info(f"Container stopped successfully for bot {bot_id}")
                        stopped = True
                        
                        # Try to remove if it still exists
                        try:
                            proc_or_container.remove(force=True)
                            logger.info(f"Container removed for bot {bot_id}")
                        except Exception as rm_err:
                            logger.warning(f"Could not remove container (may be auto-removed): {rm_err}")
                    
                    # Subprocess
                    elif hasattr(proc_or_container, "terminate"):
                        logger.info(f"Terminating bot {bot_id} process (PID: {proc_or_container.pid})...")
                        proc_or_container.terminate()
                        try:
                            proc_or_container.wait(timeout=5)
                            logger.info(f"Process terminated for bot {bot_id}")
                            stopped = True
                        except Exception as wait_err:
                            logger.warning(f"Process didn't terminate gracefully, killing: {wait_err}")
                            proc_or_container.kill()
                            stopped = True
                    else:
                        logger.warning(f"Unknown session type for {bot_id}; removing without stop")
                        stopped = True
                        
                except Exception as e:
                    logger.error(f"Error stopping session for bot {bot_id}: {e}")
                    return False
            else:
                logger.warning(f"Bot {bot_id} found in session manager but has no container/process")
                stopped = True  # Consider it stopped if there's no container
        else:
            logger.warning(f"Bot {bot_id} not found in session manager")
        
        # Always remove from tracking, even if stop failed
        self.remove_bot(bot_id)
        return stopped
    
    def force_cleanup_bot(self, bot_id: str, meeting_id: str = None) -> bool:
        """Force cleanup of bot containers by name pattern, even if not tracked."""
        try:
            import docker
            client = docker.from_env()
            
            # Find containers by name pattern
            container_pattern = f"bot_{bot_id}"
            if meeting_id:
                container_pattern = f"bot_{bot_id}_{meeting_id[:8]}"
            
            logger.info(f"Looking for containers matching pattern: {container_pattern}")
            
            containers = client.containers.list(all=True, filters={"name": container_pattern})
            if containers:
                for container in containers:
                    logger.info(f"Found orphaned container: {container.name} (status: {container.status})")
                    try:
                        if container.status == 'running':
                            container.stop(timeout=10)
                            logger.info(f"Stopped container: {container.name}")
                        container.remove(force=True)
                        logger.info(f"Removed container: {container.name}")
                    except Exception as e:
                        logger.error(f"Error cleaning up container {container.name}: {e}")
                return True
            else:
                logger.info(f"No containers found matching pattern: {container_pattern}")
                return False
                
        except Exception as e:
            logger.error(f"Error in force cleanup for bot {bot_id}: {e}")
            return False

    def list_running_bots(self) -> Dict[str, Dict[str, Any]]:
        """List all running bots."""
        return {
            bot_id: {"status": "running"} 
            for bot_id in self.running_bots.keys()
        }


session_manager = SessionManager()
