# ARS Chatbot

A local Python chatbot powered by Ollama, designed to run on a desktop computer or Raspberry Pi.

This project includes two variants:

- **Standard Child Persona** — uses one prayer knowledge base.
- **Child Persona with Dark Mother Influence** — adds a second, gated knowledge base that becomes available only after a conversation threshold and trigger keyword are both satisfied.

Both versions use a warm child-like persona, maintain limited conversation memory, enforce short responses, and support Excel conversation logging.

---

## Kiosk UI bridge (`ars_server.py`)

To connect **`ars_backend.py`** to the Ars HTML front end on a local Pi/desktop:

```bash
cd CTC_Backend
python -m pip install -r requirements.txt
python ars_server.py
```

Then open:

```text
http://127.0.0.1:8765/
```

Endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Ollama + model readiness |
| GET | `/api/loops` | Prayer / leading question / video segments |
| POST | `/api/session` | Create a chat session |
| POST | `/api/chat` | `{ "session_id", "message" }` → Child reply |
| POST | `/api/session/reset` | Clear session history |

Experience content is loaded from `Frontend/Ars/assets/docs/conversational_template.xlsx` (preferred) or `loops.json`. Each row with a leading question becomes one **prayer → conversation** loop (default **5** user turns), then the next prayer/video plays.

The server also serves `Frontend/Ars` as static files, so one process is enough for the kiosk.

CLI-only Child chat (no browser) is still:

```bash
python ars_backend_01.py
```

---

## Project Files

### Standard Child Persona

```text
ars_backend.py
ars_backend_01.py
prayers.csv
chat_log.xlsx
```

### Dark Mother Variant

```text
ars_backend_dm.py
ars_backend_dm_01.py
prayers.csv
dark_mother.csv
chat_log.xlsx
```

The CSV and Excel files are stored relative to the Python script, so the program does not depend on the terminal's current working directory.

If a required knowledge-base CSV is missing, the script creates an empty template with the correct headers.

---

## Requirements

Python 3.10+ is recommended.

Install the Python dependencies:

```bash
pip install ollama
pip install openpyxl
```

Ollama must also be installed and running locally.

The scripts default to:

```python
MODEL_NAME = "llama3"
```

Pull the model before running the chatbot:

```bash
ollama pull llama3
```

Check installed models with:

```bash
ollama list
```

---

# 1. Standard Child Persona

Run:

```bash
python ars_backend.py
```

The standard version uses:

```text
prayers.csv
```

as its only knowledge base.

The model is instructed to speak in simple, warm, encouraging language and to use knowledge-base context when a relevant prayer is found.

### Main Features

- Local Ollama inference
- Child persona system prompt
- Prayer knowledge-base retrieval
- Exact, lexical, and fuzzy matching
- Bounded conversation memory
- Enforced response-length limit
- Excel conversation logging
- Automatic CSV template creation
- Ollama and model startup checks
- Graceful handling of malformed or incomplete CSV rows

---

## Standard Knowledge Base

`prayers.csv` must use:

```csv
question,response
```

Example:

```csv
question,response
Our Father,"Our Father, who art in heaven..."
Hail Mary,"Hail Mary, full of grace..."
Prayer for Courage,"May I meet what comes with courage, patience, and love."
Prayer for Forgiveness,"Help me forgive others and ask forgiveness when I have caused harm."
```

Header capitalization is handled case-insensitively, so this is also valid:

```csv
Question,Response
```

Rows missing either a title or text are skipped.

---

## Standard Retrieval

The chatbot uses lightweight local matching rather than embeddings or a vector database.

Matching considers:

- Exact title matches
- Keyword overlap
- Query/title overlap
- Query/text overlap
- Fuzzy string similarity

The default relevance threshold is:

```python
KB_MATCH_THRESHOLD = 0.45
```

Lowering this value makes retrieval more permissive. Raising it makes matching more selective.

---

# 2. Child Persona with Dark Mother Influence

Run:

```bash
python ars_backend_dm.py
```

