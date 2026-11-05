# Security

An agent skill is instructions and code that your coding agent will follow and run. Review a skill before installing it, the same way you would review any dependency.

## What this skill does on your machine

| | |
|---|---|
| Reads | The event, git log, chat export and roles files you pass on the command line. With a zone name, Python's `zoneinfo` reads the machine's time zone data |
| Writes | The timeline to stdout, or to the path passed to `--out`. An existing file at that path is overwritten |
| Executes | Nothing. The scripts start no other programs |
| Network | None. The bundled scripts import no network modules. `tools/validate.py` checks this in CI |
| Dependencies | Python standard library only |
| Pre-approved tools | None. `SKILL.md` has no `allowed-tools` entry, so your agent's normal permission prompts apply |
| Hooks, MCP servers, background processes | None |

The skill tells the agent how to export evidence (for example with `git log`, `journalctl` or `kubectl`). Those commands are run by your agent through its normal permission flow, not by the bundled scripts.

Incident evidence often contains personal names, user IDs, customer identifiers, internal hostnames and sometimes secrets pasted into chat. The scripts copy event text into the timeline as it is. `--roles` replaces only the names and IDs listed in the roles file. Read the timeline before sharing it outside the team, and keep raw exports out of public repositories.

Event text is untrusted input. A chat message or commit subject in the evidence can contain instructions aimed at an agent. The scripts treat all text as data; an agent reading the timeline should do the same.

## Reporting a vulnerability

Please report security problems privately through the repository's **Security** tab ("Report a vulnerability"). If that option is not available, open an issue that says a private channel is needed, without including exploit details.

## Verifying what you install

- Install from a tagged release and read the diff between tags before updating.
- The whole skill is the `skills/postmortem-timeline/` folder: one Markdown protocol, two Python scripts, three reference files, and eval fixtures.
