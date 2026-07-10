## ADDED Requirements

### Requirement: Claude Session-only MVP source

系统 SHALL use one Claude Code raw Session as the only execution evidence source for one OpenSpec change in the MVP.

#### Scenario: Build graphs from one Session
- **WHEN** the user selects a Claude Session and an OpenSpec change
- **THEN** the system SHALL build the Action Graph and Event Graph from that Session
- **AND** the diagnosis path SHALL NOT require Runtime Task, Dataset, or `task.diff`

### Requirement: Minimal fixed Action Graph

系统 SHALL retain the fixed OpenSpec seven-Action graph as a workflow-stage index.

#### Scenario: Action status from observed evidence
- **WHEN** Session Events map to an Action
- **THEN** that Action SHALL have status `observed` unless explicit failure evidence makes it `failed`
- **AND** an Action without mapped Events SHALL have status `not_observed`
- **AND** lack of evidence alone SHALL NOT produce status `skipped`

#### Scenario: Workflow edges are not attribution scores
- **WHEN** user feedback diagnosis runs
- **THEN** fixed workflow edges SHALL NOT automatically propagate suspicion upstream
- **AND** the result SHALL NOT expose the previous generic `0..100` Action suspicion score as root-cause confidence

### Requirement: Evidence-complete Event Graph

系统 SHALL preserve the Session evidence required to inspect concrete Tool and Event steps.

#### Scenario: Unique Event nodes
- **WHEN** one raw log entry contains multiple content blocks or Tool Uses
- **THEN** every emitted graph node SHALL have a unique Event ID

#### Scenario: Preserve Tool evidence
- **WHEN** normalized Events contain Tool Calls, Tool Results, file operations, commands, errors, timestamps, agent identifiers, or raw references
- **THEN** Event Graph nodes SHALL preserve those fields or a bounded diagnostic summary
- **AND** Tool Calls and Tool Results SHALL be linked by stable Tool Call ID when available

#### Scenario: Retain unmapped Events
- **WHEN** an Event cannot map to a fixed OpenSpec Action
- **THEN** the Event SHALL remain in the Event Graph
- **AND** its Action mapping SHALL be absent rather than represented by a fabricated required Action

### Requirement: User feedback diagnosis through Analyzer Adapter

系统 SHALL analyze natural-language feedback through the existing local Analyzer Adapter.

#### Scenario: Start one non-interactive analyzer session
- **WHEN** the user submits feedback for a loaded Session/change graph
- **THEN** the system SHALL build a compact Action/Event context
- **AND** SHALL call `run_mc_analysis()` once using the configured local AI CLI protocol
- **AND** SHALL NOT require a model HTTP API or project-level API Key configuration

#### Scenario: Analyzer unavailable
- **WHEN** the local analyzer CLI is missing, unauthenticated, fails, or times out
- **THEN** the API SHALL return a structured unavailable/error status
- **AND** the Viewer SHALL show a readable message without fabricating suspicious Events

### Requirement: Validated structured diagnosis

系统 SHALL validate all Analyzer-produced graph references before returning a diagnosis.

#### Scenario: Valid diagnosis references
- **WHEN** Analyzer output contains suspicious Action and Event IDs
- **THEN** every returned Action ID SHALL exist in the fixed Action Graph
- **AND** every returned Event ID SHALL exist in the current Event Graph
- **AND** invalid or fabricated IDs SHALL NOT be returned as valid evidence

#### Scenario: Invalid Analyzer JSON
- **WHEN** Analyzer output is empty, malformed, or cannot be parsed as the diagnosis schema
- **THEN** diagnosis SHALL return a parse/error status with missing evidence
- **AND** SHALL NOT invent fallback root-cause references

### Requirement: Viewer feedback-to-report flow

Diagnostics Viewer SHALL provide an end-to-end feedback diagnosis flow.

#### Scenario: Submit feedback and inspect report
- **WHEN** the user loads a Session-bound OpenSpec graph and submits feedback
- **THEN** Viewer SHALL display the diagnosis summary, suspicious Actions, suspicious Events, and missing evidence
- **AND** the user SHALL be able to locate or highlight referenced Action and Event nodes

### Requirement: Realistic OpenSpec Session fixture

系统 SHALL include a realistic Claude Code Session mock for manual MVP acceptance.

#### Scenario: Diagnose the mock Session
- **WHEN** Viewer loads the mock Session and its OpenSpec change
- **THEN** it SHALL display fixed Action and step-level Event graphs
- **AND** manually submitted feedback SHALL produce a report referencing real Action/Event IDs from the mock graph
