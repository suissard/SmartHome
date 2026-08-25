import ollama
from config import (
    OLLAMA_MODEL,
    OLLAMA_HOST,
    LLM_SYSTEM_PROMPT,
    LLM_STREAM,
)

DEFAULT_MODEL = OLLAMA_MODEL
_client = ollama.Client(host=OLLAMA_HOST) if OLLAMA_HOST else ollama.Client()

def ask_llm(prompt, model=DEFAULT_MODEL, system_prompt=LLM_SYSTEM_PROMPT, stream=LLM_STREAM):
    """Envoie un prompt à Ollama et retourne la réponse"""
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {"role": "user", "content": prompt}
    ]

    response = _client.chat(model=model, messages=messages, stream=stream)
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
    print(f"🧪 [DEBUG] Mode test Ollama (Modèle: {DEFAULT_MODEL}, Host: {OLLAMA_HOST})...")
    while True:
        try:
            user_input = input("\nToi > ")
            if user_input.lower() in ["exit", "quit"]:
                break
            print("Assistant > ", end="", flush=True)
            ask_llm(user_input)
        except KeyboardInterrupt:
            break

