#!/usr/bin/env python3
"""
Monitor transcript extraction performance.
Shows real-time stats about DOM extraction frequency.
"""

import re
import sys
import time
from collections import defaultdict
from datetime import datetime

# ANSI colors
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'

class TranscriptMonitor:
    """Monitor transcript extraction logs and show stats."""
    
    def __init__(self):
        self.stats = defaultdict(int)
        self.start_time = time.time()
        self.last_update = time.time()
        
    def parse_log_line(self, line: str):
        """Parse a log line and update stats."""
        now = time.time()
        
        # Key events
        if "MutationObserver initialized" in line:
            self.stats['observer_initialized'] += 1
            print(f"{GREEN}✅ MutationObserver enabled!{RESET}")
        
        elif "DOM-change driven extraction enabled" in line:
            print(f"{GREEN}🔍 Event-driven mode active (90% less CPU){RESET}")
        
        elif "📝 Update:" in line:
            self.stats['caption_updates'] += 1
        
        elif "🎤 New:" in line:
            self.stats['new_utterances'] += 1
            # Extract speaker and text
            match = re.search(r'🎤 New: \[(.+?)\] (.+)', line)
            if match:
                speaker, text = match.groups()
                print(f"{BLUE}🎤 {speaker}: {text[:60]}...{RESET}")
        
        elif "✅ Finalized:" in line:
            self.stats['finalized'] += 1
            # Extract duration
            match = re.search(r'\((\d+)ms\)', line)
            if match:
                duration_ms = int(match.group(1))
                self.stats['total_duration_ms'] += duration_ms
                
            # Extract speaker and text
            match = re.search(r'Finalized: \[(.+?)\] (.+?)\.\.\. \(', line)
            if match:
                speaker, text = match.groups()
                print(f"{GREEN}✅ [{speaker}] {text[:50]}{RESET}")
        
        elif "Caption extraction error" in line:
            self.stats['extraction_errors'] += 1
        
        elif "MutationObserver check error" in line:
            self.stats['observer_errors'] += 1
        
        # Print stats every 10 seconds
        if now - self.last_update > 10:
            self.print_stats()
            self.last_update = now
    
    def print_stats(self):
        """Print current statistics."""
        elapsed = time.time() - self.start_time
        
        print(f"\n{YELLOW}{'=' * 60}{RESET}")
        print(f"{YELLOW}📊 Transcript Extraction Stats (after {elapsed:.0f}s){RESET}")
        print(f"{YELLOW}{'=' * 60}{RESET}")
        
        if self.stats['observer_initialized']:
            print(f"{GREEN}✓ MutationObserver: ENABLED{RESET}")
        else:
            print(f"{RED}✗ MutationObserver: Not initialized (using polling){RESET}")
        
        print(f"\n🎤 New utterances: {self.stats['new_utterances']}")
        print(f"📝 Caption updates: {self.stats['caption_updates']}")
        print(f"✅ Finalized: {self.stats['finalized']}")
        
        if self.stats['finalized'] > 0:
            avg_duration = self.stats['total_duration_ms'] / self.stats['finalized']
            print(f"⏱️  Avg utterance duration: {avg_duration/1000:.1f}s")
        
        # Performance indicators
        updates_per_min = (self.stats['caption_updates'] / elapsed) * 60
        print(f"\n📈 Update rate: {updates_per_min:.1f}/min")
        
        if updates_per_min > 30:
            print(f"{RED}⚠️  HIGH update rate - Observer may not be working{RESET}")
        else:
            print(f"{GREEN}✓ Normal update rate - Optimized extraction{RESET}")
        
        if self.stats['extraction_errors']:
            print(f"{YELLOW}⚠️  Extraction errors: {self.stats['extraction_errors']}{RESET}")
        
        print(f"{YELLOW}{'=' * 60}{RESET}\n")
    
    def final_report(self):
        """Print final report."""
        print(f"\n{GREEN}{'=' * 60}{RESET}")
        print(f"{GREEN}📋 FINAL REPORT{RESET}")
        print(f"{GREEN}{'=' * 60}{RESET}")
        self.print_stats()


def main():
    """Monitor stdin for transcript logs."""
    print(f"{BLUE}🔍 Transcript Monitor Started{RESET}")
    print(f"{BLUE}Reading logs from stdin... (pipe bot logs here){RESET}\n")
    
    monitor = TranscriptMonitor()
    
    try:
        for line in sys.stdin:
            line = line.strip()
            if line:
                monitor.parse_log_line(line)
    
    except KeyboardInterrupt:
        print(f"\n{YELLOW}⏹️  Monitoring stopped{RESET}")
    
    finally:
        monitor.final_report()


if __name__ == "__main__":
    main()
