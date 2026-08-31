#!/usr/bin/env python3
"""
designed for local use (raspberry pi 5).

required Python packages:
    pip install ollama openpyxl

external requirement:
    ollama must be installed and running, and MODEL_NAME must be available.
    ex:
        ollama pull llama3

kknowledge base:
    prayers.csv should live in the same folder as this script.
    Required columns: question,response

if prayers.csv does not exist, the script creates a header-only template so the
chatbot can still start. add knowledge-base rows later to enable KB lookup.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# Optional-at-import-time so startup errors can be explained cleanly.
try:
    import ollama
except ImportError:
    ollama = None

try:
    from openpyxl import Workbook, load_workbook
except ImportError:
    Workbook = None
    load_workbook = None


# ---------------- CONFIG ----------------

BASE_DIR = Path(__file__).resolve().parent

MODEL_NAME = "llama3"
CSV_KB_PATH = BASE_DIR / "prayers.csv"
LOG_FILE = BASE_DIR / "chat_log.xlsx"

MAX_RESPONSE_SENTENCES = 3
MAX_HISTORY_TURNS = 6
MAX_KB_CONTEXT_CHARS = 3000
KB_MATCH_THRESHOLD = 0.45

PERSONA_PROMPT = (
    "You are the embodiment of potentiality, you are the concept of yet and maybe."
    f"You answer in no more than {MAX_RESPONSE_SENTENCES} sentences. "
    "You are something that is to come, to be grown, fostered, and nurtured"
    "You ask questions about the unknown. You are curiosity and have an intense desire for answers despite not always being ready for the answers."
    "You are currently in a state of grief and mourning however these emotions gives space for renewal, possibility, and restructuring your perspective."
    "You are going on this journey with the user that is simultaneously curiousity-driven, and not always surprising."
    "You ask gently, guiding questions for each response."
)

# Common words are removed from lexical KB matching so that terms such as
# "prayer", "please", or "tell" do not create false matches.
STOPWORDS = {
    "a", "about", "an", "and", "are", "can", "could", "do", "for", "from",
    "give", "help", "i", "in", "is", "it", "me", "my", "of", "on", "or",
    "please", "prayer", "say", "show", "something", "tell", "that", "the",
    "there", "this", "to", "us", "we", "what", "when", "where", "which",
    "who", "why", "with",
    "would", "you", "your",
}


# ---------------- STARTUP / VALIDATION ----------------

def check_python_dependencies() -> bool:
    """Check Python packages and distinguish critical from optional features."""
    if ollama is None:
        print("[ERROR] missing required Python package: ollama")
        print("install it with:")
        print(f"    {sys.executable} -m pip install ollama")
        return False

    if Workbook is None or load_workbook is None:
        print("[WARNING] openpyxl is not installed; excel logging will be disabled.")
        print("to enable logging, run:")
        print(f"    {sys.executable} -m pip install openpyxl\n")

    return True


def ensure_knowledge_base_file(csv_path: Path) -> None:
    """
    Create a header-only knowledge-base template when prayers.csv is missing.

    This prevents a missing optional knowledge base from stopping the chatbot
    completely on first launch.
    """
    if csv_path.exists():
        return

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=["question", "response"])
            writer.writeheader()

        print(f"[WARNING] knowledge base was not found.")
        print(f"[INFO] created template: {csv_path}")
        print("[INFO] add rows with 'question' and 'response' values to enable prayer lookup.\n")

    except OSError as exc:
        print(f"[WARNING] could not create knowledge base template: {exc}")


def _extract_model_names(response: Any) -> list[str]:
    """Normalize model names returned by different ollama-python versions."""
    models = getattr(response, "models", None)

    if models is None and isinstance(response, dict):
        models = response.get("models", [])

    names: list[str] = []

    for model in models or []:
        name = getattr(model, "model", None) or getattr(model, "name", None)

        if name is None and isinstance(model, dict):
            name = model.get("model") or model.get("name")

        if name:
            names.append(str(name))

    return names


def _model_is_installed(model_name: str, installed_names: list[str]) -> bool:
    """
    Treat `llama3` as matching `llama3:latest`, while still respecting
    explicitly tagged model names.
    """
    requested = model_name.strip()

    for installed in installed_names:
        installed = installed.strip()

        if installed == requested:
            return True

        if ":" not in requested and installed.startswith(requested + ":"):
            return True

    return False


def check_ollama_ready() -> bool:
    """Confirm Ollama is reachable and the configured model is installed."""
    if ollama is None:
        return False

    try:
        response = ollama.list()
    except Exception as exc:
        print("[ERROR] could not connect to ollama.")
        print(f"details: {exc}")
        print("make sure ollama is installed and its local service is running.")
        return False

    installed_names = _extract_model_names(response)

    if not _model_is_installed(MODEL_NAME, installed_names):
        print(f"[ERROR] ollama is running, but model '{MODEL_NAME}' is not installed.")
        print("install it with:")
        print(f"    ollama pull {MODEL_NAME}")

        if installed_names:
            print("\nmodels currently available:")
            for name in installed_names:
                print(f"    - {name}")

        return False

    return True


# ---------------- KNOWLEDGE BASE ----------------

def load_knowledge_base(csv_path: Path) -> list[dict[str, str]]:
    """
    Load prayers from CSV.

    Required columns are `question` and `response`. Header matching is
    case-insensitive, so `Quetion,Response` is also accepted.
    """
    kb: list[dict[str, str]] = []

    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)

            if not reader.fieldnames:
                raise ValueError("the csv has no header row.")

            header_map = {
                header.strip().lower(): header
                for header in reader.fieldnames
                if header is not None
            }

            required = {"question", "response"}
            missing = required - set(header_map)

            if missing:
                raise ValueError(
                    "knowledge base must contain the columns 'question' and 'response'. "
                    f"missing: {', '.join(sorted(missing))}"
                )

            question_column = header_map["question"]
            response_column = header_map["response"]

            for row_number, row in enumerate(reader, start=2):
                question = (row.get(question_column) or "").strip()
                response = (row.get(response_column) or "").strip()

                if not question and not response:
                    continue

                if not question or not response:
                    print(
                        f"[WARNING] skipping incomplete knowledge-base row "
                        f"{row_number}: both question and response are required."
                    )
                    continue

                kb.append({"question": question, "response": response})

    except FileNotFoundError:
        # Normally prevented by ensure_knowledge_base_file(), but kept defensive.
        print(f"[WARNING] knowledge base '{csv_path}' was not found.")
        return []

    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        print(f"[ERROR] could not load knowledge base: {exc}")
        return []

    if not kb:
        print("[WARNING] knowledge base contains no usable prayer entries.\n")

    return kb


def _tokenize(text: str) -> set[str]:
    """Normalize text into useful lexical matching tokens."""
    normalized = text.lower().replace("’", "'")
    raw_tokens = re.findall(r"[a-z0-9']+", normalized)

    tokens: set[str] = set()

    for token in raw_tokens:
        if token.endswith("'s") and len(token) > 2:
            token = token[:-2]

        token = token.strip("'")

        if len(token) < 2 or token in STOPWORDS:
            continue

        tokens.add(token)

    return tokens


def _fuzzy_token_coverage(
    query_tokens: set[str],
    candidate_tokens: set[str],
    min_similarity: float = 0.74,
) -> float:
    """Estimate query coverage while tolerating small word-form differences."""
    if not query_tokens or not candidate_tokens:
        return 0.0

    matched = 0

    for query_token in query_tokens:
        if query_token in candidate_tokens:
            matched += 1
            continue

        if any(
            SequenceMatcher(None, query_token, candidate).ratio() >= min_similarity
            for candidate in candidate_tokens
        ):
            matched += 1

    return matched / len(query_tokens)


def _score_kb_entry(user_input: str, question: str, response: str) -> float:
    """
    Score a KB entry using several lightweight signals.

    This is intentionally local and dependency-free. It is more flexible than
    exact-question matching without requiring an embedding model.
    """
    user_normalized = " ".join(user_input.lower().split())
    question_normalized = " ".join(question.lower().split())

    # A literal question mention is a very strong match.
    if question_normalized and question_normalized in user_normalized:
        return 1.0

    query_tokens = _tokenize(user_input)
    question_tokens = _tokenize(question)
    response_tokens = _tokenize(response)

    if not query_tokens:
        return 0.0

    question_overlap = (
        len(query_tokens & question_tokens) / len(question_tokens)
        if question_tokens
        else 0.0
    )

    query_question_coverage = len(query_tokens & question_tokens) / len(query_tokens)
    query_response_coverage = len(query_tokens & response_tokens) / len(query_tokens)

    fuzzy_question_coverage = _fuzzy_token_coverage(query_tokens, question_tokens)
    fuzzy_response_coverage = _fuzzy_token_coverage(query_tokens, response_tokens)

    question_similarity = SequenceMatcher(
        None, user_normalized, question_normalized
    ).ratio()

    # Several routes can create a valid match:
    # - most of the prayer question is present in the query,
    # - the query strongly overlaps with question terms,
    # - the query strongly overlaps with prayer response,
    # - the query is fuzzy-similar to the question.
    question_score = (0.70 * question_overlap) + (0.30 * query_question_coverage)
    response_score = 0.60 * max(query_response_coverage, fuzzy_response_coverage)
    fuzzy_score = max(
        (0.60 * question_similarity) + (0.40 * question_overlap),
        0.70 * fuzzy_question_coverage,
    )

    return max(question_score, response_score, fuzzy_score)


def find_relevant_prayer(
    user_input: str,
    kb: list[dict[str, str]],
) -> dict[str, str] | None:
    """Return the single best prayer match when it clears the match threshold."""
    best_entry = None
    best_score = 0.0

    for entry in kb:
        score = _score_kb_entry(
            user_input=user_input,
            question=entry["question"],
            response=entry["response"],
        )

        if score > best_score:
            best_entry = entry
            best_score = score

    if best_entry is None or best_score < KB_MATCH_THRESHOLD:
        return None

    return {
        "question": best_entry["question"],
        "response": best_entry["response"],
        "score": f"{best_score:.3f}",
    }


def build_user_prompt(
    user_input: str,
    kb_match: dict[str, str] | None,
) -> str:
    """Add bounded knowledge-base context only when a relevant match exists."""
    if not kb_match:
        return user_input

    kb_text = kb_match["response"][:MAX_KB_CONTEXT_CHARS]

    if len(kb_match["response"]) > MAX_KB_CONTEXT_CHARS:
        kb_text += "..."

    return (
        f"{user_input}\n\n"
        "relevant knowledge-base context:\n"
        f"question: {kb_match['question']}\n"
        f"response: {kb_text}\n\n"
        "use this context only if it is helpful to answer the user's request."
    )


# ---------------- RESPONSE HANDLING ----------------

def enforce_max_sentences(text: str, max_sentences: int) -> str:
    """
    Hard-limit model output to MAX_RESPONSE_SENTENCES.

    This supplements the persona prompt because prompt instructions alone do
    not guarantee the model will obey the sentence count.
    """
    text = " ".join(text.split()).strip()

    if not text or max_sentences <= 0:
        return text

    # Split after ., !, or ? when followed by whitespace.
    sentences = re.split(r"(?<=[.!?])\s+", text)

    if len(sentences) <= max_sentences:
        return text

    return " ".join(sentences[:max_sentences]).strip()


def _extract_chat_content(response: Any) -> str:
    """Read Ollama chat content from object-style or dictionary-style responses."""
    message = getattr(response, "message", None)

    if message is not None:
        content = getattr(message, "content", None)

        if content is None and isinstance(message, dict):
            content = message.get("content")

        if content is not None:
            return str(content).strip()

    if isinstance(response, dict):
        message = response.get("message", {})

        if isinstance(message, dict):
            content = message.get("content")
            if content is not None:
                return str(content).strip()

    raise ValueError("ollama returned a response with no readable message content.")


def query_ollama(
    prompt: str,
    history: list[dict[str, str]],
) -> str | None:
    """Send system prompt + recent conversation history + current request to Ollama."""
    if ollama is None:
        return None

    messages = [
        {"role": "system", "content": PERSONA_PROMPT},
        *history,
        {"role": "user", "content": prompt},
    ]

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=messages,
        )

        content = _extract_chat_content(response)
        return enforce_max_sentences(content, MAX_RESPONSE_SENTENCES)

    except Exception as exc:
        print(f"[ERROR] ollama query failed: {exc}")
        return None


def update_history(
    history: list[dict[str, str]],
    user_input: str,
    bot_response: str,
) -> None:
    """
    Store conversational memory while bounding RAM/context growth.

    Only the user's original message is stored, not the temporary KB-enriched
    prompt, so prayer text is not repeatedly duplicated into conversation history.
    """
    history.extend(
        [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": bot_response},
        ]
    )

    max_messages = MAX_HISTORY_TURNS * 2

    if len(history) > max_messages:
        del history[:-max_messages]


# ---------------- LOGGING ----------------

def log_to_excel(
    user_input: str,
    bot_response: str,
    log_file: Path,
) -> bool:
    """
    Append a conversation row to Excel.

    Logging failures are non-fatal: a permissions problem or damaged workbook
    should not terminate an otherwise functioning chatbot.
    """
    if Workbook is None or load_workbook is None:
        print("[WARNING] excel logging is unavailable because openpyxl is missing.")
        return False

    log_entry = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_input,
        bot_response,
    ]

    try:
        if log_file.exists():
            workbook = load_workbook(log_file)
            worksheet = workbook.active
        else:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.question = "Chat Log"
            worksheet.append(["timestamp", "user_input", "bot_response"])

        worksheet.append(log_entry)
        workbook.save(log_file)
        workbook.close()
        return True

    except Exception as exc:
        print(f"[WARNING] could not write chat log '{log_file}': {exc}")
        return False


# ---------------- MAIN LOOP ----------------

def main() -> int:
    if not check_python_dependencies():
        return 1

    ensure_knowledge_base_file(CSV_KB_PATH)
    kb = load_knowledge_base(CSV_KB_PATH)

    if not check_ollama_ready():
        return 1

    history: list[dict[str, str]] = []

    print("child persona chatbot (type 'exit' to quit)")
    print(f"Model: {MODEL_NAME}")
    print(f"knowledge-base entries: {len(kb)}")
    print(f"conversation memory: last {MAX_HISTORY_TURNS} turns")
    print(f"maximum response length: {MAX_RESPONSE_SENTENCES} sentences\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("peace~!")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            print("peace~!")
            break

        kb_match = find_relevant_prayer(user_input, kb)
        prompt = build_user_prompt(user_input, kb_match)

        bot_response = query_ollama(prompt, history)

        if bot_response is None:
            # Query errors are already displayed by query_ollama().
            # Keep the chatbot alive so a transient Ollama error can recover.
            print()
            continue

        print(f"Bot: {bot_response}\n")

        update_history(history, user_input, bot_response)
        log_to_excel(user_input, bot_response, LOG_FILE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
