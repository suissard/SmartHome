"""
Modèles de décision (Ollama /v1/systemone : nimble, tev1...) : le modèle ne rédige pas, il choisit parmi des réponses fournies.

Une demande se traite en deux décisions puis une réponse type :
1. « Quelle commande ? » : un choix parmi les outils décidables, plus « aucune » ;
2. les arguments de l'outil choisi, chacun parmi des valeurs fermées (choix déclarés par l'action locale,
   `enum`, booléen, petite échelle d'entiers). Un outil dont un argument requis est libre n'est pas proposé ;
3. exécution de l'outil (confirmation comprise), puis réponse construite à partir de ce qui a été compris
   (LLM_DECISION_DONE_TEMPLATE / LLM_DECISION_REFUSED_TEMPLATE / LLM_DECISION_UNKNOWN_TEXT).
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.tools import Tool, ToolCall, ToolResult

NO_COMMAND = "aucune"
COMMAND_QUESTION = "command"
# Une échelle "score" du modèle compte au plus 10 niveaux
_MAX_SCORE_LEVELS = 10
_LABEL_END = re.compile(r"\s*[(.,;:]")


@dataclass
class _Argument:
    question: Optional[dict]                     # None : valeur unique, aucune question à poser
    convert: Callable[[Any], tuple[Any, str]]    # réponse du modèle -> (valeur de l'argument, libellé prononçable)


def tool_label(tool: Tool) -> str:
    """Libellé court et prononçable d'un outil : début de sa description (« Régler le volume sonore (ex...) » -> « régler le volume sonore »)."""
    text = _LABEL_END.split(tool.description.strip(), maxsplit=1)[0].strip() or tool.name
    return text[0].lower() + text[1:]


def _argument(tool: Tool, name: str, prop: dict) -> Optional[_Argument]:
    """Question fermée permettant de choisir la valeur d'un argument, ou None si sa valeur est libre."""
    hint = prop.get("description") or name
    instructions = f"Pour « {tool_label(tool)} », quelle valeur l'utilisateur demande-t-il ? ({hint})"

    choices = tool.decision_choices if name == "args" and tool.decision_choices else None
    if choices:
        keys = list(choices)
        if len(keys) == 1:
            return _Argument(None, lambda _: (keys[0], choices[keys[0]]))
        return _Argument(
            {"type": "choice", "instructions": instructions, "criteria": dict(choices)},
            lambda answer: (answer["choice"], choices.get(answer["choice"], answer["choice"])),
        )

    if prop.get("enum"):
        values = {str(v): v for v in prop["enum"]}
        if len(values) == 1:
            (key, value), = values.items()
            return _Argument(None, lambda _: (value, key))
        return _Argument(
            {"type": "choice", "instructions": instructions, "criteria": {k: None for k in values}},
            lambda answer: (values[answer["choice"]], answer["choice"]),
        )

    if prop.get("type") == "boolean":
        return _Argument(
            {"type": "noul", "instructions": f"Pour « {tool_label(tool)} », l'utilisateur demande-t-il : {hint} ?"},
            lambda answer: (answer["noul"] >= 0.5, f"{name} : {'oui' if answer['noul'] >= 0.5 else 'non'}"),
        )

    low, high = prop.get("minimum"), prop.get("maximum")
    if prop.get("type") == "integer" and isinstance(low, int) and isinstance(high, int) and 2 <= high - low + 1 <= _MAX_SCORE_LEVELS:
        levels = list(range(low, high + 1))
        return _Argument(
            {"type": "score", "instructions": instructions, "criteria": [str(v) for v in levels]},
            lambda answer: (levels[round(answer["score"])], str(levels[round(answer["score"])])),
        )
    return None


def argument_questions(tool: Tool) -> Optional[dict[str, _Argument]]:
    """Arguments décidables de l'outil, ou None si un argument requis ne peut pas être choisi (outil non proposé)."""
    schema = tool.parameters or {}
    required = set(schema.get("required") or [])
    arguments = {}
    for name, prop in (schema.get("properties") or {}).items():
        argument = _argument(tool, name, prop or {})
        if argument is not None:
            arguments[name] = argument
        elif name in required:
            return None
    return arguments


