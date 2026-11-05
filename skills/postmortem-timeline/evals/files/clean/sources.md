# Evidence bundle: invoice-pdf errors, 21 July 2026

Fictional incident at a fictional company (Quillfeather Logistics), used as a
test fixture. Where each file came from:

- `events.jsonl`: deploy, access-log, monitoring and paging events. Every
  timestamp carries Z or a UTC offset.
- `git-log.txt`: `git log --pretty=format:'%h%x09%cI%x09%s'` on the invoice-pdf
  repository, limited to the day of the incident.
- `incident-channel.json`: export of the #inc-invoice-pdf chat channel. `ts` is
  epoch seconds.
