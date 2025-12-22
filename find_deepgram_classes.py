import deepgram
import pkgutil
import inspect
import sys

target_classes = ["LiveTranscriptionEvents", "LiveOptions", "LiveResultResponse"]

print(f"Searching for {target_classes} in deepgram package...")

def find_classes(package):
    for importer, modname, ispkg in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        try:
            # Skip some modules that might cause side effects or errors
            if "test" in modname or "example" in modname:
                continue
                
            module = __import__(modname, fromlist="dummy")
            
            for target in target_classes:
                if hasattr(module, target):
                    print(f"✅ FOUND {target} in {modname}")
                    
        except Exception as e:
            # print(f"  Could not import {modname}: {e}")
            pass

find_classes(deepgram)
print("Search complete.")
