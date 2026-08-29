import base64
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
    LLM_HISTORY_MESSAGES,
    ACTIONS_DYNAMIC_PROMPT,
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

# Historique conversationnel en mémoire
_conversation_history: list[dict] = []


def get_default_system_prompt() -> str:
    """Retourne le prompt système enrichi dynamiquement avec les commandes d'actions."""
    if ACTIONS_DYNAMIC_PROMPT:
        try:
            from actions.manager import get_action_manager
            return get_action_manager().build_dynamic_system_prompt(LLM_SYSTEM_PROMPT)
        except Exception as e:
            print(f"⚠️ [LLM] Erreur lors de la construction du prompt dynamique : {e}")
            return LLM_SYSTEM_PROMPT
    return LLM_SYSTEM_PROMPT


def get_history() -> list[dict]:
    """Retourne une copie de l'historique actuel de la conversation."""
    return list(_conversation_history)


def clear_history():
    """Réinitialise l'historique de conversation."""
    global _conversation_history
    _conversation_history.clear()


def add_history_message(role: str, content: str):
    """Ajoute un message à l'historique et tronque selon LLM_HISTORY_MESSAGES."""
    global _conversation_history
    if LLM_HISTORY_MESSAGES > 0:
        _conversation_history.append({"role": role, "content": content})
        if len(_conversation_history) > LLM_HISTORY_MESSAGES:
            _conversation_history = _conversation_history[-LLM_HISTORY_MESSAGES:]


def _ask_openrouter(
    prompt: str = None,
    audio_bytes: bytes = None,
    model: str = None,
    system_prompt: str = None,
    stream: bool = LLM_STREAM,
    use_history: bool = True,
) -> str:
    """Envoie un prompt texte ou un enregistrement audio à OpenRouter (OpenAI-compatible) et retourne la réponse."""
    if not OPENROUTER_API_KEY:
        error_msg = "⚠️ Clé API OpenRouter manquante ! Veuillez renseigner OPENROUTER_API_KEY dans votre fichier .env."
        print(f"\n{error_msg}")
        return error_msg

    target_model = model or OPENROUTER_MODEL
    effective_system_prompt = system_prompt or get_default_system_prompt()

    # Construction de la liste des messages avec prompt système
    messages = [{"role": "system", "content": effective_system_prompt}]

    # Injection de l'historique conversationnel récent
    if use_history and LLM_HISTORY_MESSAGES > 0 and _conversation_history:
        messages.extend(_conversation_history[-LLM_HISTORY_MESSAGES:])

    # Construction du message utilisateur courant (Texte simple ou Multimodal Audio)
    if audio_bytes:
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        user_content = [
            {
                "type": "input_audio",
                "input_audio": {
                    "data": audio_b64,
                    "format": "wav"
                }
            }
        ]
        if prompt:
            user_content.insert(0, {"type": "text", "text": prompt})

        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": prompt or ""})

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

        # Enregistrement dans l'historique conversationnel
        if use_history and full_text and not full_text.startswith("⚠️"):
            user_turn_text = prompt or ("🎙️ [Message vocal]" if audio_bytes else "")
            add_history_message("user", user_turn_text)
            add_history_message("assistant", full_text)

        return full_text

    except Exception as e:
        err_str = f"⚠️ Erreur OpenRouter : {e}"
        print(f"\n{err_str}")
        return err_str


def _ask_ollama(
    prompt: str = None,
    audio_bytes: bytes = None,
    model: str = None,
    system_prompt: str = None,
    stream: bool = LLM_STREAM,
    think: bool = LLM_THINK,
    use_history: bool = True,
) -> str:
    """Envoie un prompt à Ollama local et retourne la réponse."""
    target_model = model or OLLAMA_MODEL
    effective_system_prompt = system_prompt or get_default_system_prompt()

    if audio_bytes and not prompt:
        prompt = "Veuillez traiter cet enregistrement audio."

    # Construction de la liste des messages avec prompt système
    messages = [{"role": "system", "content": effective_system_prompt}]

    # Injection de l'historique conversationnel récent
    if use_history and LLM_HISTORY_MESSAGES > 0 and _conversation_history:
        messages.extend(_conversation_history[-LLM_HISTORY_MESSAGES:])

    messages.append({"role": "user", "content": prompt or ""})

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

        # Enregistrement dans l'historique conversationnel
        if use_history and full_text and not full_text.startswith("⚠️"):
            user_turn_text = prompt or ("🎙️ [Message vocal]" if audio_bytes else "")
            add_history_message("user", user_turn_text)
            add_history_message("assistant", full_text)

        return full_text

    except Exception as e:
        err_str = f"⚠️ Erreur Ollama : {e}"
        print(f"\n{err_str}")
        return err_str


def ask_llm(
    prompt: str = None,
    audio_bytes: bytes = None,
    model: str = None,
    system_prompt: str = None,
    stream: bool = LLM_STREAM,
    think: bool = LLM_THINK,
    use_history: bool = True,
) -> str:
    """Route la demande vers le fournisseur LLM configuré (Ollama ou OpenRouter) avec gestion d'historique."""
    if LLM_PROVIDER == "openrouter":
        return _ask_openrouter(
            prompt=prompt,
            audio_bytes=audio_bytes,
            model=model or OPENROUTER_MODEL,
            system_prompt=system_prompt,
            stream=stream,
            use_history=use_history,
        )
    else:
        return _ask_ollama(
            prompt=prompt,
            audio_bytes=audio_bytes,
            model=model or OLLAMA_MODEL,
            system_prompt=system_prompt,
            stream=stream,
            think=think,
            use_history=use_history,
        )


if __name__ == "__main__":
    active_model = OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else OLLAMA_MODEL
    print(f"🧪 [DEBUG] Mode test LLM (Fournisseur: {LLM_PROVIDER.upper()}, Modèle: {active_model})")
    print(f"🧠 Mémoire historique active : {LLM_HISTORY_MESSAGES} messages (Tapez /clear pour vider, /history pour afficher)")
    while True:
        try:
            user_input = input("\nToi > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                break
            if user_input.lower() in ["/clear", "/reset"]:
                clear_history()
                print("🧹 Historique réinitialisé.")
                continue
            if user_input.lower() == "/history":
                hist = get_history()
                print(f"📜 Historique actuel ({len(hist)}/{LLM_HISTORY_MESSAGES}) :")
                for i, msg in enumerate(hist, 1):
                    print(f"  {i}. [{msg['role'].upper()}] {msg['content']}")
                continue

            print("Assistant > ", end="", flush=True)
            ask_llm(user_input)
        except KeyboardInterrupt:
            break