This version uses two knowledge bases:

```text
prayers.csv
dark_mother.csv
```

The normal prayer KB remains available throughout the conversation.

The `dark_mother` KB is protected by a counter and keyword condition.

---

## Dark Mother Activation

The Dark Mother knowledge base becomes eligible only when **both** conditions are true:

1. At least two successful user-to-bot interactions have already completed.
2. The current user message contains one of the configured trigger keywords.

Default configuration:

```python
DARK_MOTHER_MIN_INTERACTIONS = 2

DARK_MOTHER_TRIGGER_KEYWORDS = {
    "death",
    "birth",
    "rebirth",
    "precipice",
}
```

Conceptually:

```python
counter_condition = interaction_count >= DARK_MOTHER_MIN_INTERACTIONS
keyword_condition = bool(trigger_keywords_found)

dark_mother_active = counter_condition and keyword_condition
```

Only successful exchanges increment the counter.

Blank messages, `exit`, `quit`, and failed Ollama calls do not count as completed interactions.

---

## Example Activation Sequence

```text
Interaction 1
User: What does death mean?
Result: Dark Mother is still locked.

Interaction 2
User: Tell me about rebirth.
Result: Dark Mother is still locked.

Interaction 3
User: What happens at the precipice?
Result: dark_mother activates.

Interaction 4
User: Tell me a prayer.
Result: normal prayer routing.

Interaction 5
User: What is birth?
Result: dark_mother activates.
```

Trigger matching uses word boundaries.

For example:

```text
birth
```

matches the `birth` trigger, while:

```text
birthday
```

does not.

---

## Dark Mother Knowledge Base

`dark_mother.csv` uses the same schema:

```csv
title,text
```

Example:

```csv
title,text
Death,"Death may be approached as a threshold, ending, transformation, or return."
Birth,"Birth represents emergence, beginning, embodiment, and arrival."
Rebirth,"Rebirth represents transformation after an ending and the emergence of something changed."
Precipice,"The precipice represents the threshold between what is known and what has not yet been entered."
```

The CSV content determines the information passed to the model when this route is activated.

The trigger keywords only control access to the KB. They do not themselves define the response.

---

## Dark Mother Routing Priority

For each user turn, routing works in this order:

```text
User message
    |
    v
Counter >= 2 AND trigger keyword found?
    |
    +---- Yes ---> dark_mother KB
    |
    +---- No ----> prayer KB
                       |
                       +---- relevant match ---> prayer context
                       |
                       +---- no match ---------> no KB context
```

When the Dark Mother gate activates, it takes priority over the prayer KB for that turn.

If the Dark Mother gate activates but `dark_mother.csv` contains no usable entries, the program reports a warning instead of silently substituting the prayer KB.

The special route is evaluated separately on every message. Activating it once does **not** permanently switch the chatbot into a Dark Mother mode.

---

# Shared Configuration

Both versions use similar configuration values.

```python
MODEL_NAME = "llama3"

MAX_RESPONSE_SENTENCES = 3
MAX_HISTORY_TURNS = 6
MAX_KB_CONTEXT_CHARS = 3000
KB_MATCH_THRESHOLD = 0.45
```

---

## Response Length

The model is instructed to answer briefly, but the limit is also enforced programmatically.

Default:

```python
MAX_RESPONSE_SENTENCES = 3
```

If the model returns:

```text
One. Two. Three. Four. Five.
```

the chatbot outputs:

```text
One. Two. Three.
```

Change the limit as needed:

```python
MAX_RESPONSE_SENTENCES = 5
```

---

## Conversation Memory

The chatbot retains a limited number of previous exchanges.

Default:

```python
MAX_HISTORY_TURNS = 6
```

Older turns are removed automatically.

The script stores the user's original message in history rather than the temporary KB-enriched prompt, which prevents large KB passages from being repeatedly copied into future model context.

---

## KB Context Limit

Knowledge-base text added to an Ollama prompt is limited by:

