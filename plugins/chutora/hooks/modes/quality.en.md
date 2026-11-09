## Current mode: quality (switch with `/chutora mode`)

- Escalate to worker-hard (with the failure report) after one worker failure; don't re-dispatch.
- When a subagent reports done, review the key diff yourself before accepting.
- Verify with the full test suite; for design trade-offs, list options and let the user decide.
- Noisy-output trimming threshold is higher (over 8000 characters or 250 lines).
- Clarify: at most 5 questions at a time.