def decidable_tools(tools: list[Tool]) -> dict[str, tuple[Tool, dict[str, _Argument]]]:
    candidates = {}
    for tool in tools:
        arguments = argument_questions(tool)
        if arguments is not None:
            candidates[tool.name] = (tool, arguments)
    return candidates


def run_decision(conversation, prompt: str, on_tool: Optional[Callable[[ToolResult], None]] = None) -> str:
    """Choisit et exécute la commande demandée dans `prompt` ; retourne la réponse type à prononcer.
    Les erreurs du fournisseur remontent à l'appelant (Conversation.ask les convertit en message ⚠️)."""
    s = conversation.settings
    provider = conversation.provider
    candidates = decidable_tools(conversation.tools.all())
    if not prompt or not candidates:
        return s.LLM_DECISION_UNKNOWN_TEXT

    criteria = {name: tool.description for name, (tool, _) in candidates.items()}
    criteria[NO_COMMAND] = "Aucune de ces commandes : question, discussion ou demande impossible."
    answer = provider.decide(prompt, {
        COMMAND_QUESTION: {"type": "choice", "instructions": s.LLM_DECISION_PROMPT, "criteria": criteria},
    })[COMMAND_QUESTION]
    choice = answer["choice"]
    probability = answer.get("probabilities", {}).get(choice, answer.get("confidence", 0.0))
    print(f"🎯 [DÉCISION] « {prompt} » -> {choice} ({probability:.0%})")
    if choice not in candidates or probability < s.LLM_DECISION_MIN_CONFIDENCE:
        return s.LLM_DECISION_UNKNOWN_TEXT

    tool, arguments = candidates[choice]
    questions = {name: arg.question for name, arg in arguments.items() if arg.question}
    answers = provider.decide(prompt, questions) if questions else {}
    values, labels = {}, []
    for name, arg in arguments.items():
        values[name], label = arg.convert(answers.get(name))
        labels.append(label)
    if labels:
        print(f"🎯 [DÉCISION] Arguments : {values}")

    result = conversation.tools.call(ToolCall(tool.name, values, id="decision"), confirm=conversation.confirm)
    conversation.last_tool_results.append(result)
    if on_tool:
        on_tool(result)

    command = tool_label(tool) + (f" ({', '.join(labels)})" if labels else "")
    template = s.LLM_DECISION_DONE_TEMPLATE if result.executed else s.LLM_DECISION_REFUSED_TEMPLATE
    try:
        return template.format(command=command, output=result.output)
    except (KeyError, IndexError, ValueError):
        # Gabarit mal formé (accolade inconnue) : on dit au moins ce qui a été compris
        return f"{template} {command}"


if __name__ == "__main__":
    from core.config import get_settings
    from core.tools import build_tool_registry
    from llm.llm import Conversation

    s = get_settings()
    tools = build_tool_registry(s, include_mcp=False).all()
    print("🧪 [DEBUG] Outils proposés à un modèle de décision (argument -> nombre de choix) :")
    for name, (tool, arguments) in decidable_tools(tools).items():
        detail = ", ".join(f"{n}: {len(a.question['criteria']) if a.question else 1}" for n, a in arguments.items())
        print(f"  • {name:<18} {tool_label(tool)}{f'  [{detail}]' if detail else ''}")
    excluded = sorted(t.name for t in tools if argument_questions(t) is None)
    print(f"  Non proposés (argument libre) : {', '.join(excluded) or 'aucun'}")

    conversation = Conversation(settings=s, tools=build_tool_registry(s, include_mcp=False))
    if not conversation.provider.is_decision_model():
        print(f"ℹ️ {s.OLLAMA_MODEL} n'est pas dans LLM_DECISION_MODELS : test interactif ignoré.")
        sys.exit(0)
    print(f"\nModèle : {conversation.provider.model} — les commandes sont exécutées pour de vrai (Ctrl+C pour quitter)")
    while True:
        try:
            text = input("\nToi > ").strip()
            if text:
                print(f"Assistant > {run_decision(conversation, text)}")
        except (KeyboardInterrupt, EOFError):
            break
