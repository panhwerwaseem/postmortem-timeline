# Timeline rules

Rules for the lines of an incident timeline and for the text written from it.
`scripts/build_timeline.py` enforces the mechanical ones. The wording rules are
yours to apply.

## Contents

- [What a line contains](#what-a-line-contains)
- [What a timestamp does and does not tell you](#what-a-timestamp-does-and-does-not-tell-you)
- [Marking uncertainty](#marking-uncertainty)
- [Gaps](#gaps)
- [Milestones and durations](#milestones-and-durations)
- [Wording](#wording)
- [Sequence is not cause](#sequence-is-not-cause)

## What a line contains

Every line has four things:

1. **Time in UTC**, as the script printed it.
2. **Source**: the system or channel that recorded it.
3. **What was observed**: what a system did or reported, or what a person said
   or did. One event per line.
4. **Evidence reference**: the file and line (`deploys.csv:4`) or the position
   in a JSON file (`incident-channel.json#/3`).

A line with no evidence reference does not belong in the timeline. If the only
source is a person's memory, record it as an event with a source such as
`recollection`, say in the text that there is no record, and give the time the
precision the person actually has ("about 09:20").

Do not merge several events into one line, and do not drop lines because they
look unrelated. Unrelated-looking lines are how a wrong theory gets caught.

## What a timestamp does and does not tell you

| Source | The timestamp is | It is not |
|---|---|---|
| Alert | When the alert rule fired or the notification was sent | When the problem began. Rules usually wait for a condition to hold for some time before firing |
| Page acknowledgement | When someone pressed acknowledge | When they started working on it |
| Git commit | When the commit was created (author date) or last rewritten, for example by a rebase (committer date) | When it was merged, built, or deployed |
| Deploy record | When the deploy tool started or finished its step | When all instances were serving the new version, unless the tool says so |
| Chat message | When the message was sent | When the thing it describes happened |
| Application log line | When the process wrote the line, by that host's clock | Comparable to the second with another host's clock |

Clocks on different systems can differ. Treat the order of two events from
different sources that are a few seconds apart as unknown.

## Marking uncertainty

The script marks these, and the marks must survive into the postmortem:

- **Zone assumed.** The source had no zone and you supplied one. The time cell
  reads `2026-03-14 09:02:11 (zone assumed: +05:00)`. State the basis for the
  assumption once, near the timeline.
- **Minute precision.** A source that records only hours and minutes is shown
  without seconds (`2026-03-14 09:20`). It sorts as if it happened at second
  zero, so its order against other events in the same minute is unknown.
- **Not placed.** The event has no established UTC time and is listed in its
  own table. Do not move it into the timeline by hand.

Zone abbreviations are refused because several are shared by different
offsets. IST is used for India, Israel and Ireland. CST is used for North
American Central time and for China. Daylight-saving time adds another trap:
a local time without an offset can occur twice on the night clocks go back.

## Gaps

The script inserts a GAP row when no source has an event for longer than
`--gap-minutes` (default 15). When two or more milestones are tagged, a gap
that overlaps the span from the earliest to the latest milestone is marked
"inside the incident window".

A gap means "no record", not "nothing happened". For each gap:

1. Look for a source that covers it: another chat channel or a direct message
   thread, a call recording or its notes, shell history, cloud audit logs,
   dashboards and their annotations, ticket comments.
2. If you find one, add it as an input and rebuild.
3. If you do not, keep the GAP row and list it under open questions with the
   sources you checked.

Never bridge a gap with prose such as "the team continued to investigate".
Raising `--gap-minutes` until the row disappears is the same thing.

## Milestones and durations

Tag at most one evidence line per milestone.

| Tag | Meaning | Typical evidence |
|---|---|---|
| `started` | First recorded sign of the fault or of user impact | First failing request in a log, first breach in a metric export |
| `detected` | The organisation first knew: an alert fired or a person reported it | Alert notification, first support ticket, first chat message |
| `acknowledged` | A responder took ownership | Page acknowledgement |
| `mitigated` | User impact ended, even if the underlying fault remains | Recovery alert, error rate back under the threshold |
| `resolved` | The incident was closed | Incident closed record |

The script prints each duration as a pair, such as "detected to mitigated",
with both evidence references. Use the pairs as printed. Teams define acronyms
such as MTTR differently, so write out the two endpoints.

If `started` rests on an inference, such as "the deploy finished, so impact
began", leave it untagged and say that the start of impact is not established.

## Wording

Write what the record shows, in the past tense, without knowledge of how the
incident ended.

| Instead of | Write |
|---|---|
| "The on-call engineer failed to notice the alert for nine minutes." | "09:10:02 page sent. 09:19:20 page acknowledged." |
| "The deploy should have been rolled back immediately." | "09:04:40 rollout finished. 09:21:30 rollback started." |
| "Unfortunately the dashboard was ignored." | "No record shows the dashboard being opened before 09:15." |
| "Finally, the real problem was found." | "09:15:20 the on-call engineer reported the connection pool at its limit." |
| "A careless config change caused the outage." | "The release lowered the pool size from 40 to 10 (git-log.txt:2)." |

Avoid these in the timeline and the narrative: "should have", "could have",
"failed to", "missed", "neglected", "careless", "obviously", "simply",
"finally", "only", "too late", "human error". Each one judges an action using
information the people involved did not have at the time.

Refer to people by role: "the on-call engineer", "the service owner", "the
incident commander". A name next to a decision reads as blame whatever the
sentence says, and it stops people giving accurate accounts next time.

## Sequence is not cause

"The rollout finished at 09:04:40 and the latency warning fired at 09:06:30"
is a sequence. It becomes a statement of cause only with evidence of the
mechanism, such as:

- a change in the release that explains the symptom (a diff, a config value),
- an error message or metric that names the failing component,
- the symptom ending when the change was reverted,
- a reproduction.

A rollback that ends the symptoms supports "the release contained the
trigger". It does not show which change in the release was responsible, and it
does not explain why the change had that effect.

When the evidence stops short, write "root cause: not established" and list
each candidate with the evidence for it, the evidence against it, and the
record that would settle it.
