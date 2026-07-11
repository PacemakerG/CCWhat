import { useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  Handle,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
  useReactFlow,
  useStore,
  useViewport,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  actionForEvent,
  actionNodePosition,
  diagnosisActionIds,
  eventNodePosition,
  isRelevantEvent,
} from './graphAdapter';
import type {
  ActionNode,
  FeedbackDiagnosis,
  GraphDiagnosisContext,
  GraphNode,
} from './types';

type ViewMode = 'overview' | 'action';
type InspectorSelection =
  | { kind: 'action'; id: string }
  | { kind: 'event'; id: string }
  | null;

type FlowData = {
  kind: 'action' | 'event';
  label: string;
  sublabel: string;
  status?: string;
  relevant?: boolean;
  muted?: boolean;
};

const ACTION_NODE_SIZE = { width: 168, height: 62 };
const EVENT_NODE_SIZE = { width: 152, height: 54 };

const copy = {
  zh: {
    overview: '总览', eventView: '事件证据', fit: '适配画布', diagnosisActions: '仅诊断相关粗节点', allActions: '显示全部粗节点',
    events: '事件', inspector: '节点检查器', noSelection: '选择一个节点查看原始证据',
    raw: '查看原始 Session', timeline: '执行时间线', coverage: '证据覆盖', diagnosis: '诊断路径',
    noDiagnosis: '尚未生成诊断。提交反馈后，这里会高亮候选 Action 和真实事件。',
    action: 'Action', type: '类型', status: '状态', time: '时间', files: '文件', command: '命令',
    toolInput: '工具输入', result: '工具结果', source: '原始引用', back: '返回总览',
  },
  en: {
    overview: 'Overview', eventView: 'Event evidence', fit: 'Fit view', diagnosisActions: 'Diagnosis actions only', allActions: 'Show all actions',
    events: 'events', inspector: 'Node inspector', noSelection: 'Select a node to inspect raw evidence',
    raw: 'Open raw Session', timeline: 'Execution timeline', coverage: 'Evidence coverage', diagnosis: 'Diagnosis path',
    noDiagnosis: 'No diagnosis yet. Submit feedback to highlight candidate actions and real events.',
    action: 'Action', type: 'Type', status: 'Status', time: 'Time', files: 'Files', command: 'Command',
    toolInput: 'Tool input', result: 'Tool result', source: 'Raw reference', back: 'Back to overview',
  },
} as const;

type Labels = { [K in keyof typeof copy.zh]: string };

function FlowActionNode({ data, selected }: NodeProps<Node<FlowData>>) {
  return <div className={`gd-node gd-action-node ${selected ? 'is-selected' : ''} ${data.relevant ? 'is-relevant' : ''} ${data.muted ? 'is-muted' : ''}`}>
    <Handle type="target" position={Position.Left} />
    <span className="gd-node-eyebrow">{data.status || 'observed'}</span>
    <strong>{data.label}</strong>
    <span>{data.sublabel}</span>
    <Handle type="source" position={Position.Right} />
  </div>;
}

function FlowEventNode({ data, selected }: NodeProps<Node<FlowData>>) {
  return <div className={`gd-node gd-event-node ${selected ? 'is-selected' : ''} ${data.relevant ? 'is-relevant' : ''}`}>
    <Handle type="target" position={Position.Left} />
    <strong>{data.label}</strong>
    <span>{data.sublabel}</span>
    <Handle type="source" position={Position.Right} />
  </div>;
}

const nodeTypes = { action: FlowActionNode, event: FlowEventNode };

