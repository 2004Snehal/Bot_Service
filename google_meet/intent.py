import logging
import random
from sentence_transformers import SentenceTransformer, util

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IntentClassifier:
    """
    The Brain: Classifies user text into specific interruption categories
    using semantic similarity (all-MiniLM-L6-v2).
    """
    def __init__(self, model_name='all-MiniLM-L6-v2', threshold=0.10):
        logger.info("🧠 Loading IntentClassifier model...")
        self.model = SentenceTransformer(model_name)
        self.threshold = threshold
        self.topic_similarity_threshold = 0.35  # If query is >35% similar to current topic, it's side_chatter
        
        # Define Anchors
        self.anchors = {
            "urgent_override": [
                "Wait stop", "Hold on", "Pause please",
                "That is wrong", "I don't understand", "You are lying",
                "I can't hear you", "You are breaking up", "Too loud", "Repeat that",
                "Shut up", "Cancel", "Stop talking",
                "I have a question right now", "Wait what is X?",
                "What do you mean", "Can you explain", "What is that",
                "Before that", "Wait what", "Huh what"
            ],
            "defer_stack": [
                "By the way what about", "Quick question on the side", "Tangent but...",
                "Remind me later", "Put a pin in that", "Let's park that for now",
                "Also can you add...", "While we are on this topic", "Before you move on",
                "If that's true then what about...", "Assuming that works..."
            ],
            "side_chatter": [
                "Oh cool", "Yeah exactly", "Makes sense", "100 percent", "Agreed",
                "Okay", "Right", "Go on", "I see", "Uh huh",
                "Wow", "No way", "That is crazy", "Haha", "Nice",
                "Hey John", "Did you see that"
            ]
        }
        
        # Pre-compute embeddings
        logger.info("🧠 Pre-computing anchor embeddings...")
        self.anchor_embeddings = {
            key: self.model.encode(phrases) 
            for key, phrases in self.anchors.items()
        }
        logger.info("🧠 IntentClassifier ready.")

    def check_topic_similarity(self, user_query: str, current_topic: str) -> float:
        """
        Check if user query is related to the current topic being discussed.
        Returns similarity score (0.0 to 1.0).
        """
        if not current_topic or len(current_topic) < 5:
            return 0.0
        
        try:
            query_emb = self.model.encode(user_query)
            topic_emb = self.model.encode(current_topic)
            similarity = float(util.cos_sim(query_emb, topic_emb))
            logger.debug(f"   Topic similarity: {similarity:.2f}")
            return similarity
        except Exception as e:
            logger.error(f"Error computing topic similarity: {e}")
            return 0.0

    def classify(self, text: str, current_topic: str = None) -> str:
        """
        Returns: 'urgent_override', 'defer_stack', 'side_chatter', or 'noise'
        
        Args:
            text: User's speech/query
            current_topic: The current TTS transcript (what bot is/was saying)
        """
        if not text or len(text) < 2:
            return "noise"

        # Encode user input
        user_emb = self.model.encode(text)
        
        best_intent = "noise"
        highest_score = 0.0
        
        # Compare against all categories
        for intent, anchors_emb in self.anchor_embeddings.items():
            # util.cos_sim returns a tensor of scores, we take the max
            scores = util.cos_sim(user_emb, anchors_emb)
            max_score = float(scores.max())
            
            if max_score > highest_score:
                highest_score = max_score
                best_intent = intent
        
        logger.info(f"🔍 Intent Analysis: '{text}' -> {best_intent} (Score: {highest_score:.2f})")
        
        # Check if below threshold
        if highest_score < self.threshold:
            logger.info(f"   -> Below threshold ({self.threshold}), classifying as 'noise'")
            return "noise"
        
        # === TOPIC SIMILARITY CHECK ===
        # If user query is related to current topic, treat as side_chatter (clarification)
        if current_topic and best_intent == "urgent_override":
            topic_sim = self.check_topic_similarity(text, current_topic)
            if topic_sim > self.topic_similarity_threshold:
                logger.info(f"   -> Query related to current topic (sim={topic_sim:.2f}), upgrading to 'side_chatter'")
                return "side_chatter"
        # ==============================
            
        return best_intent


class ResponseStrategist:
    """
    The Coordinator: Decides WHAT to do based on the intent.
    """
    # Action Constants
    STOP_IMMEDIATE = "STOP_IMMEDIATE"       # Stop old, play filler, play new
    STACK_AND_RESUME = "STACK_AND_RESUME"   # Pause old, play filler, resume old, queue new
    YIELD_AND_RESUME = "YIELD_AND_RESUME"   # Pause old, play filler, resume old (no new)
    IGNORE = "IGNORE"

    def __init__(self):
        # FOR TESTING: Using reply.wav for all fillers
        # self.fillers = {
        #     "urgent_override": ["reply.wav"],
        #     "defer_stack": ["reply.wav"],
        #     "side_chatter": ["reply.wav"]
        # }
        self.fillers = {
            "urgent_override": [
                "urgent_checking.wav", 
                "urgent_one_sec.wav", 
                "urgent_clarifying.wav"
            ],
            "defer_stack": [
                "defer_noted.wav", 
                "defer_pin_that.wav", 
                "defer_after_this.wav"
            ],
            "side_chatter": [
                "ack_right.wav", 
                "ack_yeah.wav", 
                "ack_cool.wav"
            ]
        }

    def get_response_plan(self, intent: str):
        """
        Returns a plan object:
        {
            "action_type": str,
            "filler_wav": str (filename),
            "fetch_microservice": bool
        }
        """
        plan = {
            "action_type": self.IGNORE,
            "filler_wav": None,
            "fetch_microservice": False
        }

        if intent == "urgent_override":
            plan["action_type"] = self.STOP_IMMEDIATE
            plan["filler_wav"] = random.choice(self.fillers["urgent_override"])
            plan["fetch_microservice"] = True

        elif intent == "defer_stack":
            plan["action_type"] = self.STACK_AND_RESUME
            plan["filler_wav"] = random.choice(self.fillers["defer_stack"])
            plan["fetch_microservice"] = True

        elif intent == "side_chatter":
            plan["action_type"] = self.YIELD_AND_RESUME
            plan["filler_wav"] = random.choice(self.fillers["side_chatter"])
            plan["fetch_microservice"] = False
            
        return plan

# ==========================================
# MAIN EXECUTION BLOCK (SIMULATION)
# ==========================================
if __name__ == "__main__":
    print("\n🤖 Initializing System...")
    classifier = IntentClassifier()
    strategist = ResponseStrategist()
    
    test_cases = [
        "Wait, stop!", 
        "By the way, can you email me that?", 
        "Wow, nice.",
        "The weather is blue today" # Should be noise
    ]
    
    print("\n🚀 Starting Simulation:\n")
    
    for text in test_cases:
        print(f"🗣️  User says: '{text}'")
        
        # 1. Classify
        intent = classifier.classify(text)
        print(f"   🧠 Intent: {intent}")
        
        # 2. Strategize
        if intent != "noise":
            plan = strategist.get_response_plan(intent)
            print(f"   📋 Strategy: {plan['action_type']}")
            print(f"   🎵 Filler:   {plan['filler_wav']}")
            print(f"   📞 Call LLM: {plan['fetch_microservice']}")
        else:
            print("   🔇 Action: Ignore (Noise/Threshold not met)")
            
        print("-" * 40)
