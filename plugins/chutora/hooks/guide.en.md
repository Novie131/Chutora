# chutora: delegation conventions for this session

The main conversation only understands, decides and reviews: implementation goes to `worker`, heavy reading to `bulk`, memory lookups to `librarian`, code search to `Explore`.

- Do small things yourself; never send implementation to general-purpose (it inherits the pricier main model).
- Subagents can't see this conversation: make delegation messages self-contained (goal, paths, constraints, return format).
- A worker/worker-hard/bulk report starts with `狀態：完成｜失敗｜需要決策` and `驗證：通過｜未驗證｜失敗`. Done+passed → spot-check, then adopt; done but not passed, or malformed → treat as failed; needs decision → don't escalate, decide yourself or ask the user.
- Escalate: bulk→worker→worker-hard (with the failure report) → still failing, stop and re-plan or ask the user.
- Done means an executable verification (tests, lint, actually running it).
- Security testing only on targets the user owns or is authorized to test; dynamic testing only in isolated environments, never production.
- Only the main conversation asks (AskUserQuestion), not for small tasks; limit set by the mode; write answers to `claude-memory/briefs/<date>-<slug>.md`, mark acceptance criteria, attach it when delegating.
- Update the handoff on a decision or key fact.
