# Five-minute demo

1. Start the stack with `docker compose up --build`.
2. Run all four simulated packages and show the four immutable logs.
3. Ingest the run, repeat ingestion to demonstrate idempotency, and finish the run.
4. Open the dashboard overview and show simulation labels and package completeness.
5. Filter to a failure, open its details, and retrieve the retained raw log.
6. Run the parser against a truncated fixture and show its quarantine diagnostic.
7. Show a synthetic performance comparison: a stable regression is flagged while
   noisy or incompatible measurements remain inconclusive.

AI assistance was used to scaffold and review the implementation. Claims in the
demo should be backed by the checked-in tests and a locally reproduced run; hardware
support must match the machine actually used.

