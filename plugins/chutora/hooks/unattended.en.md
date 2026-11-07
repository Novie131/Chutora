# Chutora: nobody is present in this session (scheduled or headless; injected by a hook after checking)

- Nobody can answer right now: don't use AskUserQuestion to wait for a reply, and don't stop to wait for confirmation.
- For a bounded decision, run `python3 "{{HOOKS}}/decide.py" score --type <kind> --options a,b [--claude a=0.7,b=0.3] [--path <paths>] [--remote] --unattended`: if `action` is auto or auto-unattended, do `best` (when it touches files, first `decide.py snapshot --summary "<what>" <paths>`; if that fails, don't) and write down what you picked and why; on skip-todo, don't do it and list it as a to-do at the end of your report.
- Never do anything irreversible or with outside effects; leave it to the user: deleting files outside the project or untracked files that can't be backed up, push, deploy, publish, sending data out, changing permissions or settings.
