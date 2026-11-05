# postmortem-timeline

**An agent skill that builds the incident timeline from alerts, deploys, chat exports and git history before any postmortem narrative is written.**

Left alone, a coding agent asked for a postmortem tends to write the story first and fit the timestamps to it. It reads a deploy log in local time as UTC, fills a 47-minute hole in the records with "the team investigated", and states a root cause because one event came before another. This skill replaces that with a protocol and two scripts: every timestamp is converted to UTC or refused, every timeline line cites the file and line it came from, gaps stay marked, durations are computed, and the narrative is written only from the result.

Works with Claude Code, and with any agent that reads the open [Agent Skills](https://agentskills.io) format (Codex, Cursor, GitHub Copilot, Gemini CLI and others).

## What it looks like

The commands below are run from `skills/postmortem-timeline/evals/files/tz-trap`, a fixture whose deploy history is in local time with no zone.

A source with no zone information blocks the timeline:

```console
$ python3 ../../../scripts/build_timeline.py --events alerts.jsonl --events deploys.csv --git-log git-log.txt --chat incident-channel.json --out timeline.md
wrote timeline.md
- ERROR no-zone: 4 event(s) from source 'deploys' are not placed: no zone or offset in the timestamp. Find out which zone this source records in, then pass --assume-zone deploys=+HH:MM. [deploys.csv:2, deploys.csv:3, deploys.csv:4, deploys.csv:5]
- Result: BLOCKED (1 error(s), 0 warning(s))
```

Checking how single timestamps are read:

```console
$ python3 ../../../scripts/utc_time.py "2026-03-14 14:02:11" "2026-03-14T14:22:05+05:30" "2026-03-14 14:32 IST" 1773479610
2026-03-14 14:02:11  ->  NOT PLACED, no-zone: no zone or offset in the timestamp
2026-03-14T14:22:05+05:30  ->  2026-03-14T08:52:05Z  (offset)
2026-03-14 14:32 IST  ->  NOT PLACED, ambiguous-zone: a zone abbreviation that does not identify one offset (IST)
1773479610  ->  2026-03-14T09:13:30Z  (epoch)
ambiguous-zone: Pass --zone-offset NAME=+HH:MM once the offset is known.
no-zone: Find out which zone the source records in, then pass --assume-zone.
```

Once the bundle's notes show that the deploy tool logs at UTC+05:00, the events are placed and stay marked. With `--roles`, names become roles:

```console
$ python3 ../../../scripts/build_timeline.py --events alerts.jsonl --events deploys.csv --git-log git-log.txt --chat incident-channel.json --assume-zone deploys=+05:00 --roles roles.json --out timeline.md
wrote timeline.md
- WARNING assumed-zone: 4 event(s) from source 'deploys' are placed with a zone you supplied, not one in the data. State the basis for it in the postmortem. [deploys.csv:2, deploys.csv:3, deploys.csv:4, deploys.csv:5]
- Result: OK (0 error(s), 1 warning(s))
$ sed -n '5,13p' timeline.md
| Time (UTC) | Source | Event | Tag | Evidence |
|---|---|---|---|---|
| 2026-03-14 08:52:05 | git | commit 3f9c2ab: Lower label-api DB pool size from 40 to 10 |  | git-log.txt:2 |
| 2026-03-14 09:02:11 (zone assumed: +05:00) | deploys | label-api v2.31.0 rollout to production started |  | deploys.csv:2 |
| 2026-03-14 09:04:40 (zone assumed: +05:00) | deploys | label-api v2.31.0 rollout to production finished |  | deploys.csv:3 |
| 2026-03-14 09:05:00 | git | commit 8d41e07: Update carrier rate table docs |  | git-log.txt:1 |
| 2026-03-14 09:06:30 | monitor | WARN label-api p99 latency above 2s for 1m |  | alerts.jsonl:1 |
| 2026-03-14 09:10:02 | monitor | CRIT label-api HTTP 5xx rate above 5% for 2m; paging primary on-call | detected | alerts.jsonl:2 |
| 2026-03-14 09:12:47 | pager | on-call engineer: Page acknowledged | acknowledged | alerts.jsonl:3 |
```

Read as UTC, the rollout at "14:02" would have landed almost five hours after the first alert. Placed correctly, it finished under two minutes before it.

Gaps in the record become rows in the timeline (run from `evals/files/unexplained-gap`):

```console
$ python3 ../../../scripts/build_timeline.py --events alerts.csv --git-log git-log.txt --chat incident-channel.json | grep GAP
| | | **GAP: no events from any source for 2h 30m 23s** | | git-log.txt:1 to alerts.csv:2 |
| | | **GAP: no events from any source for 47m 08s** (inside the incident window) | | incident-channel.json#/2 to incident-channel.json#/3 |
```

## Install

Pick one route. Installing through more than one gives you the skill twice.

**Claude Code (plugin)**

```
/plugin install postmortem-timeline --marketplace panhwerwaseem/postmortem-timeline
```

On Claude Code versions before 2.1.275, use two steps:

```
/plugin marketplace add panhwerwaseem/postmortem-timeline
/plugin install postmortem-timeline@panhwerwaseem-postmortem-timeline
```

**Any agent (skills CLI)**

```bash
npx skills add panhwerwaseem/postmortem-timeline
```

**Manual**

Copy the `skills/postmortem-timeline` folder into `.claude/skills/` (Claude Code) or `.agents/skills/` (cross-agent) in your project, or into the same folder under your home directory.

To pin a release, add the tag: `/plugin marketplace add panhwerwaseem/postmortem-timeline#v0.1.0` or `npx skills add panhwerwaseem/postmortem-timeline@v0.1.0`. Third-party plugins do not update automatically; run `claude plugin update postmortem-timeline@panhwerwaseem-postmortem-timeline` to update.

## Use

Describe the task and the skill loads on its own:

> Write the postmortem for last night's checkout outage. The alert export, deploy history, git log and the incident channel export are in ./incident.

In Claude Code you can also call it directly with `/postmortem-timeline`.

## What is in the skill

| File | Purpose |
|---|---|
| `SKILL.md` | The protocol: seven hard rules and a nine-step workflow from raw exports to a postmortem written from the timeline |
| `scripts/build_timeline.py` | Merges neutral JSONL or CSV events, `git log` output and chat exports into one UTC-ordered timeline. Reports events it cannot place, marks gaps, checks milestone order, computes durations between tagged milestones, replaces names with roles. Outputs Markdown or JSON |
| `scripts/utc_time.py` | The timestamp reader used by `build_timeline.py`, runnable on its own to see how a timestamp is converted or why it is refused |
| `references/timeline-rules.md` | What a timeline line contains, how uncertainty and gaps are marked, milestone definitions, wording that avoids hindsight and blame, and why sequence is not cause |
| `references/postmortem-template.md` | A blameless postmortem template that takes the script's timeline and durations unchanged |
| `references/exporting-sources.md` | How to export git history, chat, alerts, deploys, logs and Kubernetes events, the input shapes, and a zone checklist |
| `evals/` | Three incident bundles (a time-zone trap, an unexplained gap, a clean one) with eval cases, plus trigger queries |

### How timestamps are handled

- Accepted: an ISO 8601 date and time ending in `Z`, `UTC`, `GMT` or a numeric offset, and epoch numbers in 10-digit seconds or 13-digit milliseconds.
- A zone name such as `Europe/Oslo` is used only if Python's `zoneinfo` can resolve it on the machine. A local time that falls in a repeated or skipped daylight-saving hour is refused.
- A timestamp with no zone, or with an abbreviation such as IST or CST, is never placed by default. You supply the zone with `--assume-zone SOURCE=ZONE` or `--zone-offset NAME=OFFSET`, and the timeline marks those rows.
- Other forms (RFC 2822 dates, syslog dates without a year, epoch microseconds) are reported as unreadable. They are not guessed.

### What the scripts do not do

- They do not fetch anything. You export the evidence; `references/exporting-sources.md` says how.
- They do not detect clock skew between systems or judge whether an assumed zone is right.
- They do not find causes. They order events and show where the record is missing.
- They do not parse raw application logs. Pick the lines that matter and put them in the event shape.

## Requirements

- Python 3.9 or later
- No packages to install and no network access

## What it reads, writes and contacts

- **Reads:** the event, git log, chat and roles files you name on the command line.
- **Writes:** the timeline to stdout, or to the file passed to `--out`. Nothing else.
- **Runs:** no other programs.
- **Contacts:** nothing. The scripts contain no network code; CI enforces this.
- **Permissions:** the skill pre-approves no tools. Your agent asks before running commands, as usual.

See [SECURITY.md](SECURITY.md).

## Testing status

- The scripts have unit tests that run in CI on Python 3.9 and 3.12, together with a validator for the skill format and plugin manifests. The tests run both scripts against every fixture and check the known event order, the planted time-zone trap, the planted gap, and that the clean bundle produces no findings.
- The eval cases in `skills/postmortem-timeline/evals/` are in the [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) format. A with-skill versus without-skill score has not been published yet; results are welcome as an issue or pull request.

## Development

```bash
python3 tools/validate.py              # skill format, manifests, no-network check
python3 -m unittest discover -s tests  # script unit tests
```

## License

[MIT](LICENSE)
