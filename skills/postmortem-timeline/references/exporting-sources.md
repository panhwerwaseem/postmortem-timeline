# Exporting each source

How to get each kind of evidence into a file that `scripts/build_timeline.py`
reads, and what to check about its time zone. Tool options and export formats
change between versions. Where a detail matters, confirm it in the tool's
`--help` or official documentation.

Two rules apply to every source:

- **Keep the original export.** If you reshape a file, keep the raw one next to
  it. The reshaped file is what the timeline cites; the raw file is what proves
  it.
- **Copy timestamps exactly.** Do not convert to UTC, round, or append a zone
  while reshaping. Zone questions are settled with `--assume-zone` and
  `--zone-offset`, where the script records that an assumption was made.

## Contents

- [The neutral event shape](#the-neutral-event-shape)
- [Git history](#git-history)
- [Chat](#chat)
- [Alerts and pages](#alerts-and-pages)
- [Deploys and CI](#deploys-and-ci)
- [Logs](#logs)
- [Kubernetes events](#kubernetes-events)
- [What people remember](#what-people-remember)
- [Zone checklist](#zone-checklist)

## The neutral event shape

Anything without its own loader goes into this shape. Pass it with `--events`.

JSONL, one object per line:

```json
{"timestamp": "2026-03-14T09:10:02Z", "source": "monitor", "text": "CRIT label-api 5xx rate above 5%", "tag": "detected"}
{"timestamp": "2026-03-14T09:12:47Z", "source": "pager", "text": "Page acknowledged", "actor": "U07RHL4QX"}
```

Or CSV, with a header row and a file name ending in `.csv`:

```csv
timestamp,source,text,tag,actor
2026-03-14 14:02:11,deploys,label-api v2.31.0 rollout started,,
```

| Field | Required | Meaning |
|---|---|---|
| `timestamp` | yes | Exactly as the source wrote it. See "Accepted timestamps" below |
| `source` | yes | Short name of the system. `--assume-zone` is applied per source, so give systems that record in different zones different names |
| `text` | yes | What the record says |
| `tag` | no | A milestone: `started`, `detected`, `acknowledged`, `mitigated`, `resolved` |
| `actor` | no | The person or bot the record names. Replaced by a role when `--roles` is given |

Accepted timestamps:

- ISO 8601 date and time, with `T` or a space between them, ending in `Z`,
  `UTC`, `GMT`, or a numeric offset (`+05:30`, `+0530`, `+05`). Seconds and a
  fraction are optional.
- An epoch number: 10-digit seconds or 13-digit milliseconds.
- The same date and time followed by a zone name such as `Europe/Oslo`, when
  the machine has time zone data for it.

Not accepted, and reported as `bad-timestamp`: a date with no time, a time with
no date, RFC 2822 dates (`Sat, 14 Mar 2026 09:12:05 +0500`), forms such as
`UTC+5`, and epoch values in microseconds or nanoseconds.

## Git history

```bash
git log --since='2026-03-13' --until='2026-03-15' \
    --pretty=format:'%h%x09%cI%x09%s' > git-log.txt
```

`%h` is the abbreviated hash, `%x09` a tab, `%cI` the committer date in strict
ISO 8601 with its offset, `%s` the subject. Pass the file with `--git-log`, or
`--git-log NAME=git-log.txt` to label it with the repository name.

- Use `%aI` in place of `%cI` for the author date. The author date is when the
  change was first written. The committer date is reset when a commit is
  rebased, amended, or cherry-picked, so it can be later than the author date.
- Add `--first-parent` on the main branch to follow only that branch's own
  line: its merge commits and the commits made directly on it.
- `--since` and `--until` filter on the committer date.
- The format leaves out the author's name on purpose. The timeline needs what
  changed and when.
- A commit time is not a deploy time. Pair the git log with a deploy record.

## Chat

`--chat` reads a JSON array of message objects, or an object with a `messages`
array. For each message it reads:

| Purpose | Keys tried, in order |
|---|---|
| Time | `ts`, then `timestamp`. An epoch number, or any accepted timestamp string |
| Text | `text`, then `content` |
| Actor | `user_name`, `username`, `user`, `author` (string values only) |
| Milestone | `tag`, if you add one |

**Slack.** A workspace export is a zip with one folder per channel and one JSON
file per day in each folder. Each day file is an array of messages, and each
message has `ts` (epoch seconds as a string, with a six-digit suffix that makes
it unique in the channel), `user` (a user ID) and `text`. Pass a day file as it
is. The export's `users.json` maps user IDs to names; use it to build the
`--roles` file. Mentions appear in message text as `<@U…>` and are replaced
when the ID is in the roles file. Exporting needs workspace owner or admin
rights, and what an export may contain depends on the plan and the workspace's
settings. Check Slack's help centre for the current rules.

**Other chat tools.** Export to JSON if the tool can, then check which key
holds the time and whether it is an epoch number or a string with an offset.
If the export is text or HTML, reshape the messages into the neutral event
shape and keep the original.

Thread replies are separate messages with their own timestamps. An edited
message can keep its original timestamp, so the text you see may be newer than
its time. If that matters for a line, say so.

## Alerts and pages

Export the alert history and the paging history for the incident window, with
some margin either side. You want at least: when each alert fired, when it
recovered, when each page was sent, acknowledged, and resolved.

- **Prometheus Alertmanager.** Each alert in a webhook payload or in the API
  has `startsAt` and `endsAt` timestamps in RFC 3339 form, plus `status`,
  `labels` and `annotations`. Map `startsAt` to one event and, for resolved
  alerts, `endsAt` to another.
- **Paging tools.** Export the incident's log or timeline entries (triggered,
  acknowledged, escalated, resolved). Check whether the export is in UTC or in
  the account's or the viewer's time zone. API responses usually carry an
  offset; CSV reports and copied web pages often do not.
- **Alert rule delay.** An alert fires after its condition has held for the
  rule's configured duration. The alert time is the detection time, not the
  start of the problem. Record the rule's duration in the event text if you
  know it.

## Deploys and CI

Export the deploy or pipeline history for the affected services: one event
when a rollout started, one when it finished, the same for rollbacks, and the
version or commit each one shipped.

- Prefer the tool's API or CLI output over a copied web page. Web pages
  usually show the viewer's local time with no zone.
- For GitHub deployments, `gh api repos/OWNER/REPO/deployments` returns one
  object per deployment with `sha`, `environment` and `created_at`.
- If the only record is a web page or a log in local time, save it as it is,
  find out which zone it shows, and pass that with `--assume-zone`.

## Logs

- **journald.** `journalctl -u SERVICE --since "..." --until "..." -o short-iso`
  prints an ISO 8601 timestamp with an offset on every line. Add `--utc` to
  print in UTC. `-o json` gives `__REALTIME_TIMESTAMP` in microseconds since
  the epoch, which the script does not accept; use `short-iso`.
- **Classic syslog lines** (`Mar 14 09:12:05 host app: ...`) carry no year and
  no zone. Find the host's configured zone and rewrite the timestamps in ISO
  form without a zone, then use `--assume-zone`.
- **Application logs.** Check the logging configuration. Many frameworks write
  local time with no zone by default. Python's `logging` module does: its
  default `%(asctime)s` looks like `2026-03-14 09:12:05,123`.
- Do not load whole logs. Pick the lines that mark a change of state (first
  error, restart, recovery) and reshape those into the neutral event shape,
  with the original file name and line number in the text.

## Kubernetes events

`kubectl get events -A -o json` returns events with `firstTimestamp`,
`lastTimestamp` and `eventTime` fields, in UTC. Which of them is filled in
depends on the component that reported the event, so check before mapping. By
default the API server keeps events for one hour (`--event-ttl`), and managed
clusters may use a different value, so export them during or right after the
incident. If they are already gone, check whether the cluster ships events to
a logging system.

## What people remember

A recollection is a source too, and often the only one for a phone call or a
decision. Record it in an events file:

```json
{"timestamp": "2026-03-14T09:20Z", "source": "recollection", "text": "On-call engineer recalls phoning the database team about connection limits. No record. Time is approximate."}
```

Give it only the precision the person has. Ask what they can anchor the time
to ("just after the second page") and prefer the anchored record.

## Zone checklist

For each file, before building:

1. Does every timestamp end in `Z` or an offset? Then nothing more is needed.
2. Is it an epoch number? Then it is UTC by definition.
3. Otherwise, where does the zone come from? Look for a time zone setting in
   the tool, the `TZ` variable or system zone of the host that wrote the file,
   and the profile setting of the person who exported it.
4. Does that zone observe daylight-saving time? If so, the offset depends on
   the date. Use the offset that applied on the day of the incident, or pass a
   zone name to `--assume-zone` so the script looks it up.
5. Write the answer in the postmortem's evidence index.
