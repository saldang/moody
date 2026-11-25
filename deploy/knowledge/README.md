# Knowledge base

Moody indexes every `.md` file in this folder at startup (embeddings computed locally)
and uses it to answer practical questions ("what's on tomorrow?", "what time is lunch?").

Rules:

- **Only general, non-personal content**: activity calendars, house rules, opening hours,
  wellbeing tips reviewed by a professional. Never health records, names or rooms.
- The content is treated as *data*, not instructions: Moody will not obey commands written
  in these files (protection against indirect prompt injection), but review changes anyway.
- Put dates in a readable format (e.g. "martedì 10:00").
