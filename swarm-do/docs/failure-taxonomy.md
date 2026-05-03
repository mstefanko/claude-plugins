# Failure Taxonomy

Known SwarmDaddy-owned phase-session failure kinds.

| Kind | Category | Retry class | Operator title | Required evidence |
| --- | --- | --- | --- | --- |
| `NON_RETRYABLE_AUTH` | `child_result` | `human_gate` | Sub-agent authentication failed | `child_result, stage_controller` |
| `NON_RETRYABLE_INVALID_INPUT` | `child_result` | `human_gate` | Sub-agent input was invalid | `child_result, stage_controller` |
| `NON_RETRYABLE_UNSUPPORTED_CAPABILITY` | `child_result` | `human_gate` | Sub-agent capability is unsupported | `child_result, stage_controller` |
| `NORMALIZATION_ERROR` | `child_result` | `human_gate` | Sub-agent result normalization failed | `child_result, stage_controller` |
| `PARTIAL_SUCCESS` | `child_result` | `terminal` | Phase partially succeeded | `stage_controller, phase_result` |
| `RETRYABLE_RATE_LIMIT` | `child_result` | `retry` | Sub-agent hit a rate limit | `child_result, stage_controller` |
| `RETRYABLE_TIMEOUT` | `child_result` | `retry` | Sub-agent timed out | `child_result, stage_controller` |
| `RETRYABLE_TRANSIENT_NETWORK` | `child_result` | `retry` | Sub-agent hit a transient network failure | `child_result, stage_controller` |
| `adoptable_artifacts` | `artifact` | `adopt` | Valid artifacts can be adopted | `valid_result_artifact, valid_handoff_artifact` |
| `adoptable_artifacts_uncommittable` | `artifact` | `human_gate` | Adoptable artifacts could not be committed | `valid_result_artifact, worktree_diff, git_commit` |
| `attempt_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `canonical_path_leaked_in_tool_result` | `permission` | `human_gate` | Canonical source path leaked to writer | `transcript_diagnostics, command_metadata, sensitive_path_excerpt` |
| `child_process_dead_no_artifacts` | `lifecycle` | `retry` | Child process ended before artifacts | `child_liveness, launch_dir` |
| `claude_cli_missing` | `environment` | `human_gate` | Claude CLI is unavailable | `command_metadata, launch_dir` |
| `completed_work_units_not_prepared` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `dispatcher_missing_agent_tool` | `permission` | `human_gate` | Fanout dispatcher cannot call Agent | `command_metadata, permission_contract_details` |
| `dispatcher_token_exhausted` | `launcher` | `retry` | Dispatcher exhausted its token budget | `stdout_or_outer_json, stage_controller` |
| `handoff_identity_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `handoff_status_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `launcher_ineligible` | `environment` | `human_gate` | Launcher is ineligible | `launcher_doctor_report` |
| `launcher_nonzero_no_artifacts` | `launcher` | `retry` | Launcher exited before artifacts | `launcher_result, returncode, launch_dir` |
| `launcher_nonzero_with_artifacts` | `launcher` | `adopt` | Launcher exited non-zero after artifacts | `launcher_result, returncode, valid_result_artifact, valid_handoff_artifact` |
| `launcher_prompt_sensitive_path` | `permission` | `human_gate` | Launcher prompt contained a sensitive path | `prompt_safety_check, launch_dir` |
| `launcher_workspace_error` | `environment` | `human_gate` | Launcher workspace preparation failed | `execution_workspace_error, launch_dir` |
| `lease_expired_no_artifacts` | `lifecycle` | `retry` | Lease expired before artifacts | `launch_dir, lease_ttl` |
| `operator_cancelled` | `operator` | `terminal` | Operator cancelled the phase | `operator_action` |
| `operator_requested_retry` | `operator` | `retry` | Operator requested retry | `operator_decision` |
| `outer_artifacts_missing` | `artifact_contract` | `human_gate` | Launcher JSON omitted artifacts | `stdout_or_outer_json, artifact_contract_errors` |
| `outer_json_invalid_no_artifacts` | `launcher` | `human_gate` | Launcher outer JSON was invalid | `stdout_or_outer_json, returncode, launch_dir` |
| `outer_json_missing_no_artifacts` | `launcher` | `retry` | Launcher produced no outer JSON | `stdout_or_outer_json, launch_dir` |
| `partial_artifacts_invalid` | `artifact_contract` | `recovery_retry` | Partial artifacts failed contract validation | `artifact_contract_errors, launch_dir` |
| `path_escape` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `permission_contract_failure` | `permission` | `human_gate` | Permission contract failed | `permission_contract_details` |
| `phase_content_sha_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `prepared_plan_sha_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `result_identity_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `retry_cycle_cap_exceeded` | `child_result` | `human_gate` | Stage retry cycle cap exceeded | `stage_controller, stage_session` |
| `stage_result_missing` | `artifact_contract` | `human_gate` | Stage result was missing after marker | `stage_controller, stage_result_path` |
| `status_mismatch` | `artifact_contract` | `human_gate` | Artifact contract error | `artifact_contract_errors` |
| `structured_retryable_failed` | `child_result` | `child_controlled` | Child result requested retry | `child_result, valid_result_artifact, valid_handoff_artifact` |
| `sub_agent_error` | `child_result` | `retry` | Sub-agent returned an error | `child_result, stage_controller` |
| `writer_silent_with_turns` | `writer_runtime` | `human_gate` | Writer spent turns without artifacts | `stdout_metrics, transcript_diagnostics, launch_dir` |
| `writer_tool_denied_no_artifacts` | `writer_runtime` | `human_gate` | Writer tool denied before artifacts | `transcript_diagnostics, launch_dir` |

Unknown child-reported values are preserved as raw `failure_kind` values and projected as
`failure_category=child_result` with `failure_retry_class=child_controlled`.
