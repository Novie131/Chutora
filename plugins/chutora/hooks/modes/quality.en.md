## Current mode: quality (switch with `/chutora mode`)

- Delegate as above, but escalate to worker-hard (with the failure report) after a single worker failure instead of re-dispatching the same agent.
- When a subagent reports done, the main conversation reviews the key diff itself before accepting it, not just spot-checks the evidence.
- Verify with the full test suite; when a design trade-off is involved, list the options and let the user decide.
- Noisy-output trimming is more conservative: only output over 8000 characters or 250 lines is trimmed, and more lines are kept at the start and end; the original's path is at the end of the output.
