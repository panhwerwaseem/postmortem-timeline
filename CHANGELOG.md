# Changelog

All notable changes to this skill are recorded here. Versions follow [Semantic Versioning](https://semver.org).

## 0.1.0 - 2026-11-06

### Added

- `SKILL.md` with the timeline protocol: hard rules and a nine-step workflow.
- `scripts/build_timeline.py`, which merges events, `git log` output and chat exports into a UTC-ordered timeline with gaps, milestone durations, and Markdown or JSON output.
- `scripts/utc_time.py`, the timestamp reader, usable on its own.
- References for timeline rules, a blameless postmortem template, and exporting each source.
- Three incident bundles (time-zone trap, unexplained gap, clean) with eval cases, and trigger queries.
- Unit tests, a format validator, and a CI workflow.
