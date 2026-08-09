# Changelog

## 2026-08-09

- Randomized normal test generation so selected questions are no longer pulled in source PDF order.
- Kept the existing fresh-first, due-review, and seen-question scheduling buckets while sampling randomly inside each bucket.
- Added a Math and Reading/Writing rule that targets at least 40% Hard questions in normal tests when Hard questions are available in the selected filters.
- Preserved difficulty filters: tests that exclude Hard questions stay limited to the selected Easy/Medium difficulties, and Hard-only tests remain all Hard.
- Updated README documentation to describe the project feature set and the current test-sampling behavior.
