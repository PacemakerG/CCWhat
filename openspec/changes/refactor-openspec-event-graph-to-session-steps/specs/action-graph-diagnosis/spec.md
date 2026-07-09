## ADDED Requirements

### Requirement: OpenSpec graph source binding

系统 SHALL 为 OpenSpec graph 记录其细图数据来源绑定。

#### Scenario: Dataset task binding
- **WHEN** graph sync receives a dataset id and task id
- **THEN** graph metadata SHALL record `source_kind` as `dataset_task`
- **AND** graph metadata SHALL record the dataset id and task id
- **AND** Event Graph SHALL be built from the Dataset task trace

#### Scenario: Session task binding
- **WHEN** graph sync receives a session id and task id
- **THEN** graph metadata SHALL record `source_kind` as `session_task`
- **AND** Event Graph SHALL be built from normalized session events within that task boundary

#### Scenario: Session full binding
- **WHEN** graph sync receives a session id without a task id
- **THEN** graph metadata SHALL record `source_kind` as `session_full`
- **AND** Event Graph SHALL be built from normalized session events
- **AND** diagnosis SHALL mark confidence lower than task-scoped evidence

#### Scenario: Missing step evidence
- **WHEN** graph sync cannot resolve Dataset or session step evidence
- **THEN** graph metadata SHALL record `source_kind` as `milestone_fallback`
- **AND** diagnosis SHALL include `missing_evidence` explaining that session step evidence is unavailable

### Requirement: Step-level Event Graph for OpenSpec graph

OpenSpec graph sync SHALL use session step evidence as the primary Event Graph source.

#### Scenario: Step events become graph nodes
- **WHEN** normalized session events contain user messages, assistant text, tool calls, tool results, commands, file edits, errors, or final claims
- **THEN** Event Graph SHALL create nodes for those step events
- **AND** each node SHALL preserve event id, event type, timestamp, agent id, turn index, summary, and raw evidence reference when available

#### Scenario: Tool and file details are preserved
- **WHEN** a step event contains tool name, tool call id, command, or file paths
- **THEN** Event Graph node data SHALL preserve those fields for mapping and Viewer inspection

#### Scenario: Milestones are supplemental
- **WHEN** `graph/events.jsonl` contains milestone events and session step evidence is available
- **THEN** milestone events SHALL be stored as supplemental evidence or graph metadata
- **AND** milestone events SHALL NOT replace the step-level Event Graph main nodes

### Requirement: Action mapping reasons

系统 SHALL explain why each Event maps to each OpenSpec Action.

#### Scenario: Mapping reason output
- **WHEN** an Event is mapped to an Action
- **THEN** Action evidence SHALL include the mapped event id
- **AND** Action evidence SHALL include a reason such as `path:proposal`, `path:spec`, `path:design`, `path:tasks`, `command:openspec_validate`, `command:test`, `command:openspec_archive`, `event:file_change`, or `unmapped_turn`

#### Scenario: Unmapped step retention
- **WHEN** a step event cannot be mapped to a fixed OpenSpec Action
- **THEN** Event Graph SHALL retain the event
- **AND** mapping SHALL mark it as unmapped or ad hoc evidence instead of dropping it