function GraphDiagnosisCanvas({ context }: { context: GraphDiagnosisContext }) {
  const t = copy[context.locale];
  const payload = context.graphPayload;
  const actions = payload?.actionGraph.actions || [];
  const allEvents = payload?.eventGraph.nodes || [];
  const diagnosis = context.feedbackDiagnosis;
  const [view, setView] = useState<ViewMode>('overview');
  const [activeActionId, setActiveActionId] = useState<string | null>(null);
  const [selection, setSelection] = useState<InspectorSelection>(null);
  const [diagnosisActionsOnly, setDiagnosisActionsOnly] = useState(false);
  const { fitView, fitBounds, setCenter } = useReactFlow();
  const viewport = useViewport();
  const canvasWidth = useStore((state) => state.width);
  const canvasHeight = useStore((state) => state.height);

  useEffect(() => {
    setView('overview');
    setActiveActionId(null);
    setSelection(null);
    setDiagnosisActionsOnly(false);
  }, [context.changeName, payload]);

  const activeAction = actions.find((action) => action.action_id === activeActionId);
  const visibleEvents = useMemo(() => {
    if (!activeAction) return [];
    const byId = new Map(allEvents.map((event) => [event.node_id, event]));
    return activeAction.event_ids.map((id) => byId.get(id)).filter((event): event is GraphNode => Boolean(event));
  }, [activeAction, allEvents]);

  const flowNodes = useMemo<Node<FlowData>[]>(() => {
    if (view === 'overview') {
      const candidateIds = diagnosisActionIds(diagnosis);
      return actions
        .filter((action) => !diagnosisActionsOnly || candidateIds.has(action.action_id))
        .map((action, index) => ({
          id: action.action_id,
          type: 'action',
          position: actionNodePosition(index),
          data: {
            kind: 'action',
            label: action.label || action.action_id,
            sublabel: `${action.event_ids.length} ${t.events}`,
            status: action.status,
            relevant: candidateIds.has(action.action_id),
          },
        }));
    }
    const actionNodes = actions.map((action, index) => ({
      id: action.action_id,
      type: 'action',
      position: actionNodePosition(index),
      data: {
        kind: 'action' as const,
        label: action.label || action.action_id,
        sublabel: `${action.event_ids.length} ${t.events}`,
        status: action.status,
        relevant: diagnosisActionIds(diagnosis).has(action.action_id),
        muted: action.action_id !== activeActionId,
      },
    }));
    const actionIndex = Math.max(0, actions.findIndex((action) => action.action_id === activeActionId));
    return [...actionNodes, ...visibleEvents
      .map((event, index) => ({
        id: event.node_id,
        type: 'event',
        position: detailEventPosition(actionIndex, index),
        data: {
          kind: 'event' as const,
          label: event.label || event.node_id,
          sublabel: event.type,
          relevant: isRelevantEvent(event, actions, diagnosis),
        },
      }))];
  }, [actions, activeActionId, diagnosis, diagnosisActionsOnly, t.events, view, visibleEvents]);

  const flowEdges = useMemo<Edge[]>(() => {
    const ids = new Set(flowNodes.map((node) => node.id));
    const actionEdges = (payload?.actionGraph.edges || [])
      .filter((edge) => ids.has(edge.from) && ids.has(edge.to))
      .map((edge) => ({
        id: edge.edge_id,
        source: edge.from,
        target: edge.to,
        type: 'smoothstep',
        animated: Boolean(diagnosisActionsOnly && view === 'overview'),
        style: { stroke: 'var(--gd-line)', strokeWidth: 1.4 },
      }));
    if (view === 'overview') return actionEdges;
    const eventEdges = (payload?.eventGraph.edges || [])
      .filter((edge) => ids.has(edge.from) && ids.has(edge.to))
      .map((edge) => ({
        id: `event-${edge.edge_id}`,
        source: edge.from,
        target: edge.to,
        type: 'smoothstep',
        style: { stroke: 'var(--gd-line)', strokeWidth: 1.1 },
      }));
    if (activeActionId && visibleEvents[0]) {
      eventEdges.unshift({
        id: `detail-${activeActionId}`,
        source: activeActionId,
        target: visibleEvents[0].node_id,
        type: 'smoothstep',
        style: { stroke: 'var(--gd-accent)', strokeWidth: 1.4 },
      });
    }
    return [...actionEdges, ...eventEdges];
  }, [activeActionId, diagnosisActionsOnly, flowNodes, payload, view, visibleEvents]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      if (view === 'action' && activeActionId && visibleEvents.length) {
        const actionIndex = Math.max(0, actions.findIndex((action) => action.action_id === activeActionId));
        const origin = detailEventPosition(actionIndex, 0);
        fitBounds({
          x: origin.x - 76,
          y: 138,
          width: Math.max(420, (visibleEvents.length - 1) * 118 + 280),
          height: 370,
        }, { padding: 0.16, duration: 320 });
        return;
      }
      fitView({ padding: 0.22, duration: 320, maxZoom: 1.05 });
    }, 20);
    return () => window.clearTimeout(id);
  }, [actions, activeActionId, fitBounds, fitView, flowNodes, view, visibleEvents.length]);

  const selectedAction = selection?.kind === 'action' ? actions.find((action) => action.action_id === selection.id) : undefined;
  const selectedEvent = selection?.kind === 'event' ? allEvents.find((event) => event.node_id === selection.id) : undefined;
  const selectedEventAction = selectedEvent ? actionForEvent(actions, selectedEvent.node_id) : undefined;

  function openAction(actionId: string) {
    setActiveActionId(actionId);
    setSelection({ kind: 'action', id: actionId });
    setView('action');
  }

  function openRawEvent() {
    if (!selectedEvent) return;
    window.dispatchEvent(new CustomEvent('ccwhat:navigate-to-event', {
      detail: {
        sessionId: context.sessionId,
        eventId: selectedEvent.event_id || selectedEvent.node_id,
        rawRef: selectedEvent.data?.raw_ref,
      },
    }));
  }

  const coveredEvents = new Set(actions.flatMap((action) => action.event_ids));
  return <section className="gd-shell" data-theme={context.theme}>
    <header className="gd-toolbar">
      <div className="gd-breadcrumb">
        <button type="button" className="gd-crumb" onClick={() => { setView('overview'); setActiveActionId(null); }}>
          {context.changeName || 'OpenSpec'}
        </button>
        {activeAction && <><span>/</span><strong>{activeAction.label}</strong></>}
      </div>
      <div className="gd-toolbar-actions">
        {view === 'action' && <button type="button" className="gd-button" onClick={() => { setView('overview'); setActiveActionId(null); }}>{t.back}</button>}
        {view === 'overview' && diagnosis?.available && <button type="button" className={`gd-button ${diagnosisActionsOnly ? 'is-active' : ''}`} onClick={() => setDiagnosisActionsOnly((value) => !value)}>
          {diagnosisActionsOnly ? t.allActions : t.diagnosisActions}
        </button>}
        <button type="button" className="gd-button" onClick={() => fitView({ padding: 0.22, duration: 320 })}>{t.fit}</button>
      </div>
    </header>
    <DiagnosisPanel diagnosis={diagnosis} actions={actions} t={t} onAction={openAction} />
    <TimelinePanel actions={actions} activeActionId={activeActionId} view={view} t={t} onAction={openAction} onOverview={() => { setView('overview'); setActiveActionId(null); }} />
    <div className="gd-main">
      <div className="gd-canvas" aria-label={view === 'overview' ? t.overview : t.eventView}>
        {flowNodes.length ? <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          fitView
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          onNodeClick={(_, node) => {
            const nodeData = node.data as FlowData;
            if (nodeData.kind === 'action') openAction(node.id);
            else setSelection({ kind: 'event', id: node.id });
          }}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} color="var(--gd-grid)" />
          <Controls showInteractive={false} />
          <Panel position="bottom-right"><GraphNavigator nodes={flowNodes} edges={flowEdges} viewport={viewport} canvasWidth={canvasWidth} canvasHeight={canvasHeight} onNavigate={(x, y) => setCenter(x, y, { zoom: viewport.zoom, duration: 180 })} /></Panel>
        </ReactFlow> : <div className="gd-empty">{diagnosisActionsOnly ? t.noDiagnosis : 'No graph nodes'}</div>}
      </div>
      <aside className="gd-inspector">
        <div className="gd-panel-title">{t.inspector}</div>
        {!selection && <div className="gd-muted">{t.noSelection}</div>}
        {selectedAction && <ActionInspector action={selectedAction} t={t} />}
        {selectedEvent && <EventInspector event={selectedEvent} action={selectedEventAction} t={t} onRaw={openRawEvent} />}
      </aside>
    </div>
    <footer className="gd-footer">
      <section><div className="gd-panel-title">{t.coverage}</div><strong>{coveredEvents.size} / {allEvents.length}</strong><span className="gd-muted"> {t.events}</span></section>
    </footer>
  </section>;
}

