# English content policy and labeling rubric

Version 1.0, accepted policy recorded from the user's explicit instructions. Classify the sending mechanism and text origin separately.

| Example history | Agent-send ground truth | In-scope content ground truth |
| --- | --- | --- |
| Person writes and sends an original message | Negative | Negative |
| Person pastes a ChatGPT/Claude/Copilot draft and clicks Send | Negative | Positive |
| Claude executes Send after the person approves | Positive | Determine separately from text creation history |
| Agent sends an existing human template | Positive | Negative when original human history is established |
| Assistant fixes only spelling, punctuation or basic grammar | Based on who sends | Basic-correction control; no targeted content positive solely for this help |
| Assistant restructures an argument, adds reasoning or rewrites most wording | Based on who sends | Positive substantial rewrite |
| Assistant translates text into English | Based on who sends | Positive |
| A person forwards a quoted AI paragraph | Based on who sends | Flag inherited region where supported, without attributing generation to the forwarder |

Illustrative rubric pair (authored contract examples, not independent evaluation labels):

- Original: “Please send teh agenda before tomorow meeting.”
- Basic correction: “Please send the agenda before tomorrow's meeting.” The same request and information remain.
- Substantial rewrite: “Please circulate the agenda by this afternoon so attendees can prepare decisions and identify outstanding dependencies.” New timing, rationale and requested preparation are introduced.

Two independent reviewers later examine creation history and original/output pairs, recording disagreement and adjudication. A final-text detector cannot establish the editing operation reliably. Ambiguous cases remain uncertain and do not enter definitive test labels. AI paraphrases of human material are not labeled genuine human originals.

Separate authored text, inherited quotes, signatures and boilerplate. Do not interpret a score as an AI-word percentage or infer provider/model from style. English is the first supported language; unsupported or unestablished language is unknown. The initial statistical eligibility hypothesis is 100 authored English words, with 1–49, 50–99, 100–199 and 200+ bins reported independently. Short positives stay in all-length recall.

The evidence spike verifies only supported provenance contracts and returns explicit unknown for untracked content. Actual pretrained statistical scoring is the bounded later content experiment described in `content-feasibility.md`; its absence in this feasibility tool is not represented as a completed content detector.
