import re
import ollama
from config import (
    OLLAMA_MODEL,
    OLLAMA_HOST,
    LLM_SYSTEM_PROMPT,
    LLM_STREAM,
    LLM_THINK,
)

DEFAULT_MODEL = OLLAMA_MODEL
_client = ollama.Client(host=OLLAMA_HOST) if OLLAMA_HOST else ollama.Client()


def ask_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = LLM_SYSTEM_PROMPT,
    stream: bool = LLM_STREAM,
    think: bool = LLM_THINK,
) -> str:
    """Envoie un prompt à Ollama et retourne la réponse avec option de désactivation du thinking."""
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {"role": "user", "content": prompt}
    ]

    try:
        response = _client.chat(model=model, messages=messages, stream=stream, think=think)
    except TypeError:
        # Fallback pour versions d'Ollama ne supportant pas l'argument explicite think
        response = _client.chat(model=model, messages=messages, stream=stream)

    full_text = ""

    if stream:
        for chunk in response:
            msg = chunk.message if hasattr(chunk, "message") else chunk.get("message", {})
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if content:
                print(content, end="", flush=True)
                full_text += content
        print()
    else:
        msg = response.message if hasattr(response, "message") else response.get("message", {})
        full_text = msg.content if hasattr(msg, "content") else msg.get("content", "")

    # Nettoyage des balises de réflexion résiduelles éventuelles (<think>...</think>)
    full_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()

    return full_text


if __name__ == "__main__":
    print(f"🧪 [DEBUG] Mode test Ollama (Modèle: {DEFAULT_MODEL}, Host: {OLLAMA_HOST}, Think: {LLM_THINK})...")
    while True:
        try:
            user_input = input("\nToi > ")
            if user_input.lower() in ["exit", "quit"]:
                break
            print("Assistant > ", end="", flush=True)
            ask_llm(user_input)
        except KeyboardInterrupt:
            break


