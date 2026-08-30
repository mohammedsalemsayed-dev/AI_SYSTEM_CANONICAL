# Local Builder benchmark

Each model run through `LocalBuilder` (same loop / tools / contracts as the real system) on the seeded bug repos; diff independently verified with pytest.

| model | fixed | tool_valid_rate | bad_arg_rate | confusion_rate | edit_fail_rate | finished_rate | turn_cap_rate | avg_turns | avg_wall_s | avg_tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | 9/10 | 1.0 | 0.0 | 0.0 | 0.0 | 0.9 | 0.1 | 6.9 | 6.8 | 8386 |
| qwen2.5-coder:7b | 6/10 | 0.97 | 0.0 | 0.0 | 0.08 | 0.6 | 0.3 | 11.9 | 16.3 | 21304 |
| llama3.1:8b | 2/10 | 0.99 | 0.06 | 0.0 | 0.13 | 0.2 | 0.6 | 17.2 | 55.9 | 26586 |

## Per-task

| model | task | fixed | turns | calls | bad_args | edit_fail | finished | wall_s |
|---|---|---|---|---|---|---|---|---|
| qwen3:8b | 01-pagination-off-by-one | yes | 5 | 5 | 0 | 0 | yes | 6.6 |
| qwen3:8b | 02-boundary-operator | yes | 5 | 5 | 0 | 0 | yes | 4.4 |
| qwen3:8b | 03-missing-empty-guard | yes | 5 | 5 | 0 | 0 | yes | 5.2 |
| qwen3:8b | 04-int-vs-float-division | yes | 5 | 5 | 0 | 0 | yes | 4.4 |
| qwen3:8b | 05-mutable-default-arg | no | 24 | 24 | 0 | 0 | no | 24.5 |
| qwen3:8b | 06-wrong-dict-key | yes | 5 | 5 | 0 | 0 | yes | 4.4 |
| qwen3:8b | 07-inverted-boolean | yes | 5 | 5 | 0 | 0 | yes | 4.3 |
| qwen3:8b | 08-missing-normalization | yes | 5 | 5 | 0 | 0 | yes | 4.3 |
| qwen3:8b | 09-accumulator-init | yes | 5 | 5 | 0 | 0 | yes | 4.2 |
| qwen3:8b | 10-returns-first-not-all | yes | 5 | 5 | 0 | 0 | yes | 5.6 |
| qwen2.5-coder:7b | 01-pagination-off-by-one | yes | 8 | 8 | 0 | 0 | yes | 26.5 |
| qwen2.5-coder:7b | 02-boundary-operator | yes | 4 | 4 | 0 | 0 | yes | 3.2 |
| qwen2.5-coder:7b | 03-missing-empty-guard | yes | 6 | 6 | 0 | 1 | yes | 5.3 |
| qwen2.5-coder:7b | 04-int-vs-float-division | no | 24 | 24 | 0 | 0 | no | 28.2 |
| qwen2.5-coder:7b | 05-mutable-default-arg | no | 24 | 24 | 0 | 0 | no | 33.7 |
| qwen2.5-coder:7b | 06-wrong-dict-key | yes | 6 | 6 | 0 | 1 | yes | 4.9 |
| qwen2.5-coder:7b | 07-inverted-boolean | no | 7 | 4 | 0 | 0 | no | 7.2 |
| qwen2.5-coder:7b | 08-missing-normalization | yes | 10 | 10 | 0 | 1 | yes | 8.4 |
| qwen2.5-coder:7b | 09-accumulator-init | yes | 6 | 6 | 0 | 1 | yes | 4.5 |
| qwen2.5-coder:7b | 10-returns-first-not-all | no | 24 | 24 | 0 | 0 | no | 40.8 |
| llama3.1:8b | 01-pagination-off-by-one | yes | 7 | 7 | 1 | 0 | yes | 22.3 |
| llama3.1:8b | 02-boundary-operator | no | 24 | 24 | 3 | 2 | no | 30.4 |
| llama3.1:8b | 03-missing-empty-guard | no | 5 | 4 | 0 | 1 | no | 306.8 |
| llama3.1:8b | 04-int-vs-float-division | no | 24 | 23 | 1 | 1 | no | 30.1 |
| llama3.1:8b | 05-mutable-default-arg | no | 24 | 24 | 0 | 0 | no | 56.6 |
| llama3.1:8b | 06-wrong-dict-key | no | 8 | 8 | 5 | 0 | no | 9.4 |
| llama3.1:8b | 07-inverted-boolean | no | 24 | 24 | 0 | 1 | no | 25.8 |
| llama3.1:8b | 08-missing-normalization | yes | 8 | 8 | 0 | 0 | yes | 7.2 |
| llama3.1:8b | 09-accumulator-init | no | 24 | 24 | 0 | 4 | no | 37.2 |
| llama3.1:8b | 10-returns-first-not-all | no | 24 | 24 | 1 | 1 | no | 33.3 |
