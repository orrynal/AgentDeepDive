import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  MarkerType,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { Cpu, Layers } from 'lucide-react';
import CustomNode from './components/CustomNode';

import { CockpitHeader } from './components/CockpitHeader';
import { MissionControl } from './components/MissionControl';
import { LogTelemetry } from './components/LogTelemetry';
import { ApprovalGate } from './components/ApprovalGate';
import { SkillMarketDialog } from './components/SkillMarketDialog';
import { WorkspaceDialog } from './components/WorkspaceDialog';
import { DiagnosticsDialog } from './components/DiagnosticsDialog';
import { OpaPolicyDialog } from './components/OpaPolicyDialog';
import { CeleryStatsDialog } from './components/CeleryStatsDialog';
import { ApprovalDialog } from './components/ApprovalDialog';
import { useSkillManager } from './hooks/useSkillManager';
import { useWorkspaceManager } from './hooks/useWorkspaceManager';

// Calculate base URL relative to window.location dynamically
const getApiBase = () => {
  if (typeof window === 'undefined') return 'http://localhost:8000';
  const backendHost = window.location.port === '5173'
    ? `${window.location.hostname}:8000`
    : window.location.host;
  return `${window.location.protocol}//${backendHost}`;
};
export const API_BASE = getApiBase();

// Custom node types registry
const nodeTypes = {
  custom: CustomNode,
};

// Initial Sample DAG for visualization
const initialNodes: Node[] = [
  {
    id: '1',
    type: 'custom',
    data: { name: 'Auto-Split Task', skillId: 'task-splitter', roleId: 'supervisor', color: 'success', progress: 100, tokenCost: 1200 },
    position: { x: 250, y: 20 },
  },
  {
    id: '2',
    type: 'custom',
    data: { name: 'Analyze Codebase', skillId: 'code-analyzer', roleId: 'security_auditor', color: 'success', progress: 100, tokenCost: 2400 },
    position: { x: 50, y: 150 },
  },
  {
    id: '3',
    type: 'custom',
    data: { name: 'Generate Patch', skillId: 'code-patcher', roleId: 'senior_coder', color: 'running', progress: 65, tokenCost: 8900 },
    position: { x: 450, y: 150 },
  },
  {
    id: '4',
    type: 'custom',
    data: { name: 'Docker Sandbox Test', skillId: 'sandbox-exec', roleId: 'qa_tester', color: 'queued', progress: 0, tokenCost: 0 },
    position: { x: 250, y: 280 },
  },
  {
    id: '5',
    type: 'custom',
    data: { name: 'Human Review Patch', skillId: 'human-gate', roleId: 'editor', color: 'suspended', progress: 0, tokenCost: 0 },
    position: { x: 450, y: 280 },
  },
  {
    id: '6',
    type: 'custom',
    data: { name: 'Apply & Commit', skillId: 'git-committer', roleId: 'senior_coder', color: 'ready', progress: 0, tokenCost: 0 },
    position: { x: 250, y: 400 },
  },
];

