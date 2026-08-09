# Changelog

## 2026-08-09

- Randomized normal test generation so selected questions are no longer pulled in source PDF order.
- Kept the existing fresh-first, due-review, and seen-question scheduling buckets while sampling randomly inside each bucket.
- Added a Math and Reading/Writing rule that targets at least 40% Hard questions in normal tests when Hard questions are available in the selected filters.
- Added fresh top-level topic coverage for Math and Reading/Writing tests so each selected official topic is represented when unexhausted questions are available.
- Preserved difficulty filters: tests that exclude Hard questions stay limited to the selected Easy/Medium difficulties, and Hard-only tests remain all Hard.
- Preserved imported answer choice order for Math and Reading/Writing so displayed A/B/C/D labels match source PDF explanations.
- Allowed in-progress test answers to be changed before finishing and added Back/Next navigation through reached questions.
- Added a live test stopwatch plus completed-test total time and average time per question.
- Moved the in-test stopwatch into the sticky bottom action row so it stays visible while scrolling.
- Updated README documentation to describe the project feature set and the current test-sampling behavior.
