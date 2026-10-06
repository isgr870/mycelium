import sys
import json
import urllib.request

URL = "http://localhost:5000/api/rag/query"

def chat():
    print("\033[1;32m=== Mycelium Mesh Interactive CLI ===\033[0m")
    print("Type your query or 'exit' / 'quit' to leave.\n")
    
    while True:
        try:
            prompt = input("\033[1;34mmycelium> \033[0m").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit"):
                break
            
            payload = json.dumps({"prompt": prompt}).encode("utf-8")
            req = urllib.request.Request(
                URL, 
                data=payload, 
                headers={"Content-Type": "application/json", "X-Mycelium-PIN": "7734"},
                method="POST"
            )
            
            print("\033[1;33mNode Response:\033[0m ", end="", flush=True)
            with urllib.request.urlopen(req) as response:
                for line in response:
                    line_str = line.decode("utf-8").strip()
                    if line_str.startswith("data:"):
                        raw_json = line_str[5:].strip()
                        try:
                            data = json.loads(raw_json)
                            if "token" in data:
                                print(data["token"], end="", flush=True)
                        except Exception:
                            pass
            print("\n")
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n\033[1;31m[Error]\033[0m {e}\n")

if __name__ == "__main__":
    chat()