```python
MAX_KB_CONTEXT_CHARS = 3000
```

This keeps large CSV entries from consuming excessive context on a local model.

---

# Excel Logging

Both versions write conversation logs to:

```text
chat_log.xlsx
```

### Standard Version

The standard log contains:

```text
timestamp
user_input
bot_response
```

### Dark Mother Version

The Dark Mother version additionally records routing information:

```text
timestamp
interaction_count
user_input
bot_response
kb_route
activation_keywords
```

Possible routes include:

```text
none
prayers
dark_mother
dark_mother_empty
```

This makes the conditional routing behavior auditable during testing.

Routing metadata is not presented as part of the chatbot's normal response.

---

# Changing the Ollama Model

Replace:

```python
MODEL_NAME = "llama3"
```

with another locally installed model.

Example:

```python
MODEL_NAME = "gemma3"
```

Then install it:

```bash
ollama pull gemma3
```

The chatbot checks that Ollama is reachable and that the configured model is installed before beginning the main conversation loop.

---

# Recommended Raspberry Pi Setup

Create a project directory:

```bash
mkdir child-persona
cd child-persona
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install ollama openpyxl
```

Pull the model:

```bash
ollama pull llama3
```

Then run either version.

Standard:

```bash
python3 ars_backend.py
```

Dark Mother:

```bash
python3 ars_backend_dark_mother.py
```

Actual model speed and memory use depend on the Ollama model and quantization selected.

---

# Troubleshooting

## Missing `ollama` Python package

```bash
python3 -m pip install ollama
```

## Missing `openpyxl`

```bash
python3 -m pip install openpyxl
```

## Ollama cannot be reached

Check:

```bash
ollama list
```

If that command fails, make sure Ollama is installed and its local service is running.

## Model is missing

```bash
ollama pull llama3
```

## Knowledge base is empty

Make sure the CSV contains:

```csv
title,text
```

and at least one complete row.

## Prayer retrieval is too strict

Lower:

```python
KB_MATCH_THRESHOLD = 0.45
```

For example:

```python
KB_MATCH_THRESHOLD = 0.40
```

## Dark Mother does not activate

Confirm that:

- Two successful exchanges have already completed.
- The current message contains a configured trigger word.
- `dark_mother.csv` contains usable rows.
- The trigger appears as a standalone word.

---

# Choosing a Version

Use **`ars_backend.py`** if you want:

- One stable child persona
- One prayer-oriented knowledge base
- Simpler retrieval and routing
- A clean baseline for testing

Use **`ars_backend_dark_mother.py`** if you want:

- The same baseline child persona
- A second thematic knowledge source
- Counter-based gating
- Keyword-based activation
- Conditional context influence
- Route-aware debugging logs

---

# Design Notes

These scripts are local prototypes.

Important considerations:

- CSV content is inserted into model prompts.
- Anyone able to edit a KB file can influence model behavior.
- Excel logs contain conversation content.
- Keyword gating is application logic, not a security boundary.
- A language model can still produce unexpected responses despite the persona prompt.
- Response-length enforcement limits sentence count, not factual accuracy.
- The retrieval system is lightweight lexical/fuzzy retrieval, not vector search.
- The Dark Mother influence is turn-specific rather than a permanent persona transition.

---

# Architecture

Standard:

```text
User input
    |
    v
Prayer KB retrieval
    |
    v
Prompt construction
    |
    v
Ollama
    |
    v
Sentence limit
    |
    v
Conversation memory
    |
    v
Excel log
```

Dark Mother:

```text
User input
    |
    v
Interaction counter + keyword condition
    |
    +---- true ----> Dark Mother KB
    |
    +---- false ---> Prayer KB / no KB
                          |
                          v
                        Ollama
                          |
                          v
                    Sentence limit
                          |
                          v
                 Conversation memory
                          |
                          v
                      Excel log
```

---

# License

No license has been assigned.

If the project will be distributed publicly, add a `LICENSE` file with terms appropriate for the project.
