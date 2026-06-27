import { useState, useCallback } from 'react';
import { API_BASE } from '../App';
import { MarkerType } from '@xyflow/react';

/**
 * Custom hook to encapsulate all Workspace management logic.
 * Extracted from App.tsx to improve modularity and reduce main file size.
 */
export function useWorkspaceManager(
  setNodes: React.Dispatch<React.SetStateAction<any[]>>,
  setEdges: React.Dispatch<React.SetStateAction<any[]>>,
  setHasProjectStarted: React.Dispatch<React.SetStateAction<boolean>>,
  setTaskLauncherStatus: React.Dispatch<React.SetStateAction<string>>,
  setActiveDagId: React.Dispatch<React.SetStateAction<string | null>>,
  setIsExecutingRealTask: React.Dispatch<React.SetStateAction<boolean>>,
  layoutNodes: (backendNodes: Array<any>, backendEdges: Array<any>) => any[],
) {
  const [activeWorkspace, setActiveWorkspace] = useState<string>('');
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [isWorkspaceDialogOpen, setIsWorkspaceDialogOpen] = useState<boolean>(false);
  const [newWorkspacePath, setNewWorkspacePath] = useState<string>('');

  const [availableDags, setAvailableDags] = useState<any[]>([]);

  const loadDAG = useCallback(async (dagId: string) => {
    try {
      setActiveDagId(dagId);
      const detailRes = await fetch(`${API_BASE}/api/v1/dags/${dagId}`);
      if (!detailRes.ok) return;
      const dagDetail = await detailRes.json();
      
      // Convert to React Flow nodes/edges
      const backendNodes = dagDetail.nodes || [];
      const backendEdges: any[] = [];
      backendNodes.forEach((n: any) => {
        const deps = n.dependencies || [];
        deps.forEach((dep: string) => {
          backendEdges.push({ from: dep, to: n.node_id });
        });
      });
      
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
      setHasProjectStarted(true);
      setTaskLauncherStatus(`Loaded task state: ${dagDetail.name || dagDetail.dag_id} (${dagDetail.status})`);
      
      if (dagDetail.status === 'running') {
        setIsExecutingRealTask(true);
      } else {
        setIsExecutingRealTask(false);
      }
    } catch (err) {
      console.error('Failed to load DAG details:', err);
    }
  }, [setNodes, setEdges, setHasProjectStarted, setTaskLauncherStatus, setActiveDagId, setIsExecutingRealTask, layoutNodes]);

  const restoreActiveDAG = useCallback(async () => {
    try {
      const listRes = await fetch(`${API_BASE}/api/v1/dags`);
      if (!listRes.ok) return;
      const dags = await listRes.json();
      if (dags.length === 0) {
        setAvailableDags([]);
        setNodes([]);
        setEdges([]);
        setHasProjectStarted(false);
        setTaskLauncherStatus('Workspace is empty. Ready for new task.');
        return;
      }
      
      // Find the latest DAG, prioritizing non-test DAGs
      const sortedDags = [...dags].sort((a: any, b: any) => {
        const aIsTest = (a.name || '').toLowerCase().includes('test') || a.dag_id.includes('test') || a.dag_id.includes('n8n');
        const bIsTest = (b.name || '').toLowerCase().includes('test') || b.dag_id.includes('test') || b.dag_id.includes('n8n');
        if (aIsTest && !bIsTest) return 1;
        if (!aIsTest && bIsTest) return -1;
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
      setAvailableDags(sortedDags);
      const latestDagInfo = sortedDags[0];
      await loadDAG(latestDagInfo.dag_id);
    } catch (err) {
      console.error('Failed to restore active DAG state:', err);
    }
  }, [loadDAG, setNodes, setEdges, setHasProjectStarted, setTaskLauncherStatus]);

  const handleSwitchWorkspace = useCallback(async (path: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/workspaces/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      if (res.ok) {
        const data = await res.json();
        setActiveWorkspace(data.active_workspace);
        setWorkspaces(data.workspaces);
        setTimeout(() => {
          restoreActiveDAG();
        }, 100);
      }
    } catch (err) {
      console.error('Failed to switch workspace:', err);
    }
  }, [restoreActiveDAG]);

  const handleCreateWorkspace = useCallback(async (path: string) => {
    if (!path.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/workspaces`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      if (res.ok) {
        const data = await res.json();
        setActiveWorkspace(data.active_workspace);
        setWorkspaces(data.workspaces);
        setIsWorkspaceDialogOpen(false);
        setNewWorkspacePath('');
        setNodes([]);
        setEdges([]);
        setHasProjectStarted(false);
        setTaskLauncherStatus('Workspace initialized. Ready for new task.');
      }
    } catch (err) {
      console.error('Failed to create workspace:', err);
    }
  }, [setNodes, setEdges, setHasProjectStarted, setTaskLauncherStatus]);

  const initWorkspaceAndDAG = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/workspaces`);
      if (res.ok) {
        const data = await res.json();
        setActiveWorkspace(data.active_workspace);
        setWorkspaces(data.workspaces);
        if (!data.active_workspace) {
          setIsWorkspaceDialogOpen(true);
        } else {
          restoreActiveDAG();
        }
      }
    } catch (err) {
      console.error('Failed to initialize workspace and DAG:', err);
    }
  }, [restoreActiveDAG]);

  return {
    activeWorkspace, setActiveWorkspace,
    workspaces, setWorkspaces,
    isWorkspaceDialogOpen, setIsWorkspaceDialogOpen,
    newWorkspacePath, setNewWorkspacePath,
    restoreActiveDAG,
    handleSwitchWorkspace,
    handleCreateWorkspace,
    initWorkspaceAndDAG,
    availableDags,
    loadDAG,
  };
}