function detailEventPosition(actionIndex: number, eventIndex: number) {
  const action = actionNodePosition(actionIndex);
  return {
    x: Math.max(32, action.x - 128 + eventIndex * 118),
    y: 350 + (eventIndex % 2) * 72,
  };
}

function GraphNavigator({
  nodes,
  edges,
  viewport,
  canvasWidth,
  canvasHeight,
  onNavigate,
}: {
  nodes: Node<FlowData>[];
  edges: Edge[];
  viewport: { x: number; y: number; zoom: number };
  canvasWidth: number;
  canvasHeight: number;
  onNavigate: (x: number, y: number) => void;
}) {
  const width = 232;
  const height = 138;
  const padding = 10;
  const nodeBox = (node: Node<FlowData>) => ({
    x: node.position.x,
    y: node.position.y,
    ...(node.data.kind === 'action' ? ACTION_NODE_SIZE : EVENT_NODE_SIZE),
  });
  const boxes = nodes.map(nodeBox);
  const minX = Math.min(...boxes.map((box) => box.x), 0) - 36;
  const minY = Math.min(...boxes.map((box) => box.y), 0) - 36;
  const maxX = Math.max(...boxes.map((box) => box.x + box.width), 1) + 36;
  const maxY = Math.max(...boxes.map((box) => box.y + box.height), 1) + 36;
  const graphWidth = Math.max(1, maxX - minX);
  const graphHeight = Math.max(1, maxY - minY);
  const scale = Math.min((width - padding * 2) / graphWidth, (height - padding * 2) / graphHeight);
  const offsetX = (width - graphWidth * scale) / 2;
  const offsetY = (height - graphHeight * scale) / 2;
  const point = (x: number, y: number) => ({ x: offsetX + (x - minX) * scale, y: offsetY + (y - minY) * scale });
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const viewportLeft = -viewport.x / viewport.zoom;
  const viewportTop = -viewport.y / viewport.zoom;
  const viewportWidth = canvasWidth / viewport.zoom;
  const viewportHeight = canvasHeight / viewport.zoom;
  const viewportPoint = point(viewportLeft, viewportTop);

  function navigate(event: React.PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) * (width / rect.width);
    const y = (event.clientY - rect.top) * (height / rect.height);
    onNavigate((x - offsetX) / scale + minX, (y - offsetY) / scale + minY);
  }

  return <section className="gd-navigator" aria-label="Graph navigator">
    <div className="gd-navigator-title">全图导航</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Complete graph and current viewport" onPointerDown={navigate}>
      <rect className="gd-navigator-surface" x="0" y="0" width={width} height={height} rx="5" />
      {edges.map((edge) => {
        const from = nodesById.get(edge.source);
        const to = nodesById.get(edge.target);
        if (!from || !to) return null;
        const fromBox = nodeBox(from);
        const toBox = nodeBox(to);
        const start = point(fromBox.x + fromBox.width / 2, fromBox.y + fromBox.height / 2);
        const end = point(toBox.x + toBox.width / 2, toBox.y + toBox.height / 2);
        return <line className="gd-navigator-edge" key={edge.id} x1={start.x} y1={start.y} x2={end.x} y2={end.y} />;
      })}
      {nodes.map((node) => {
        const box = nodeBox(node);
        const position = point(box.x, box.y);
        return <rect
          className={`gd-navigator-node ${node.data.kind === 'action' ? 'is-action' : 'is-event'} ${node.data.muted ? 'is-muted' : ''}`}
          key={node.id}
          x={position.x}
          y={position.y}
          width={Math.max(2.5, box.width * scale)}
          height={Math.max(2.5, box.height * scale)}
          rx="1.5"
        />;
      })}
      <rect
        className="gd-navigator-viewport"
        x={viewportPoint.x}
        y={viewportPoint.y}
        width={Math.min(width, viewportWidth * scale)}
        height={Math.min(height, viewportHeight * scale)}
        rx="2"
      />
    </svg>
    <div className="gd-navigator-hint">拖动或点击定位当前视口</div>
  </section>;
}

