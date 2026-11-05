# Evidence bundle: rate-updates queue backlog, 8 to 9 May 2026

Fictional incident at a fictional company (Quillfeather Logistics), used as a
test fixture. Where each file came from:

- `alerts.csv`: monitoring and paging events. The monitoring tool exports
  local time with its UTC offset.
- `git-log.txt`: `git log --pretty=format:'%h%x09%cI%x09%s'` on the rates-sync
  repository for the 24 hours before the page. There is no deploy record in
  this bundle.
- `incident-channel.json`: export of the #inc-rate-updates chat channel. `ts`
  is epoch seconds.
