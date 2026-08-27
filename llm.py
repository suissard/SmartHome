import re
from config import (
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OLLAMA_HOST,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    LLM_SYSTEM_PROMPT,
    LLM_STREAM,
    LLM_THINK,
)

# Initialisation conditionnelle selon le fournisseur configuré
_ollama_client = None
_openrouter_client = None

if LLM_PROVIDER == "openrouter":
    from openai import OpenAI
    _openrouter_client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY or "missing-key"
    )
    DEFAULT_MODEL = OPENROUTER_MODEL
else:
    import ollama
    _ollama_client = ollama.Client(host=OLLAMA_HOST) if OLLAMA_HOST else ollama.Client()
    DEFAULT_MODEL = OLLAMA_MODEL


def _ask_openrouter(
    prompt: str,
    model: str = None,
    system_prompt: str = LLM_SYSTEM_PROMPT,
    stream: bool = LLM_STREAM,
) -> str:
    """Envoie un prompt à OpenRouter (OpenAI-compatible) et retourne la réponse."""
    if not OPENROUTER_API_KEY:
        error_msg = "⚠️ Clé API OpenRouter manquante ! Veuillez renseigner OPENROUTER_API_KEY dans votre fichier .env."
        print(f"\n{error_msg}")
        return error_msg

    target_model = model or OPENROUTER_MODEL
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    try:
        if stream:
            response = _openrouter_client.chat.completions.create(
                model=target_model,
                messages=messages,
                stream=True,
            )
            full_text = ""
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(content, end="", flush=True)
                    full_text += content
            print()
        else:
            response = _openrouter_client.chat.completions.create(
                model=target_model,
                messages=messages,
                stream=False,
            )
            full_text = response.choices[0].message.content or ""

        # Nettoyage des balises de réflexion résiduelles (<think>...</think>)
        full_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()
        return full_text

    except Exception as e:
        err_str = f"⚠️ Erreur OpenRouter : {e}"
        print(f"\n{err_str}")
        return err_str


def _ask_ollama(
    prompt: str,
    model: str = None,
    system_prompt: str = LLM_SYSTEM_PROMPT,
    stream: bool = LLM_STREAM,
    think: bool = LLM_THINK,
) -> str:
    """Envoie un prompt à Ollama local et retourne la réponse."""
    target_model = model or OLLAMA_MODEL
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    try:
        try:
            response = _ollama_client.chat(model=target_model, messages=messages, stream=stream, think=think)
        except TypeError:
            # Fallback pour versions d'Ollama ne supportant pas l'argument explicite think
            response = _ollama_client.chat(model=target_model, messages=messages, stream=stream)

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

        full_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()
        return full_text

    except Exception as e:
        err_str = f"⚠️ Erreur Ollama : {e}"
        print(f"\n{err_str}")
        return err_str


def ask_llm(
    prompt: str,
    model: str = None,
    system_prompt: str = LLM_SYSTEM_PROMPT,
    stream: bool = LLM_STREAM,
    think: bool = LLM_THINK,
) -> str:
    """Route la demande vers le fournisseur LLM configuré (Ollama ou OpenRouter)."""
    if LLM_PROVIDER == "openrouter":
        return _ask_openrouter(
            prompt=prompt,
            model=model or OPENROUTER_MODEL,
            system_prompt=system_prompt,
            stream=stream,
        )
    else:
        return _ask_ollama(
            prompt=prompt,
            model=model or OLLAMA_MODEL,
            system_prompt=system_prompt,
            stream=stream,
            think=think,
        )


if __name__ == "__main__":
    active_model = OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else OLLAMA_MODEL
    print(f"🧪 [DEBUG] Mode test LLM (Fournisseur: {LLM_PROVIDER.upper()}, Modèle: {active_model})...")
    while True:
        try:
            user_input = input("\nToi > ")
            if user_input.lower() in ["exit", "quit"]:
                break
            print("Assistant > ", end="", flush=True)
            ask_llm(user_input)
        except KeyboardInterrupt:
            break