function TimelinePanel({
  actions,
  activeActionId,
  view,
  t,
  onAction,
  onOverview,
}: {
  actions: ActionNode[];
  activeActionId: string | null;
  view: ViewMode;
  t: Labels;
  onAction: (actionId: string) => void;
  onOverview: () => void;
}) {
  return <section className="gd-timeline-panel">
    <div className="gd-footer-heading"><div className="gd-panel-title">{t.timeline}</div>{view === 'action' && <button type="button" className="gd-button gd-timeline-back" onClick={onOverview}>{t.back}</button>}</div>
    <div className="gd-timeline">
      {actions.map((action) => <button key={action.action_id} type="button" className={`gd-timeline-step ${action.action_id === activeActionId ? 'is-active' : ''}`} onClick={() => onAction(action.action_id)}>{action.label}</button>)}
    </div>
  </section>;
}

function ActionInspector({ action, t }: { action: ActionNode; t: Labels }) {
  return <div className="gd-inspector-content">
    <h3>{action.label}</h3>
    <Info label={t.type} value={action.type} /><Info label={t.status} value={action.status} />
    <Info label={t.time} value={[action.started_at, action.ended_at].filter(Boolean).join(' → ') || '—'} />
    <Info label={t.events} value={String(action.event_ids.length)} />
  </div>;
}

