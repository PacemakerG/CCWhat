## ADDED Requirements

### Requirement: Step-level OpenSpec Event Graph display

Diagnostics page SHALL display OpenSpec Event Graph nodes at session step granularity when step evidence is available.

#### Scenario: Display step-level nodes
- **WHEN** OpenSpec graph payload contains step-level Event Graph nodes
- **THEN** Viewer SHALL render event nodes for tool calls, tool results, commands, file edits, errors, messages, and final claims
- **AND** Viewer SHALL NOT collapse the Event Graph to only artifact or milestone nodes

#### Scenario: Display Action-to-Event binding
- **WHEN** an Action node has mapped `event_ids`
- **THEN** Viewer SHALL make the event count visible on the Action node or adjacent metadata
- **AND** Viewer SHALL provide a way to locate or highlight the mapped Event nodes

#### Scenario: Display fallback warning
- **WHEN** graph metadata says `source_kind` is `milestone_fallback`
- **THEN** Viewer SHALL show a clear warning that the Event Graph is not session step level
