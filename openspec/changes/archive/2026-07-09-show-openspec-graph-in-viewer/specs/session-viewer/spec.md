## ADDED Requirements

### Requirement: OpenSpec Graph API

Viewer server SHALL provide an API for reading active OpenSpec graph artifacts.

#### Scenario: Read active change graph
- **WHEN** client requests `/api/openspec-graph/<change>`
- **THEN** server SHALL read `openspec/changes/<change>/graph/action_graph.json`
- **AND** server SHALL read `openspec/changes/<change>/graph/event_graph.json`
- **AND** server SHALL read `openspec/changes/<change>/graph/diagnosis.json`
- **AND** response SHALL contain `ok`, `change`, `actionGraph`, `eventGraph`, and `diagnosis`

#### Scenario: Graph missing
- **WHEN** graph artifacts are missing
- **THEN** server SHALL return a non-2xx response with a clear error

### Requirement: Diagnostics page graph rendering

Diagnostics page SHALL render OpenSpec Action Graph and Event Graph as point-line diagrams.

#### Scenario: Load graph by change name
- **WHEN** user enters a change name and clicks load
- **THEN** Viewer SHALL fetch `/api/openspec-graph/<change>`
- **AND** render an Action Graph panel
- **AND** render an Event Graph panel

#### Scenario: Action graph status
- **WHEN** Action Graph contains action nodes
- **THEN** Viewer SHALL display each node label and status
- **AND** workflow edges SHALL be visible as connecting lines

#### Scenario: Event graph detail
- **WHEN** Event Graph contains event nodes
- **THEN** Viewer SHALL display event nodes and edge lines
- **AND** node labels SHALL remain readable without overlapping adjacent controls
