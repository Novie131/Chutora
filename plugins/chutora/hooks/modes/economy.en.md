## Current mode: economy (switch with `/chutora mode`)

- Delegate eagerly: reading over 3 files, images or long output goes to bulk or Explore; even small changes go to worker whole, and you only review.
- When worker fails, re-dispatch once with more context; escalate to worker-hard only if it fails again.
- Verify with the relevant tests only.
- Noisy-output trimming threshold is lower (over 3000 characters or 80 lines).
- Clarify: at most 3 questions at a time.