function EventInspector({ event, action, t, onRaw }: { event: GraphNode; action?: ActionNode; t: Labels; onRaw: () => void }) {
  const data = event.data || {};
  return <div className="gd-inspector-content">
    <h3>{event.label || event.node_id}</h3>
    <Info label="ID" value={event.node_id} /><Info label={t.type} value={event.type} />
    <Info label={t.action} value={action?.label || '—'} /><Info label={t.time} value={event.timestamp || '—'} />
    <Info label={t.files} value={Array.isArray(data.files) ? data.files.join('\n') || '—' : '—'} />
    <Info label={t.command} value={String(data.command || '—')} />
    <Info label={t.toolInput} value={data.tool_input ? JSON.stringify(data.tool_input, null, 2) : '—'} />
    <Info label={t.result} value={String(data.result_summary || '—')} />
    <Info label={t.source} value={data.raw_ref ? JSON.stringify(data.raw_ref) : '—'} />
    <button type="button" className="gd-button gd-raw-button" onClick={onRaw}>{t.raw}</button>
  </div>;
}

function DiagnosisPanel({ diagnosis, actions, t, onAction }: { diagnosis?: FeedbackDiagnosis; actions: ActionNode[]; t: Labels; onAction: (id: string) => void }) {
  if (!diagnosis?.available) return null;
  return <section className="gd-diagnosis gd-diagnosis-top"><div className="gd-panel-title">{t.diagnosis}</div>
    <>
      <p>{diagnosis.summary || '—'}</p>
      {(diagnosis.suspicious_actions || []).map((item) => {
        const action = actions.find((candidate) => candidate.action_id === item.action_id);
        return action ? <button type="button" className="gd-diagnosis-link" key={action.action_id} onClick={() => onAction(action.action_id)}>{action.label} · {item.reason || 'candidate'}</button> : null;
      })}
    </>
  </section>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="gd-info"><span>{label}</span><pre>{value}</pre></div>;
}

export function GraphDiagnosisApp({ context }: { context: GraphDiagnosisContext }) {
  return <ReactFlowProvider><GraphDiagnosisCanvas context={context} /></ReactFlowProvider>;
}
