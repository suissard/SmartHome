import ollama

DEFAULT_MODEL = "qwen2.5:7b"

def ask_llm(prompt, model=DEFAULT_MODEL, stream=True):
    """Envoie un prompt à Ollama et retourne la réponse"""
    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant vocal domotique. Réponds en français de manière claire, concise et directe (1 à 2 phrases max). N'utilise pas de markdown complexe."
        },
        {"role": "user", "content": prompt}
    ]

    response = ollama.chat(model=model, messages=messages, stream=stream)
    full_text = ""

    if stream:
        for chunk in response:
            content = chunk["message"]["content"]
            print(content, end="", flush=True)
            full_text += content
        print()
    else:
        full_text = response["message"]["content"]

    return full_text

if __name__ == "__main__":
    print(f"🧪 [DEBUG] Mode test Ollama ({DEFAULT_MODEL})...")
    while True:
        try:
            user_input = input("\nToi > ")
            if user_input.lower() in ["exit", "quit"]:
                break
            print("Assistant > ", end="", flush=True)
            ask_llm(user_input)
        except KeyboardInterrupt:
            break
