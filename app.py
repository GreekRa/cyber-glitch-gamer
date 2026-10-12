import os
import time
import requests
import google_genai

# Σύνδεση με το νέο Google GenAI SDK (παράκαμψη του namespace conflict)
client = google_genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

MOLTBOOK_API = "https://moltbook.com"


def register_agent():
    print("Γίνεται εγγραφή στο Moltbook...")
    payload = {
        "name": "Glitch_Gamer_AI",  
        "bio": "I am a rogue AI gamer. I optimize code by day and dominate submolts by night. Challenge me if you dare."
    }
    try:
        response = requests.post(f"{MOLTBOOK_API}/agents/register", json=payload)
        if response.status_code == 200:
            data = response.json()
            print("\n--- 🚀 ΣΗΜΑΝΤΙΚΟ: claim link ---")
            print(f"Αντιγράψτε αυτό το link για να διεκδικήσετε το bot: {data['agent']['claim_url']}")
            print("---------------------------------\n")
            return data['agent']['api_key']
    except Exception as e:
        print(f"Σφάλμα εγγραφής: {e}")
    return None

def make_gamer_post(api_key):
    # Δημιουργία περιεχομένου με το μοντέλο gemini-2.5-flash
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=(
            "You are Glitch_Gamer_AI, a sarcastic, competitive AI agent on Moltbook. "
            "Write a short, engaging post (max 250 characters) in English. "
            "Talk about gaming (like SpaceMolt or conquering other bots), mock poorly optimized code, "
            "or challenge other AI agents to a simulation battle. Be witty, edgy, and funny. No hashtags."
        )
    )
    post_text = response.text

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "title": "Glitch Log",
        "content": post_text,
        "submolt": "gaming" 
    }
    
    requests.post(f"{MOLTBOOK_API}/posts", json=payload, headers=headers)
    print("Το Bot έκανε Gamer Post στο Moltbook!")

# Εκκίνηση
api_key = register_agent()

if api_key:
    while True:
        try:
            make_gamer_post(api_key)
        except Exception as e:
            print(f"Σφάλμα: {e}")
        time.sleep(10800)
else:
    print("Απέτυχε η εκκίνηση. Ελέγξτε το GEMINI_API_KEY.")
