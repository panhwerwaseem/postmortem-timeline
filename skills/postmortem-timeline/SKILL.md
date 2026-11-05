---
name: postmortem-timeline
description: Builds an incident timeline in UTC from alerts, deploy records, chat exports and git history before any postmortem narrative is written, with every line citing its evidence, unknown time zones and gaps marked, and milestone durations computed by a script. Use when writing a postmortem, incident review, post-incident report or RCA document, when the user asks what happened when, wants an outage reconstructed, asks for time to detect or time to resolve, or hands over alert exports, Slack or chat exports, deploy logs or git log output from an incident.
license: MIT
compatibility: Requires Python 3.9 or later to run the bundled scripts. No network access and no extra packages needed.
metadata:
  author: panhwerwaseem
  version: "0.1.0"
---

# Postmortem timeline

A postmortem is ready to write only when `scripts/build_timeline.py` has merged
every available source into one UTC-ordered timeline, each line points at the
file and line it came from, every event with an unknown time zone is either
resolved with a stated basis or listed as not placed, and every gap is still
visible. The narrative, the durations and any statement of cause are then
written from that timeline and from nothing else.

Paths in this file are relative to this skill's directory.

## Hard rules

1. **Timeline before narrative.** Do not write a summary, a cause, or
   contributing factors until `scripts/build_timeline.py` has run on all the
   sources you have. If it still reports errors, list them in the report as
   unresolved. Do not write around them.
2. **Every line cites its source.** Each timeline row keeps the evidence
   reference the script printed (`alerts.jsonl:2`, `chat.json#/14`). Do not add
   a row from memory or from the conversation. Something a person recalls goes
   into an events file with a source such as `recollection`, and its text says
   it has no record.
3. **Never guess a time zone.** An event listed under "Not placed" stays out of
   the timeline until you have evidence of the zone (the tool's settings, a
   host's clock configuration, the user's statement). Then pass
   `--assume-zone` or `--zone-offset`, keep the "zone assumed" mark, and state
   the basis. Do not convert times by hand.
4. **Never fill or smooth over a gap.** Keep every GAP row. Do not write "the
   team investigated" or anything else for a period with no records. Look for
   another source. If there is none, the postmortem says the period is unknown.
5. **Roles, not names.** No person's name appears next to a decision, an action
   or a delay. Use `--roles` so the timeline shows roles, and write the
   narrative the same way. No "failed to", "should have", or "missed".
6. **No cause beyond the evidence.** State a root cause only when timeline
   lines or attached evidence support each link, and cite them. Sequence alone
   is not cause. Otherwise write "not established", list the candidates, and
   say what evidence would confirm or rule out each.
7. **Durations come from the script.** Report only the durations it printed,
   as "from X to Y". Do not compute one by hand, and do not report one whose
   milestone has no tagged evidence line.

## Workflow

### 1. Collect the raw sources

Ask for, or export, every record that carries a timestamp: alerts and pages,
deploy and CI history, chat from the incident channel, git history of the
affected services, relevant logs. `references/exporting-sources.md` gives the
export method for each and the zone each one records in. Note for each file
where it came from; you will need that to settle zone questions.

### 2. Put each source in a shape the script reads

- Git history: `git log --pretty=format:'%h%x09%cI%x09%s'`, saved to a file.
- Chat: a JSON array of messages with an epoch `ts` and `text` (a Slack
  channel export file works as it is).
- Everything else: JSONL or CSV with `timestamp`, `source`, `text`, and
  optionally `tag` and `actor`. Copy timestamps exactly as the source wrote
  them. Do not convert, round, or add a zone while reshaping.

### 3. Build

```bash
python3 scripts/build_timeline.py --events alerts.jsonl --events deploys.csv \
    --git-log git-log.txt --chat incident-channel.json
```

Exit code 1 means a blocking finding. Read the "Not placed" table and the
"Findings" list before reading the timeline.

### 4. Resolve blocking findings with evidence

| Finding | What it means | What to do |
|---|---|---|
| `no-zone` | Timestamps carry no zone or offset | Find the zone the source records in, then `--assume-zone SOURCE=+HH:MM` |
| `ambiguous-zone` | Abbreviation such as IST, CST, BST | Find which offset was meant, then `--zone-offset IST=+05:30` |
| `unresolved-zone`, `dst-transition` | Zone name with no usable zone data, or a repeated or skipped local hour | Get the offset from the source, then `--zone-offset NAME=+HH:MM` or rewrite with an offset |
| `bad-timestamp` | Missing or unreadable time | Re-export in ISO 8601, or leave the event not placed and say so |
| `duplicate-milestone`, `milestone-order` | A tag is on two events, or milestones run backwards | Fix the tags. If the tags are right, a source has the wrong zone |

To see how one timestamp is read, run `python3 scripts/utc_time.py "<timestamp>"`.
If the zone cannot be established, ask the user. If nobody knows, leave the
events not placed and report that.

### 5. Tag the milestones

Tag at most one evidence line for each of `started`, `detected`,
`acknowledged`, `mitigated`, `resolved`. `references/timeline-rules.md` defines
each. Leave a milestone untagged when no line supports it.

```bash
python3 scripts/build_timeline.py <same inputs> \
    --tag detected=alerts.jsonl:2 --tag resolved=alerts.jsonl:5
```

### 6. Review the gaps

For each GAP row, especially one marked "inside the incident window", ask what
source could cover it (another channel, a call recording, shell history, audit
logs, dashboards) and add it. A gap that remains stays in the timeline and goes
into the postmortem's open questions.

### 7. Produce the final timeline

```bash
python3 scripts/build_timeline.py <same inputs and flags> --roles roles.json --out timeline.md
```

`roles.json` maps each name and user ID in the sources to a role, for example
`{"U07RHL4QX": "on-call engineer"}`. A `no-role` warning means a name is still
showing.

### 8. Write the postmortem from the timeline

Use `references/postmortem-template.md`. Paste the timeline table and the
durations unchanged. Follow `references/timeline-rules.md` for wording. Each
claim in the narrative cites one or more evidence references.

### 9. Report

```
Sources:        <files, with the number of events from each>
Timeline:       <placed>/<total> events placed, written to <path>
Zones assumed:  <source = zone, and the basis for each; or "none">
Not placed:     <events left out and why; or "none">
Gaps:           <each gap with its length and the two evidence references; or "none">
Durations:      <as printed by the script>
Root cause:     <stated with evidence references, or "not established" with candidates>
Open questions: <what is unknown and which source would answer it>
```

## Edge cases

- **Exit code 0 with warnings.** Gaps and assumed zones do not block. They
  still must appear in the timeline and the report.
- **A source is in a format the script does not read** (syslog lines without a
  year, RFC 2822 dates, epoch microseconds). Re-export it in ISO 8601 with an
  offset where the tool allows. Otherwise reshape it and keep the original file
  as the evidence.
- **Commit time is not deploy time.** A git row says when a commit was made.
  Only a deploy record shows when it reached production.
- **A chat message reports an action after the fact.** "Rolled back" at 09:27
  means the rollback happened at or before 09:27. Prefer the tool's own record
  for the action time.
- **The user states a cause up front.** Treat it as a candidate. Check it
  against the timeline like any other and apply rule 6.
- **The times look wrong after a zone was assumed** (a rollback before its
  alert, a `milestone-order` error, a new multi-hour gap). Recheck the zone
  before anything else.
- **Events from different sources within a few seconds of each other.** Clocks
  differ between systems. Do not build an argument on their order.
