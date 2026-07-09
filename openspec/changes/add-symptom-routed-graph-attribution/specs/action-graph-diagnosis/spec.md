## ADDED Requirements

### Requirement: Diagnosis package cleanup

系统 SHALL separate graph construction from attribution scoring and remove stale MVP attribution paths.

#### Scenario: Cleanup stale attribution code
- **WHEN** symptom-routed attribution is implemented
- **THEN** `ccwhat/diagnosis/` SHALL keep only reusable graph models, fixed Action DAG, mapping helpers, and new attribution modules
- **AND** stale milestone-only or single-score MVP attribution paths SHALL NOT remain as the main diagnosis path

### Requirement: Symptom router

系统 SHALL classify user-reported or system-detected problems into explicit symptom routes.

#### Scenario: Route user report
- **WHEN** user reports a problem after a run
- **THEN** diagnosis SHALL produce a symptom route with `type`, `anchor_action_ids`, `query_terms`, `confidence`, and `source`

#### Scenario: Supported symptom types
- **WHEN** diagnosis routes a symptom
- **THEN** symptom type SHALL be one of `workflow_skip`, `validation_failed`, `unsupported_final_claim`, `missing_required_artifact`, `wrong_or_incomplete_output`, `tool_or_command_error_ignored`, `bad_edit_or_regression`, or `insufficient_context`

### Requirement: Action-first reverse attribution

系统 SHALL use the fixed OpenSpec Action DAG as the first attribution layer.

#### Scenario: Reverse walk from anchor action
- **WHEN** a symptom route has anchor Action nodes
- **THEN** attribution SHALL walk upstream through OpenSpec workflow edges
- **AND** attribution SHALL score candidate Actions before scoring Events

#### Scenario: Action scoring reasons
- **WHEN** an Action receives a suspicion score
- **THEN** result SHALL include score reasons such as distance, action status, missing evidence, error evidence, downstream impact, or symptom-specific weight

### Requirement: Event-level suspicious node scoring

系统 SHALL score concrete Event nodes inside suspicious Actions.

#### Scenario: Score mapped Events
- **WHEN** an Action has mapped `event_ids`
- **THEN** attribution SHALL score those Events
- **AND** output SHALL include `event_id`, `action_id`, `score`, `reasons`, and evidence summary

#### Scenario: Symptom-specific Event weights
- **WHEN** symptom type is `validation_failed`
- **THEN** Events representing related edits before the failed command SHALL receive additional suspicion
- **WHEN** symptom type is `unsupported_final_claim`
- **THEN** final claim Events without supporting verify evidence SHALL receive additional suspicion
- **WHEN** symptom type is `tool_or_command_error_ignored`
- **THEN** error result Events followed by continued action or claim SHALL receive additional suspicion

### Requirement: Causal chains include Actions and Events

系统 SHALL output causal chains that connect workflow-level suspicion to concrete step evidence.

#### Scenario: Mixed Action/Event chain
- **WHEN** diagnosis produces a causal chain
- **THEN** chain SHALL include suspicious Action ids
- **AND** chain SHALL include suspicious Event ids when step evidence is available
- **AND** chain SHALL include human-readable evidence reasons

#### Scenario: Missing step evidence downgrade
- **WHEN** Event-level evidence is unavailable
- **THEN** diagnosis SHALL still output Action-level suspicion when possible
- **AND** diagnosis SHALL include `missing_evidence` explaining why Event-level attribution was downgraded
