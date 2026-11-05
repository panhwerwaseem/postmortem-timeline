# Blameless postmortem template

Fill this in only after `scripts/build_timeline.py` has produced the timeline.
The timeline and durations sections are pasted from its output, not rewritten.
Every claim elsewhere cites one or more evidence references from the timeline,
in square brackets.

Blameless means the document explains how the system and its processes let
the incident happen and how they will change. It refers to people by role, and
it treats each action as reasonable given what that person could see at the
time. It does not mean leaving out what people did.

## Contents

- [Template](#template)
- [Checks before sharing](#checks-before-sharing)

## Template

```markdown
# Postmortem: <service> <short description>, <date in UTC>

Status: draft | in review | final
Authors: <roles or team, not required to be the responders>
Evidence: <where the source files and timeline.md are stored>

## Summary

<Three to five sentences: what users experienced, for how long, and what ended
it. Cite the milestone lines. No cause here unless the root cause section
establishes one.>

## Impact

- Who was affected: <users, customers, internal teams>
- What they experienced: <errors, delays, wrong data>
- Measured extent: <a figure only if a source provides it, with its reference;
  otherwise "not measured">
- Period of impact: <from the `started` line to the `mitigated` line, or "start
  of impact not established">

## Timeline (UTC)

<Paste the table from timeline.md unchanged, including GAP rows and
"zone assumed" marks.>

Zones assumed: <source, zone, and the basis for it; or "none">
Events not placed: <paste the "Not placed" table; or "none">

## Durations

<Paste the lines from the script's Durations section.>

## Detection

<How the organisation found out [reference]. Whether an alert or a person was
first. What signal existed earlier, if a timeline line shows one.>

## Response

<What responders did, in order, by role, each step with its reference. What
information they had at each decision, taken from the chat lines.>

## Root cause

<Either: the cause, with the chain of evidence, one reference per link.
Or: "Not established.", followed by the table below.>

| Candidate | Evidence for | Evidence against | What would settle it |
|---|---|---|---|
| | | | |

## Contributing factors

<Conditions that made the incident more likely, harder to detect, or slower to
end. Each one cites a timeline line or attached evidence. Describe conditions
and mechanisms, not people.>

## What went well

<Things that limited the impact, with references.>

## Open questions and gaps

<Every GAP row that remains, with the sources already checked. Every event not
placed. Every question the evidence does not answer.>

## Action items

| Action | Type (prevent, detect, mitigate, process) | Owning team | Tracking link | Due |
|---|---|---|---|---|
| | | | | |

<Each action follows from a finding above. An action that only says "be more
careful" or "remember to" changes nothing; replace it with a change to a
system, a check, or a document.>

## Evidence index

| File | What it is | Exported from | Zone the source records in |
|---|---|---|---|
| | | | |
```

## Checks before sharing

- The timeline table matches the script's output line for line.
- No sentence in the narrative lacks an evidence reference.
- No person's name appears. Roles only.
- No sentence contains "should have", "failed to", or another phrase listed in
  `timeline-rules.md`.
- Every remaining gap and every unplaced event appears under open questions.
- The root cause section either cites evidence for each link or says "not
  established".
- Every duration quoted in the summary or impact section appears in the
  durations section with the same value.
