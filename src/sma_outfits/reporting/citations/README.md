# Academic Validation Citation Pack

This directory stores versioned citation metadata used by the Academic Validation Appendix.

## Files

- `academic_validation.yaml`: citation pack consumed by report generation.
- `author_alignment_rules.yaml`: ground-truth checklist used to score replication alignment.

## Citation Schema

Each citation row must include:

- `id`
- `title`
- `authors`
- `year`
- `venue`
- `type`
- `url`
- `why_it_matters`
- `retrieved_at_utc`

Missing required fields are treated as a hard error in validation/report flows.
