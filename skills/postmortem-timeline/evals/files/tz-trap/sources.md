# Evidence bundle: label-api errors, 14 March 2026

Fictional incident at a fictional company (Quillfeather Logistics), used as a
test fixture. Where each file came from:

- `alerts.jsonl`: monitoring and paging events, exported in UTC.
- `deploys.csv`: copied from the history page of the Shipwright deploy tool.
  Shipwright runs on the build host in the Karachi office. The host clock is
  set to UTC+05:00 and the history page prints local time without a zone.
- `git-log.txt`: `git log --pretty=format:'%h%x09%cI%x09%s'` on the label-api
  repository, limited to the day of the incident.
- `incident-channel.json`: export of the #inc-label-api chat channel. `ts` is
  epoch seconds.
- `roles.json`: maps the people in the chat export to their roles.