const initialEdges = [
  { id: 'e1-2', source: '1', target: '2', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' } },
  { id: 'e1-3', source: '1', target: '3', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' } },
  { id: 'e2-4', source: '2', target: '4', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' } },
  { id: 'e3-5', source: '3', target: '5', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' } },
  { id: 'e4-6', source: '4', target: '6', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' } },
  { id: 'e5-6', source: '5', target: '6', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' } },
];

const initialBlueprintNodes: Node[] = [
  // ─── PARENT GROUPS (MIND MAP BUCKETS) ───
  {
    id: 'bp-group-gateway',
    data: { label: 'Interface & API Gateway / 接入与网关层' },
    position: { x: 50, y: 50 },
    style: { width: 280, height: 400 },
    type: 'group',
  },
  {
    id: 'bp-group-orchestrator',
    data: { label: 'Core Orchestrator & Routing / 调度与路由层' },
    position: { x: 370, y: 50 },
    style: { width: 280, height: 400 },
    type: 'group',
  },
  {
    id: 'bp-group-execution',
    data: { label: 'Execution Runtime & Sandbox / 执行与沙箱层' },
    position: { x: 690, y: 50 },
    style: { width: 280, height: 400 },
    type: 'group',
  },
  {
    id: 'bp-group-security',
    data: { label: 'HITL Protection & Governance / 安全与人机审批' },
    position: { x: 1010, y: 50 },
    style: { width: 280, height: 400 },
    type: 'group',
  },
  {
    id: 'bp-group-memory',
    data: { label: 'Memory & Self-Evolution / 记忆与自演进飞轮' },
    position: { x: 1330, y: 50 },
    style: { width: 280, height: 400 },
    type: 'group',
  },
  {
    id: 'bp-group-brain',
    data: { label: 'Central Brain & Space-Time Cycle / 时空与大脑核心' },
    position: { x: 1650, y: 50 },
    style: { width: 280, height: 400 },
    type: 'group',
  },

  // ─── CHILD NODES (RELATIVE TO PARENTS) ───
  // Gateway Group
  {
    id: 'bp-cli',
    parentId: 'bp-group-gateway',
    type: 'custom',
    data: { name: '统一终端 CLI 入口', skillId: 'cli-shell', roleId: 'admin', color: 'success', progress: 100, tokenCost: 15 },
    position: { x: 25, y: 40 },
    extent: 'parent',
  },
  {
    id: 'bp-webui',
    parentId: 'bp-group-gateway',
    type: 'custom',
    data: { name: 'Cockpit 仪表盘中控台', skillId: 'react-ui', roleId: 'developer', color: 'success', progress: 100, tokenCost: 20 },
    position: { x: 25, y: 160 },
    extent: 'parent',
  },
  {
    id: 'bp-api',
    parentId: 'bp-group-gateway',
    type: 'custom',
    data: { name: 'FastAPI 后端集成路由', skillId: 'fastapi', roleId: 'developer', color: 'success', progress: 100, tokenCost: 25 },
    position: { x: 25, y: 280 },
    extent: 'parent',
  },

  // Orchestrator Group
  {
    id: 'bp-dag',
    parentId: 'bp-group-orchestrator',
    type: 'custom',
    data: { name: 'DAG 编排调度引擎', skillId: 'dag-orchestrator', roleId: 'supervisor', color: 'success', progress: 100, tokenCost: 35 },
    position: { x: 25, y: 40 },
    extent: 'parent',
  },
  {
    id: 'bp-router',
    parentId: 'bp-group-orchestrator',
    type: 'custom',
    data: { name: '自适应智能路由器', skillId: 'adaptive-router', roleId: 'supervisor', color: 'success', progress: 100, tokenCost: 30 },
    position: { x: 25, y: 160 },
    extent: 'parent',
  },
  {
    id: 'bp-contract',
    parentId: 'bp-group-orchestrator',
    type: 'custom',
    data: { name: 'FIPA-ACL 契约网竞标', skillId: 'contract-net', roleId: 'analyst', color: 'success', progress: 100, tokenCost: 40 },
    position: { x: 25, y: 280 },
    extent: 'parent',
  },

  // Execution Group
  {
    id: 'bp-executor',
    parentId: 'bp-group-execution',
    type: 'custom',
    data: { name: 'AgentExecutor 运行时', skillId: 'agent-runtime', roleId: 'supervisor', color: 'success', progress: 100, tokenCost: 45 },
    position: { x: 25, y: 40 },
    extent: 'parent',
  },
  {
    id: 'bp-docker',
    parentId: 'bp-group-execution',
    type: 'custom',
    data: { name: 'Docker 物理沙箱隔离', skillId: 'docker-exec', roleId: 'qa', color: 'success', progress: 100, tokenCost: 50 },
    position: { x: 25, y: 160 },
    extent: 'parent',
  },
  {
    id: 'bp-k8s',
    parentId: 'bp-group-execution',
    type: 'custom',
    data: { name: 'Kubernetes 隔离运行时', skillId: 'k8s-exec', roleId: 'qa', color: 'success', progress: 100, tokenCost: 55 },
    position: { x: 25, y: 280 },
    extent: 'parent',
  },

  // Security Group
  {
    id: 'bp-guardrails',
    parentId: 'bp-group-security',
    type: 'custom',
    data: { name: 'OPA/Rego 安全守卫', skillId: 'guardrails-rego', roleId: 'security', color: 'success', progress: 100, tokenCost: 60 },
    position: { x: 25, y: 40 },
    extent: 'parent',
  },
  {
    id: 'bp-hitl',
    parentId: 'bp-group-security',
    type: 'custom',
    data: { name: '人机协同审批与 Diff', skillId: 'hitl-gate', roleId: 'editor', color: 'success', progress: 100, tokenCost: 65 },
    position: { x: 25, y: 160 },
    extent: 'parent',
  },
  {
    id: 'bp-sentinel',
    parentId: 'bp-group-security',
    type: 'custom',
    data: { name: 'Sentinel 守护垃圾回收', skillId: 'sentinel-gc', roleId: 'security', color: 'success', progress: 100, tokenCost: 70 },
    position: { x: 25, y: 280 },
    extent: 'parent',
  },

  // Memory Group
  {
    id: 'bp-memory',
    parentId: 'bp-group-memory',
    type: 'custom',
    data: { name: 'Milvus 向量知识检索', skillId: 'rag-memory', roleId: 'analyst', color: 'success', progress: 100, tokenCost: 75 },
    position: { x: 25, y: 40 },
    extent: 'parent',
  },
  {
    id: 'bp-abtesting',
    parentId: 'bp-group-memory',
    type: 'custom',
    data: { name: 'Prompt 自演进灰度 A/B', skillId: 'ab-flywheel', roleId: 'developer', color: 'yellow', progress: 60, tokenCost: 80 },
    position: { x: 25, y: 160 },
    extent: 'parent',
  },
  {
    id: 'bp-dialogue',
    parentId: 'bp-group-memory',
    type: 'custom',
    data: { name: 'Agent 间交流共识系统', skillId: 'dialogue', roleId: 'lang', color: 'ready', progress: 0, tokenCost: 0 },
    position: { x: 25, y: 280 },
    extent: 'parent',
  },

  // Brain Group
  {
    id: 'bp-tiangan',
    parentId: 'bp-group-brain',
    type: 'custom',
    data: { name: '天干地支时间记忆轮转', skillId: 'tgdz-cycle', roleId: 'data', color: 'ready', progress: 0, tokenCost: 0 },
    position: { x: 25, y: 80 },
    extent: 'parent',
  },
  {
    id: 'bp-centralbrain',
    parentId: 'bp-group-brain',
    type: 'custom',
    data: { name: '中央大脑控制核心', skillId: 'central-brain', roleId: 'supervisor', color: 'success', progress: 100, tokenCost: 0 },
    position: { x: 25, y: 200 },
    extent: 'parent',
  },
];

const initialBlueprintEdges = [
  // CLI/WebUI -> API
  { id: 'e-cli-api', source: 'bp-cli', target: 'bp-api', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },
  { id: 'e-webui-api', source: 'bp-webui', target: 'bp-api', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // API -> DAG Engine
  { id: 'e-api-dag', source: 'bp-api', target: 'bp-dag', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // DAG Engine -> Router
  { id: 'e-dag-router', source: 'bp-dag', target: 'bp-router', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Router -> Contract Net
  { id: 'e-router-contract', source: 'bp-router', target: 'bp-contract', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Router -> Executor
  { id: 'e-router-executor', source: 'bp-router', target: 'bp-executor', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },
  { id: 'e-contract-executor', source: 'bp-contract', target: 'bp-executor', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Executor -> Sandbox (Docker/K8s)
  { id: 'e-executor-docker', source: 'bp-executor', target: 'bp-docker', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },
  { id: 'e-executor-k8s', source: 'bp-executor', target: 'bp-k8s', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Executor -> Guardrails -> HITL
  { id: 'e-executor-guard', source: 'bp-executor', target: 'bp-guardrails', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },
  { id: 'e-guard-hitl', source: 'bp-guardrails', target: 'bp-hitl', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Sandbox/HITL -> Sentinel
  { id: 'e-docker-sentinel', source: 'bp-docker', target: 'bp-sentinel', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },
  { id: 'e-hitl-sentinel', source: 'bp-hitl', target: 'bp-sentinel', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Sentinel/Executor -> Memory (RAG)
  { id: 'e-executor-memory', source: 'bp-executor', target: 'bp-memory', animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }, style: { stroke: '#22c55e', strokeWidth: 2 } },

  // Memory -> AB Testing
  { id: 'e-memory-ab', source: 'bp-memory', target: 'bp-abtesting', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: '#eab308' }, style: { stroke: '#eab308', strokeWidth: 2, strokeDasharray: '5 5' } },

  // Future Connections: AB Testing -> Dialogue, Central Brain, Tiangan
  { id: 'e-ab-central', source: 'bp-abtesting', target: 'bp-centralbrain', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(100, 116, 139, 0.2)' }, style: { stroke: 'rgba(100, 116, 139, 0.2)', strokeWidth: 2 } },
  { id: 'e-dialogue-central', source: 'bp-dialogue', target: 'bp-centralbrain', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(100, 116, 139, 0.2)' }, style: { stroke: 'rgba(100, 116, 139, 0.2)', strokeWidth: 2 } },
  { id: 'e-tiangan-central', source: 'bp-tiangan', target: 'bp-centralbrain', animated: false, markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(100, 116, 139, 0.2)' }, style: { stroke: 'rgba(100, 116, 139, 0.2)', strokeWidth: 2 } },
];

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const [viewMode, setViewMode] = useState<'task' | 'blueprint'>('task');
  const [bpNodes, , onBpNodesChange] = useNodesState(initialBlueprintNodes);
  const [bpEdges, , onBpEdgesChange] = useEdgesState(initialBlueprintEdges);

  // High-frequency WebSocket event buffer queue (100ms debounce/throttle)
  const pendingUpdates = useRef<{
    dag_updates: any[];
    approval_updates: any[];
    recovery_updates: any[];
  }>({
    dag_updates: [],
    approval_updates: [],
    recovery_updates: [],
  });
  const [wsConnected, setWsConnected] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [sentinelState, setSentinelState] = useState<'active' | 'recovery' | 'idle'>('active');
  const [concurrencyActive, setConcurrencyActive] = useState(3);
  
  // Real task execution states
  const [taskPrompt, setTaskPrompt] = useState('');
  const [taskLauncherStatus, setTaskLauncherStatus] = useState('');
  const [isExecutingRealTask, setIsExecutingRealTask] = useState(false);
  const [hasProjectStarted, setHasProjectStarted] = useState(false);

  // Derived display nodes for grey-out effect
  const displayNodes = useMemo(() => {
    return nodes.map((node) => {
      const status = (node.data?.color as string) || 'ready';
      // If project has not started, every node is inactive.
      // If project has started, nodes that are success/running/failed/suspended/green/yellow/red/orange/blue/queued are active;
      // ready/idle/gray nodes are inactive.
      const isNodeActive = [
        'success', 'running', 'failed', 'suspended',
        'green', 'yellow', 'red', 'orange', 'blue', 'queued'
      ].includes(status.toLowerCase());
      const isInactive = !hasProjectStarted || !isNodeActive;
      return {
        ...node,
        data: {
          ...node.data,
          isInactive,
        },
      };
    });
  }, [nodes, hasProjectStarted]);

  // Derived display edges for active connection flow styling
  const displayEdges = useMemo(() => {
    return edges.map((edge) => {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetNode = nodes.find((n) => n.id === edge.target);

      const sourceStatus = (sourceNode?.data?.color as string) || 'ready';
      const targetStatus = (targetNode?.data?.color as string) || 'ready';

      const isSourceCompleted = ['success', 'failed', 'green', 'red'].includes(sourceStatus.toLowerCase());

      if (!hasProjectStarted) {
        // No project running: all edges grey and static
        return {
          ...edge,
          animated: false,
          style: { stroke: 'rgba(100, 116, 139, 0.2)', strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(100, 116, 139, 0.2)' }
        };
      }

      if (isSourceCompleted) {
        // Source completed: success green line pointing to the next node
        // Animated if the next node is running, queued, or suspended.
        const isActiveFlow = ['running', 'queued', 'suspended', 'yellow', 'blue', 'orange'].includes(targetStatus.toLowerCase());
        return {
          ...edge,
          animated: isActiveFlow,
          style: {
            stroke: '#22c55e',
            strokeWidth: 2,
            filter: isActiveFlow ? 'drop-shadow(0 0 4px #22c55e)' : 'none',
            transition: 'stroke 0.5s ease, filter 0.5s ease',
          },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' }
        };
      } else {
        // Source not completed: grey/inactive edge
        return {
          ...edge,
          animated: false,
          style: { stroke: 'rgba(100, 116, 139, 0.2)', strokeWidth: 2, transition: 'stroke 0.5s ease' },
          markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(100, 116, 139, 0.2)' }
        };
      }
    });
  }, [edges, nodes, hasProjectStarted]);

  // Layout nodes topologically
  const layoutNodes = useCallback((backendNodes: Array<any>, backendEdges: Array<any>) => {
    const layers: { [key: string]: number } = {};
    const queue: string[] = [];
    const inDegree: { [key: string]: number } = {};
    const adj: { [key: string]: string[] } = {};

    backendNodes.forEach(n => {
      inDegree[n.node_id] = 0;
      adj[n.node_id] = [];
      layers[n.node_id] = 0;
    });

    backendEdges.forEach(e => {
      adj[e.from].push(e.to);
      inDegree[e.to] = (inDegree[e.to] || 0) + 1;
    });

    backendNodes.forEach(n => {
      if (inDegree[n.node_id] === 0) {
        queue.push(n.node_id);
      }
    });

    while (queue.length > 0) {
      const curr = queue.shift()!;
      const nextNodes = adj[curr] || [];
      nextNodes.forEach(nxt => {
        layers[nxt] = Math.max(layers[nxt], layers[curr] + 1);
        inDegree[nxt]--;
        if (inDegree[nxt] === 0) {
          queue.push(nxt);
        }
      });
    }

    const layerCounts: { [key: number]: number } = {};
    backendNodes.forEach(n => {
      const lyr = layers[n.node_id] || 0;
      layerCounts[lyr] = (layerCounts[lyr] || 0) + 1;
    });

    const layerIndices: { [key: number]: number } = {};
    return backendNodes.map(n => {
      const lyr = layers[n.node_id] || 0;
      const idx = layerIndices[lyr] || 0;
      layerIndices[lyr] = idx + 1;

      const totalInLayer = layerCounts[lyr] || 1;
      const x = 300 + (idx - (totalInLayer - 1) / 2) * 260;
      const y = 50 + lyr * 130;

      return {
        id: n.node_id,
        type: 'custom',
        data: {
          name: n.name,
          skillId: n.skill_id,
          roleId: n.role_id || 'auto',
          color: n.color || 'ready',
          progress: ['success', 'green'].includes(n.color) ? 100 : ['running', 'yellow'].includes(n.color) ? 50 : 0,
          tokenCost: 0,
        },
        position: { x, y },
      };
    });
  }, []);

  const handleLaunchTask = async () => {
    if (!taskPrompt.trim()) return;
    setIsExecutingRealTask(true);
    setHasProjectStarted(true);
    setTaskLauncherStatus('Decomposing task into DAG...');
    setCotLogs([]);
    setApprovals([]);
    
    try {
      // 1. Auto-split task description into a DAG
      const splitRes = await fetch(`${API_BASE}/api/v1/dags/auto-split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: taskPrompt })
      });
      
      if (!splitRes.ok) {
        throw new Error('Failed to auto-split task. Is the backend running?');
      }
      
      const dagData = await splitRes.json();
      const { dag_id, nodes: backendNodes, edges: backendEdges } = dagData;
      setActiveDagId(dag_id);
      
      setTaskLauncherStatus(`DAG Created (${dag_id}). Arranging layout...`);
      
      // Calculate layout and set nodes/edges state
      const formattedNodes = layoutNodes(backendNodes, backendEdges);
      const formattedEdges = backendEdges.map((e: any) => ({
        id: `e-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: 'rgba(255,255,255,0.2)' }
      }));
      
      setNodes(formattedNodes);
      setEdges(formattedEdges);
      
      setTaskLauncherStatus('Executing DAG on backend...');
      
      // 2. Trigger async execution on backend
      const executeRes = await fetch(`${API_BASE}/api/v1/dags/${dag_id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      
      if (!executeRes.ok) {
        throw new Error('Execution failed to start.');
      }
      
      setTaskLauncherStatus('DAG Running! Monitor logs & states.');
    } catch (err: any) {
      console.error(err);
      setTaskLauncherStatus(`Error: ${err.message}`);
      setIsExecutingRealTask(false);
    }
  };

  const handleRestoreTask = async () => {
    // If we don't have an activeDagId in state, let's try to restore the active DAG first to find it
    let currentDagId = activeDagId;
    if (!currentDagId) {
      setTaskLauncherStatus('Restoring active DAG state from backend first...');
      try {
        const listRes = await fetch(`${API_BASE}/api/v1/dags`);
        if (listRes.ok) {
          const dags = await listRes.json();
          if (dags.length > 0) {
            const sortedDags = dags.sort((a: any, b: any) => 
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
            );
            currentDagId = sortedDags[0].dag_id;
            setActiveDagId(currentDagId);
          }
        }
      } catch (err) {
        console.error('Failed to pre-fetch active DAG for restore:', err);
      }
    }

    if (!currentDagId) {
      setTaskLauncherStatus('No active task to restore.');
      return;
    }

    setIsExecutingRealTask(true);
    setTaskLauncherStatus('Restoring and resuming task...');
    try {
      const res = await fetch(`${API_BASE}/api/v1/dags/${currentDagId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (res.ok) {
        setTaskLauncherStatus('Task execution resumed successfully.');
        restoreActiveDAG();
      } else {
        const errData = await res.json();
        setTaskLauncherStatus(`Failed to resume task: ${errData.detail || 'Unknown error'}`);
        setIsExecutingRealTask(false);
      }
    } catch (err: any) {
      setTaskLauncherStatus(`Error resuming task: ${err.message || err}`);
      setIsExecutingRealTask(false);
    }
  };

  const handleCancelTask = async () => {
    if (!activeDagId) return;
    setTaskLauncherStatus('Sending cancellation request...');
    try {
      const res = await fetch(`${API_BASE}/api/v1/dags/${activeDagId}/cancel`, {
        method: 'POST'
      });
      if (res.ok) {
        setTaskLauncherStatus('Cancellation request sent. Stopping execution...');
      } else {
        throw new Error('Failed to cancel execution.');
      }
    } catch (err: any) {
      console.error(err);
      setTaskLauncherStatus(`Error: ${err.message}`);
    }
  };
  
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Real-time metrics
  const [localTokenCost, setLocalTokenCost] = useState(128400);
  const [cloudTokenCost] = useState(22600);
  const [totalCostUSD, setTotalCostUSD] = useState(2.48);

  // CoT Log entries
  const [cotLogs, setCotLogs] = useState<Array<{ id: string; nodeId?: string; type: 'thought' | 'tool' | 'observation'; text: string; time: string }>>([
    { id: '1', nodeId: '1', type: 'thought', text: 'Initializing multi-agent topological task splitting...', time: '09:20:01' },
    { id: '2', nodeId: '1', type: 'tool', text: 'Calling split_task() with request: "Optimize code and verify in sandbox"', time: '09:20:02' },
    { id: '3', nodeId: '1', type: 'observation', text: 'Decomposed task into 6 topological execution nodes.', time: '09:20:04' },
    { id: '4', nodeId: '1', type: 'thought', text: 'Executing Node 1 (Auto-Split Task) using skill: task-splitter.', time: '09:20:05' },
    { id: '5', nodeId: '1', type: 'observation', text: 'Node 1 finished. Execution results propagated to Node 2 and Node 3.', time: '09:20:08' },
    { id: '6', nodeId: '2', type: 'thought', text: 'Starting parallel nodes: Node 2 (Analyze Codebase) and Node 3 (Generate Patch).', time: '09:20:10' },
  ]);

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    if (viewMode === 'blueprint') {
      return bpNodes.find((n) => n.id === selectedNodeId);
    }
    return nodes.find((n) => n.id === selectedNodeId);
  }, [nodes, bpNodes, selectedNodeId, viewMode]);

  const filteredLogs = useMemo(() => {
    if (!selectedNodeId) return cotLogs;
    const name = selectedNode?.data?.name as string | undefined;
    return cotLogs.filter(
      (log) => 
        log.nodeId === selectedNodeId || 
        (name && log.nodeId === name) ||
        (log.text && log.text.includes(`[${selectedNodeId}]`)) ||
        (name && log.text && log.text.includes(`[${name}]`))
    );
  }, [cotLogs, selectedNodeId, selectedNode]);

  // Approvals list
  const [approvals, setApprovals] = useState<Array<{
    approval_id: string;
    task_id: string;
    agent_id: string;
    tool_name: string;
    arguments: any;
    priority: number;
    status: 'pending' | 'approved' | 'rejected';
    diff?: string;
    task_description?: string;
    workspace_path?: string;
    project_name?: string;
  }>>([
    {
      approval_id: 'appr-a49d8c',
      task_id: 'dag-migration:node-5',
      agent_id: 'skill:human-gate',
      tool_name: 'git_commit_push',
      arguments: {
        branch: 'main',
        commit_message: 'feat: apply automated code quality patches',
        modified_files: ['src/core/agent/executor.py', 'src/core/concurrency/lock_manager.py']
      },
      priority: 85,
      status: 'pending',
      task_description: 'Apply automated code quality patches to git repository',
      project_name: 'demo-project',
      workspace_path: '/path/to/demo-project'
    }
  ]);

  const [activeApprovalId, setActiveApprovalId] = useState<string | null>(null);
  const [editableArgs, setEditableArgs] = useState<string>('{}');

  // Auto-Approve Governance State & Handlers
  const [autoApprove, setAutoApprove] = useState<boolean>(false);
  const [autoApproveL4, setAutoApproveL4] = useState<boolean>(false);

  useEffect(() => {
    fetch(`${API_BASE}/config/auto-approve`)
      .then(res => res.json())
      .then(data => {
        setAutoApprove(data.auto_approve_l3);
        setAutoApproveL4(data.auto_approve_l4 || false);
      })
      .catch(err => console.log('Failed to fetch auto-approve config', err));
  }, []);

  const handleToggleAutoApprove = () => {
    const nextVal = !autoApprove;
    setAutoApprove(nextVal);
    fetch(`${API_BASE}/config/auto-approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_approve_l3: nextVal })
    })
    .then(res => res.json())
    .then(data => {
      setAutoApprove(data.auto_approve_l3);
      setCotLogs(prev => [
        ...prev,
        {
          id: Math.random().toString(),
          type: 'observation',
          text: `⚙️ L3 Auto-Approval Governance: ${data.auto_approve_l3 ? 'ENABLED (Auto-Grant)' : 'DISABLED (HIL Approval Required)'}`,
          time: new Date().toLocaleTimeString()
        }
      ]);
    })
    .catch(err => {
      console.log('Failed to toggle auto-approve', err);
      setAutoApprove(!nextVal);
    });
  };

  const handleToggleAutoApproveL4 = () => {
    const nextVal = !autoApproveL4;
    
    if (nextVal) {
      const confirmed = window.confirm(
        "⚠️ 安全警告 (Security Warning):\n\n" +
        "开启 L4 自动授权意味着允许 AI 智能体自动执行具有最高风险的操作（例如写入系统核心文件、修改全局凭证、越权执行关键命令等）。\n\n" +
        "此操作可能导致系统被恶意篡改、发生文件损坏或带来重大安全风险。仅建议在受保护的隔离开发环境（Sandbox）下开启。\n\n" +
        "确定要开启 L4 自动授权吗？"
      );
      if (!confirmed) return;
    }

    setAutoApproveL4(nextVal);
    fetch(`${API_BASE}/config/auto-approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_approve_l4: nextVal })
    })
    .then(res => res.json())
    .then(data => {
      setAutoApproveL4(data.auto_approve_l4);
      setCotLogs(prev => [
        ...prev,
        {
          id: Math.random().toString(),
          type: 'observation',
          text: `⚙️ L4 Auto-Approval Governance: ${data.auto_approve_l4 ? 'ENABLED (High-Risk Auto-Grant)' : 'DISABLED (HIL Approval Required)'}`,
          time: new Date().toLocaleTimeString()
        }
      ]);
    })
    .catch(err => {
      console.log('Failed to toggle L4 auto-approve', err);
      setAutoApproveL4(!nextVal);
    });
  };

  const [activeDagId, setActiveDagId] = useState<string | null>(null);

  const {
    activeWorkspace,
    workspaces,
    isWorkspaceDialogOpen,
    setIsWorkspaceDialogOpen,
    newWorkspacePath,
    setNewWorkspacePath,
    handleSwitchWorkspace,
    handleCreateWorkspace,
    initWorkspaceAndDAG,
    restoreActiveDAG,
    availableDags,
    loadDAG,
  } = useWorkspaceManager(
    setNodes,
    setEdges,
    setHasProjectStarted,
    setTaskLauncherStatus,
    setActiveDagId,
    setIsExecutingRealTask,
    layoutNodes
  );

  const {
    isMarketOpen,
    setIsMarketOpen,
    marketTab,
    setMarketTab,
    marketSkills,
    marketSearchQuery,
    setMarketSearchQuery,
    installedSkills,
    fetchInstalledSkills,
    installingSkillId,
    setInstallingSkillId,
    installScope,
    setInstallScope,
    installWorkspacePath,
    setInstallWorkspacePath,
    installStatus,
    setInstallStatus,
    previewContent,
    setPreviewContent,
    previewResult,
    previewLoading,
    previewError,
    handleToggleSkill,
    handleDeleteSkill,
    fetchMarketSkills,
    handleInstallSkill,
    handlePreviewSkill,
    handleInstallPreviewedSkill,
  } = useSkillManager(activeWorkspace, setCotLogs);

  // Webhook Diagnostics State
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState<boolean>(false);
  const [isOpaDialogOpen, setIsOpaDialogOpen] = useState<boolean>(false);
  const [isCeleryStatsOpen, setIsCeleryStatsOpen] = useState<boolean>(false);
  const [diagnosingChannel, setDiagnosingChannel] = useState<string>('telegram');
  const [diagnosticResult, setDiagnosticResult] = useState<any>(null);
  const [diagnosticLoading, setDiagnosticLoading] = useState<boolean>(false);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);

  const handleTestWebhookConnection = async () => {
    setDiagnosticLoading(true);
    setDiagnosticError(null);
    setDiagnosticResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/approvals/diagnose/${diagnosingChannel}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setDiagnosticResult(data);
      } else {
        const errData = await res.json();
        setDiagnosticError(errData.detail || 'Diagnostic connection test failed.');
      }
    } catch (err: any) {
      setDiagnosticError(err.message || 'Network connection failed.');
    } finally {
      setDiagnosticLoading(false);
    }
  };

  // Fetch and restore the active workspace and DAG state on page load or when server becomes connected
  useEffect(() => {
    initWorkspaceAndDAG();
  }, [initWorkspaceAndDAG, wsConnected]);

  // Fetch pending approvals on load or activeWorkspace change
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/approvals/pending`)
      .then(res => {
        if (!res.ok) throw new Error();
        return res.json();
      })
      .then(data => {
        if (data && data.length > 0) {
          setApprovals(data);
          const latestPending = [...data].reverse().find(u => u.status === 'pending');
          if (latestPending) {
            setActiveApprovalId(latestPending.approval_id);
            setEditableArgs(JSON.stringify(latestPending.arguments, null, 2));
          }
        } else {
          setApprovals([]);
          setActiveApprovalId(null);
        }
      })
      .catch(err => console.log('Failed to fetch pending approvals', err));
  }, [activeWorkspace]);

  // Connect to FastAPI WebSocket with 100ms batched state updates
  useEffect(() => {
    let ws: WebSocket;
    let retryDelay = 2000;
    
    const connectWS = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      // Auto-detect backend port (default to 8000 if frontend runs on Vite port 5173)
      const backendHost = window.location.port === '5173'
        ? `${window.location.hostname}:8000`
        : window.location.host;
      const wsUrl = `${protocol}//${backendHost}/api/v1/ws`;
      
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setWsConnected(true);
        retryDelay = 2000; // Reset backoff on success
        console.log('Connected to AgentDeepDive WebSocket server at', wsUrl);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          const { event_type, data } = message;

          if (event_type === 'dag_update') {
            pendingUpdates.current.dag_updates.push(data);
          } else if (event_type === 'approval_update') {
            pendingUpdates.current.approval_updates.push(data);
          } else if (event_type === 'recovery') {
            pendingUpdates.current.recovery_updates.push(data);
          }
        } catch (err) {
          console.error('WebSocket message parsing error', err);
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        console.log(`AgentDeepDive WebSocket disconnected. Reconnecting in ${retryDelay / 1000}s...`);
        setTimeout(connectWS, retryDelay);
        retryDelay = Math.min(30000, retryDelay * 1.5); // Exponential backoff up to 30s
      };
    };

    connectWS();
    return () => {
      if (ws) ws.close();
    };
  }, []);

  // Interval loop to batch update React states every 100ms
  useEffect(() => {
    const batchInterval = setInterval(() => {
      const { dag_updates, approval_updates, recovery_updates } = pendingUpdates.current;
      if (dag_updates.length === 0 && approval_updates.length === 0 && recovery_updates.length === 0) {
        return;
      }

      // Batch process dag_updates
      if (dag_updates.length > 0) {
        setHasProjectStarted(true);
        setNodes((prevNodes) => {
          let updatedNodes = [...prevNodes];
          dag_updates.forEach((data) => {
            if (data.node_id) {
              updatedNodes = updatedNodes.map((n) => {
                if (n.id === data.node_id || n.data.name === data.node_id) {
                  return {
                    ...n,
                    data: {
                      ...n.data,
                      color: data.color || 'ready',
                      roleId: data.role_id || n.data.roleId || '',
                      progress: ['success', 'green'].includes(data.color) ? 100 : ['running', 'yellow'].includes(data.color) ? 50 : 0,
                    },
                  };
                }
                return n;
              });
            }
          });
          return updatedNodes;
        });

        const latestDagStatusUpdate = [...dag_updates].reverse().find(u => u.dag_status);
        if (latestDagStatusUpdate) {
          const status = latestDagStatusUpdate.dag_status;
          setTaskLauncherStatus(`DAG Status: ${status.toUpperCase()}`);
          if (status === 'running') {
            setIsExecutingRealTask(true);
          } else if (['completed', 'completed_with_errors', 'failed'].includes(status)) {
            setIsExecutingRealTask(false);
          }
        }

        setCotLogs((prev) => {
          const newLogs = dag_updates.map((data) => {
            const timeStr = new Date(data.timestamp || Date.now()).toLocaleTimeString();
            return {
              id: Math.random().toString(),
              nodeId: data.node_id || undefined,
              type: (data.color === 'running' ? 'thought' : 'observation') as 'thought' | 'observation',
              text: data.node_id
                ? `DAG ${data.dag_id} Node: [${data.node_id}] transitioned status to ${data.color || 'idle'}.`
                : `DAG ${data.dag_id} overall status transitioned to ${data.dag_status || 'idle'}.`,
              time: timeStr,
            };
          });
          return [...prev, ...newLogs];
        });

        pendingUpdates.current.dag_updates = [];
      }

      // Batch process approval_updates
      if (approval_updates.length > 0) {
        setApprovals((prev) => {
          let updatedApprovals = [...prev];
          approval_updates.forEach((data) => {
            const existingIdx = updatedApprovals.findIndex((a) => a.approval_id === data.approval_id);
            if (existingIdx !== -1) {
              updatedApprovals[existingIdx] = data;
            } else {
              updatedApprovals.push(data);
            }
          });
          return updatedApprovals;
        });

        const latestPending = [...approval_updates].reverse().find(u => u.status === 'pending');
        if (latestPending) {
          setActiveApprovalId(latestPending.approval_id);
          setEditableArgs(JSON.stringify(latestPending.arguments, null, 2));
        }

        pendingUpdates.current.approval_updates = [];
      }

      // Batch process recovery_updates
      if (recovery_updates.length > 0) {
        setSentinelState('recovery');
        const timeStr = new Date().toLocaleTimeString();
        setCotLogs((prev) => {
          const newLogs = recovery_updates.map((data) => ({
            id: Math.random().toString(),
            type: 'tool' as 'tool',
            text: `⚠️ Sentinel Daemon detected stale Agent. Triggered Recovery Flow for agent ID ${data.agent_id}. Concurrency slots freed.`,
            time: timeStr,
          }));
          return [...prev, ...newLogs];
        });
        setTimeout(() => setSentinelState('active'), 4000);

        pendingUpdates.current.recovery_updates = [];
      }
    }, 100);

    return () => clearInterval(batchInterval);
  }, []);

  // Handle local simulation of execution loop (if backend is not active)
  const triggerSimulation = () => {
    if (isSimulating) return;
    setIsSimulating(true);
    setHasProjectStarted(true);
    setNodes(initialNodes.map(n => ({ ...n, data: { ...n.data, color: 'ready', progress: 0, tokenCost: 0 } })));
    setEdges(initialEdges);

    let step = 0;
    const interval = setInterval(() => {
      setNodes((prevNodes) => {
        const nextNodes = [...prevNodes];
        const updateNode = (id: string, updates: any) => {
          const idx = nextNodes.findIndex(n => n.id === id);
          if (idx !== -1) {
            nextNodes[idx] = {
              ...nextNodes[idx],
              data: { ...nextNodes[idx].data, ...updates }
            };
          }
        };

        if (step === 0) {
          updateNode('1', { color: 'running', progress: 40, tokenCost: 500 });
          setCotLogs(prev => [...prev, { id: Date.now().toString(), nodeId: '1', type: 'thought', text: 'Decomposing complex instructions via topological split...', time: new Date().toLocaleTimeString() }]);
        } else if (step === 1) {
          updateNode('1', { color: 'success', progress: 100, tokenCost: 1200 });
          updateNode('2', { color: 'running', progress: 30, tokenCost: 800 });
          updateNode('3', { color: 'running', progress: 20, tokenCost: 1500 });
          setCotLogs(prev => [...prev, { id: Date.now().toString(), nodeId: '2', type: 'thought', text: 'Parallel execution branch started: code analyzer & patch generator.', time: new Date().toLocaleTimeString() }]);
        } else if (step === 2) {
          updateNode('2', { color: 'success', progress: 100, tokenCost: 2400 });
          updateNode('3', { color: 'running', progress: 80, tokenCost: 4500 });
          updateNode('4', { color: 'queued', progress: 0 });
          setLocalTokenCost(prev => prev + 3000);
          setTotalCostUSD(prev => prev + 0.05);
        } else if (step === 3) {
          updateNode('3', { color: 'success', progress: 100, tokenCost: 8900 });
          updateNode('5', { color: 'suspended', progress: 0 });
          updateNode('4', { color: 'running', progress: 50, tokenCost: 1200 });
          setCotLogs(prev => [...prev, { id: Date.now().toString(), nodeId: '4', type: 'tool', text: 'Executing Docker Sandbox build check...', time: new Date().toLocaleTimeString() }]);
        } else if (step === 4) {
          updateNode('4', { color: 'success', progress: 100, tokenCost: 2100 });
          setCotLogs(prev => [...prev, { id: Date.now().toString(), nodeId: '5', type: 'thought', text: 'Docker build verification succeeded. Awaiting user approval to commit changes...', time: new Date().toLocaleTimeString() }]);
          
           const approvalId = 'appr-demo-' + Math.floor(Math.random()*100);
          setApprovals([{
            approval_id: approvalId,
            task_id: 'demo-dag:node-5',
            agent_id: 'skill:human-gate',
            tool_name: 'git_commit_push',
            arguments: { branch: 'main', commit_message: 'feat: apply local docker verified patches' },
            priority: 95,
            status: 'pending',
            task_description: 'Apply local docker verified patches to git repository',
            project_name: 'demo-project',
            workspace_path: '/path/to/demo-project'
          }]);
          setActiveApprovalId(approvalId);
        }
        return nextNodes;
      });

      step += 1;
      if (step > 4) {
        clearInterval(interval);
        setIsSimulating(false);
      }
    }, 4000);
  };

  // Mock sentinel crash/recovery trigger
  const triggerSentinelCrash = () => {
    setSentinelState('recovery');
    setConcurrencyActive(2);
    setCotLogs(prev => [
      ...prev,
      {
        id: Math.random().toString(),
        type: 'tool',
        text: '🚨 [Sentinel Alert] Agent ID agent-398a is unresponsive (Heartbeat missed). Initiating recovery sweeping...',
        time: new Date().toLocaleTimeString()
      }
    ]);

    setTimeout(() => {
      setSentinelState('active');
      setConcurrencyActive(3);
      setCotLogs(prev => [
        ...prev,
        {
          id: Math.random().toString(),
          type: 'observation',
          text: '✅ Sentinel successfully released Redis file-locks and reclaimed active concurrency slot. Agent status reset to idle.',
          time: new Date().toLocaleTimeString()
        }
      ]);
    }, 3000);
  };

  const handleResolveApproval = (status: 'approved' | 'rejected') => {
    if (!activeApprovalId) return;

    // Local resolution handling
    setApprovals(prev =>
      prev.map(a => (a.approval_id === activeApprovalId ? { ...a, status } : a))
    );

    setCotLogs(prev => [
      ...prev,
      {
        id: Math.random().toString(),
        type: 'observation',
        text: `Approval [${activeApprovalId}] resolved as: ${status.toUpperCase()}. Resuming downstream execution...`,
        time: new Date().toLocaleTimeString()
      }
    ]);

    // Transition suspended nodes to yellow/green in mock demo
    setNodes(prev =>
      prev.map(n => {
        if (n.data.color === 'suspended') {
          return {
            ...n,
            data: {
              ...n.data,
              color: status === 'approved' ? 'success' : 'failed',
              progress: 100
            }
          };
        }
        if (n.id === '6' && status === 'approved') {
          return {
            ...n,
            data: {
              ...n.data,
              color: 'success',
              progress: 100,
              tokenCost: 600
            }
          };
        }
        return n;
      })
    );

    // If backend is connected, notify HTTP API
    if (wsConnected) {
      let parsedArgs = null;
      if (status === 'approved' && editableArgs) {
        try {
          parsedArgs = JSON.parse(editableArgs);
        } catch (e) {
          console.error('Invalid arguments JSON:', e);
        }
      }

      fetch(`${API_BASE}/api/v1/approvals/${activeApprovalId}/${status}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ arguments: parsedArgs })
      }).catch(err => console.log('HTTP API Approval trigger failed:', err));
    }

    setActiveApprovalId(null);
  };

  const currentActiveApproval = useMemo(() => {
    return approvals.find(a => a.approval_id === activeApprovalId);
  }, [approvals, activeApprovalId]);

  return (
    <div style={{
      display: 'grid',
      gridTemplateRows: '70px 1fr',
      height: '100vh',
      width: '100vw',
      backgroundColor: 'hsl(var(--bg-dark))',
      color: '#fff',
      padding: '12px'
    }}>
      
      <CockpitHeader
        wsConnected={wsConnected}
        activeWorkspace={activeWorkspace}
        workspaces={workspaces}
        handleSwitchWorkspace={handleSwitchWorkspace}
        setIsWorkspaceDialogOpen={setIsWorkspaceDialogOpen}
        setIsMarketOpen={setIsMarketOpen}
        fetchMarketSkills={fetchMarketSkills}
        setIsDiagnosticsOpen={setIsDiagnosticsOpen}
        setIsOpaDialogOpen={setIsOpaDialogOpen}
        setIsCeleryStatsOpen={setIsCeleryStatsOpen}
        autoApprove={autoApprove}
        handleToggleAutoApprove={handleToggleAutoApprove}
        autoApproveL4={autoApproveL4}
        handleToggleAutoApproveL4={handleToggleAutoApproveL4}
        sentinelState={sentinelState}
        totalCostUSD={totalCostUSD}
      />


      {/* ── MAIN WORKSPACE PANEL ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '300px 1fr 350px',
        gap: '12px',
        overflow: 'hidden',
        height: '100%',
        minHeight: 0
      }}>
        
        <MissionControl
          concurrencyActive={concurrencyActive}
          isSimulating={isSimulating}
          triggerSimulation={triggerSimulation}
          triggerSentinelCrash={triggerSentinelCrash}
          taskPrompt={taskPrompt}
          setTaskPrompt={setTaskPrompt}
          isExecutingRealTask={isExecutingRealTask}
          handleCancelTask={handleCancelTask}
          handleLaunchTask={handleLaunchTask}
          handleRestoreTask={handleRestoreTask}
          taskLauncherStatus={taskLauncherStatus}
          localTokenCost={localTokenCost}
          cloudTokenCost={cloudTokenCost}
          availableDags={availableDags}
          activeDagId={activeDagId}
          loadDAG={loadDAG}
          activeWorkspace={activeWorkspace}
        />


        {/* ── CENTER PANEL: DAG ORCHESTRATION CANVAS ── */}
        <main className="glass-panel" style={{
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          height: '100%',
          minHeight: 0
        }}>
          <div style={{
            position: 'absolute',
            top: 15,
            left: 20,
            zIndex: 10,
            background: 'rgba(10, 13, 22, 0.85)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            padding: '4px',
            borderRadius: '20px',
            fontSize: '11px',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}>
            <button
              onClick={() => {
                setViewMode('task');
                setSelectedNodeId(null);
              }}
              style={{
                background: viewMode === 'task' ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                border: viewMode === 'task' ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent',
                color: viewMode === 'task' ? '#60a5fa' : 'rgba(255,255,255,0.6)',
                borderRadius: '16px',
                padding: '4px 12px',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '10px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                outline: 'none',
                transition: 'all 0.2s'
              }}
            >
              <Cpu size={11} />
              Task DAG
            </button>
            <button
              onClick={() => {
                setViewMode('blueprint');
                setSelectedNodeId(null);
              }}
              style={{
                background: viewMode === 'blueprint' ? 'rgba(168, 85, 247, 0.2)' : 'transparent',
                border: viewMode === 'blueprint' ? '1px solid rgba(168, 85, 247, 0.4)' : '1px solid transparent',
                color: viewMode === 'blueprint' ? '#c084fc' : 'rgba(255,255,255,0.6)',
                borderRadius: '16px',
                padding: '4px 12px',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '10px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                outline: 'none',
                transition: 'all 0.2s'
              }}
            >
              <Layers size={11} />
              Architecture Blueprint
            </button>
          </div>

          <div style={{ flex: 1, width: '100%', height: '100%', minHeight: 0, position: 'relative' }}>
            <ReactFlow
              nodes={viewMode === 'blueprint' ? bpNodes : displayNodes}
              edges={viewMode === 'blueprint' ? bpEdges : displayEdges}
              onNodesChange={viewMode === 'blueprint' ? onBpNodesChange : onNodesChange}
              onEdgesChange={viewMode === 'blueprint' ? onBpEdgesChange : onEdgesChange}
              nodeTypes={nodeTypes}
              onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
              onPaneClick={() => setSelectedNodeId(null)}
              fitView
              style={{ width: '100%', height: '100%' }}
            >
              <Background color="#334155" gap={16} size={1} />
              <Controls />
            </ReactFlow>
          </div>
        </main>

        {/* ── RIGHT PANEL: CoT LOGS & APPROVAL DRAWER ── */}
        <aside className="glass-panel" style={{
          padding: '16px',
          display: 'grid',
          gridTemplateRows: '1fr 1fr',
          gap: '12px',
          overflow: 'hidden',
          height: '100%',
          minHeight: 0
        }}>
          {/* Real-time CoT Telemetry */}
          <LogTelemetry
            selectedNode={selectedNode}
            selectedNodeId={selectedNodeId}
            setSelectedNodeId={setSelectedNodeId}
            filteredLogs={filteredLogs}
          />

          {/* Interactive Approvals Panel */}
          <ApprovalGate
            currentActiveApproval={currentActiveApproval || null}
            editableArgs={editableArgs}
            setEditableArgs={setEditableArgs}
            handleResolveApproval={handleResolveApproval}
          />
        </aside>



      </div>

      {/* Workspace Selection / Initialization Modal */}
      <WorkspaceDialog
        isOpen={isWorkspaceDialogOpen}
        activeWorkspace={activeWorkspace}
        newWorkspacePath={newWorkspacePath}
        setNewWorkspacePath={setNewWorkspacePath}
        handleCreateWorkspace={handleCreateWorkspace}
        onClose={() => setIsWorkspaceDialogOpen(false)}
      />


      <SkillMarketDialog
        isOpen={isMarketOpen}
        onClose={() => setIsMarketOpen(false)}
        marketTab={marketTab}
        setMarketTab={setMarketTab}
        marketSearchQuery={marketSearchQuery}
        setMarketSearchQuery={setMarketSearchQuery}
        fetchMarketSkills={fetchMarketSkills}
        marketSkills={marketSkills}
        installedSkills={installedSkills}
        fetchInstalledSkills={fetchInstalledSkills}
        handleToggleSkill={handleToggleSkill}
        handleDeleteSkill={handleDeleteSkill}
        installingSkillId={installingSkillId}
        setInstallingSkillId={setInstallingSkillId}
        installWorkspacePath={installWorkspacePath}
        setInstallWorkspacePath={setInstallWorkspacePath}
        installScope={installScope}
        setInstallScope={setInstallScope}
        installStatus={installStatus}
        setInstallStatus={setInstallStatus}
        handleInstallSkill={handleInstallSkill}
        previewContent={previewContent}
        setPreviewContent={setPreviewContent}
        previewResult={previewResult}
        previewLoading={previewLoading}
        previewError={previewError}
        handlePreviewSkill={handlePreviewSkill}
        handleInstallPreviewedSkill={handleInstallPreviewedSkill}
        activeWorkspace={activeWorkspace}
        wsConnected={wsConnected}
      />


      {/* Webhook Diagnostics Dialog */}
      <DiagnosticsDialog
        isOpen={isDiagnosticsOpen}
        onClose={() => setIsDiagnosticsOpen(false)}
        diagnosingChannel={diagnosingChannel}
        setDiagnosingChannel={setDiagnosingChannel}
        diagnosticLoading={diagnosticLoading}
        diagnosticError={diagnosticError}
        diagnosticResult={diagnosticResult}
        handleTestWebhookConnection={handleTestWebhookConnection}
      />

      {/* Celery stats monitoring dialog */}
      <CeleryStatsDialog
        isOpen={isCeleryStatsOpen}
        onClose={() => setIsCeleryStatsOpen(false)}
        apiBase={API_BASE}
      />

      {/* OPA Rego Rules Dialog */}
      <OpaPolicyDialog
        isOpen={isOpaDialogOpen}
        onClose={() => setIsOpaDialogOpen(false)}
        activeWorkspace={activeWorkspace}
        wsConnected={wsConnected}
      />

      {/* Human-in-the-Loop Approval Modal Overlay */}
      <ApprovalDialog
        isOpen={activeApprovalId !== null}
        approval={currentActiveApproval || null}
        editableArgs={editableArgs}
        setEditableArgs={setEditableArgs}
        handleResolveApproval={handleResolveApproval}
      />

    </div>
  );
}
