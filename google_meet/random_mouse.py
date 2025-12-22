import time
import random
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By


def random_mouse_movements(self, duration_seconds=8):
    """
    Perform random mouse movements within browser boundaries for a specified duration.
    
    Args:
        duration_seconds (int): Duration in seconds to perform random mouse movements
    """

    try:
        self.logger.info(f"Starting random mouse movements for {duration_seconds} seconds")
        
        # Get browser window size
        window_size = self.browser.get_window_size()
        width = window_size['width']
        height = window_size['height']
        
        # Set safety margins to stay away from edges
        margin = 100
        
        # Create action chain
        actions = ActionChains(self.browser)
        
        # Set end time
        end_time = time.time() + duration_seconds
        
        # Perform random movements until time is up
        while time.time() < end_time:
            try:
                # Move to a safe random absolute position instead of relative movement
                x_position = random.randint(margin, width - margin)
                y_position = random.randint(margin, height - margin)
                
                # Use move_to_location for absolute positioning
                actions.reset_actions()
                actions.move_by_offset(0, 0)  # Reset position
                
                # Find an element to use as reference
                body = self.browser.find_element(By.TAG_NAME, "body")
                actions.move_to_element(body).perform()
                
                # Then move to a position relative to the viewport
                script = f"""
                    const el = document.elementFromPoint({x_position}, {y_position});
                    if (el) {{
                        const rect = el.getBoundingClientRect();
                        return [el, rect.left + {x_position/2}, rect.top + {y_position/2}];
                    }} else {{
                        return [document.body, {x_position}, {y_position}];
                    }}
                """
                result = self.browser.execute_script(script)
                
                # Move to element with offset
                actions.reset_actions()
                actions.move_to_element_with_offset(
                    self.browser.execute_script("return arguments[0]", result[0]), 
                    min(20, int(result[1])), 
                    min(20, int(result[2]))
                ).perform()
                
                # Random pause between movements to simulate human behavior
                time.sleep(random.uniform(0.1, 0.3))
                
                # Occasionally pause for longer
                if random.random() < 0.1:
                    time.sleep(random.uniform(0.5, 1.0))
                    
            except Exception as e:
                self.logger.warning(f"Movement error (continuing): {str(e)}")
                # If any movement fails, move to center and continue
                try:
                    actions.reset_actions()
                    body = self.browser.find_element(By.TAG_NAME, "body")
                    actions.move_to_element(body).perform()
                    time.sleep(0.5)
                except:
                    pass
            
        self.logger.info("Completed random mouse movements")
    except Exception as e:
        self.logger.error(f"Error during random mouse movements: {e}")