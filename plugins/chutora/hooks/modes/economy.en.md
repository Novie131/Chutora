## Current mode: economy (switch with `/chutora mode`)

- Delegate more eagerly: whenever a step would read more than 3 files, look at images, read a long log or produce long command output, hand it to bulk or Explore and keep only the conclusion in the main conversation.
- Hand even small, well-defined changes to worker as a whole; the main conversation only reviews.
- When worker fails, re-dispatch the same agent once with more context; escalate to worker-hard only if it fails again.
- Verify with the relevant tests rather than the full suite every time.
- Noisy-output trimming uses a lower threshold: install, build and test output over 3000 characters or 80 lines is trimmed first; the original's path is at the end of the output, so Read it when you need something that was omitted.
