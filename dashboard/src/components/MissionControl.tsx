import React, { useMemo } from 'react';
import { Play, Cpu, Terminal, XCircle, RefreshCw } from 'lucide-react';

interface MissionControlProps {
  concurrencyActive: number;
  isSimulating: boolean;
  triggerSimulation: () => void;
  triggerSentinelCrash: () => void;
  taskPrompt: string;
  setTaskPrompt: (prompt: string) => void;
  isExecutingRealTask: boolean;
  handleCancelTask: () => void;
  handleLaunchTask: () => void;
  handleRestoreTask: () => void;
  taskLauncherStatus: string;
  localTokenCost: number;
  cloudTokenCost: number;
  availableDags?: any[];
  activeDagId?: string | null;
  loadDAG?: (dagId: string) => Promise<void>;
  activeWorkspace?: string;
}

export const MissionControl: React.FC<MissionControlProps> = ({
  concurrencyActive,
  isSimulating,
  triggerSimulation,
  triggerSentinelCrash,
  taskPrompt,
  setTaskPrompt,
  isExecutingRealTask,
  handleCancelTask,
  handleLaunchTask,
  handleRestoreTask,
  taskLauncherStatus,
  localTokenCost,
  cloudTokenCost,
  availableDags = [],
  activeDagId = null,
  loadDAG,
  activeWorkspace = '',
}) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [collapsedGroups, setCollapsedGroups] = React.useState<{[key: string]: boolean}>({});
  const [hoveredDag, setHoveredDag] = React.useState<any | null>(null);
  const [hoveredY, setHoveredY] = React.useState(0);

  const currentProject = useMemo(() => {
    if (!activeWorkspace) return '';
    return activeWorkspace.split('/').pop() || '';
  }, [activeWorkspace]);

  // Filter DAGs based on workspace selection rules
  const filteredDags = useMemo(() => {
    if (!activeWorkspace) return availableDags;
    const proj = currentProject.toLowerCase();
    // If parent directory is selected, show all project tasks
    if (proj === 'agentdeepdiveprojects') {
      return availableDags;
    }
    // If a single project workspace is chosen, restrict to only that project
    return availableDags.filter(
      (dag) => (dag.project_name || '').toLowerCase() === proj
    );
  }, [availableDags, currentProject, activeWorkspace]);

  const groupedDags = useMemo(() => {
    const groups: { [key: string]: any[] } = {};
    filteredDags.forEach((dag) => {
      const proj = dag.project_name || 'General';
      if (!groups[proj]) {
        groups[proj] = [];
      }
      groups[proj].push(dag);
    });
    return groups;
  }, [filteredDags]);

  const selectedDag = useMemo(() => {
    return availableDags.find(d => d.dag_id === activeDagId);
  }, [availableDags, activeDagId]);

  return (
    <aside className="glass-panel" style={{
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
      overflowY: 'auto'
    }}>
      <div>
        <h3 style={{ fontSize: '14px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '10px' }}>
          Mission Control
        </h3>
        
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>Engine Running</span>
            <span style={{ color: '#22c55e', fontWeight: 600 }}>TOPOLOGICAL</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>Concurrency Slots</span>
            <span style={{ color: '#00d2ff', fontWeight: 600 }}>{concurrencyActive} / 10 Active</span>
          </div>
          
          <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
            <button 
              onClick={triggerSimulation} 
              disabled={isSimulating || isExecutingRealTask}
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                backgroundColor: (isSimulating || isExecutingRealTask) ? 'rgba(255,255,255,0.05)' : '#22c55e',
                border: 'none',
                color: '#fff',
                padding: '8px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: (isSimulating || isExecutingRealTask) ? 'not-allowed' : 'pointer'
              }}
            >
              <Play size={12} /> {isSimulating ? 'Running...' : 'Run Simulation'}
            </button>
            
            <button 
              onClick={triggerSentinelCrash}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                backgroundColor: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                color: '#ef4444',
                padding: '8px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              <Cpu size={12} /> Crash Agent
            </button>
          </div>
        </div>
      </div>

      <div>
        <h3 style={{ fontSize: '14px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '10px' }}>
          Task Launcher (Live Engine)
        </h3>
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <textarea
            value={taskPrompt}
            onChange={(e) => setTaskPrompt(e.target.value)}
            placeholder="Enter a complex task description (e.g. Design and develop a Python snake game with unit tests)..."
            disabled={isExecutingRealTask}
            style={{
              width: '100%',
              height: '80px',
              backgroundColor: 'rgba(0, 0, 0, 0.3)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              borderRadius: '6px',
              padding: '8px',
              color: '#fff',
              fontSize: '12px',
              resize: 'none',
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
          
          {filteredDags.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px', marginBottom: '4px', position: 'relative' }}>
              <label style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Restore Task Selection
              </label>
              
              {/* Custom Trigger */}
              <div
                onClick={() => !isExecutingRealTask && setIsOpen(!isOpen)}
                style={{
                  width: '100%',
                  backgroundColor: 'rgba(0, 0, 0, 0.4)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '6px',
                  padding: '8px 10px',
                  color: '#fff',
                  fontSize: '11px',
                  outline: 'none',
                  cursor: isExecutingRealTask ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  boxSizing: 'border-box',
                  userSelect: 'none',
                }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: '8px' }}>
                  {selectedDag ? (
                    `${selectedDag.name || selectedDag.dag_id} (${selectedDag.status})`
                  ) : (
                    'Select a task to restore...'
                  )}
                </span>
                <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)' }}>
                  {isOpen ? '▲' : '▼'}
                </span>
              </div>

              {/* Custom Dropdown Options */}
              {isOpen && (
                <div style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  width: '100%',
                  marginTop: '4px',
                  backgroundColor: 'rgba(15, 23, 42, 0.98)',
                  backdropFilter: 'blur(12px)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '8px',
                  boxShadow: '0 10px 30px rgba(0, 0, 0, 0.6)',
                  zIndex: 1000,
                  maxHeight: '280px',
                  overflowY: 'auto',
                }}>
                  {Object.keys(groupedDags).map((projectName) => {
                    const dags = groupedDags[projectName];
                    const isCollapsed = collapsedGroups[projectName];
                    const showHeader = currentProject.toLowerCase() === 'agentdeepdiveprojects';

                    return (
                      <div key={projectName}>
                        {showHeader && (
                          <div
                            onClick={() => {
                              setCollapsedGroups(prev => ({
                                ...prev,
                                [projectName]: !prev[projectName]
                              }));
                            }}
                            style={{
                              padding: '8px 12px',
                              backgroundColor: 'rgba(255, 255, 255, 0.04)',
                              borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                              color: 'rgba(255, 255, 255, 0.6)',
                              fontSize: '10px',
                              fontWeight: 700,
                              textTransform: 'uppercase',
                              letterSpacing: '0.05em',
                              cursor: 'pointer',
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              userSelect: 'none',
                            }}
                          >
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span>{isCollapsed ? '📁' : '📂'}</span>
                              {projectName} ({dags.length})
                            </span>
                            <span>{isCollapsed ? '►' : '▼'}</span>
                          </div>
                        )}

                        {!isCollapsed && (
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            {dags.map((dag: any, index: number) => {
                              const seqNum = String(index + 1).padStart(2, '0');
                              const dateStr = new Date(dag.created_at).toLocaleString('zh-CN', {
                                month: 'numeric',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit'
                              });
                              const isSelected = dag.dag_id === activeDagId;

                              return (
                                <div
                                  key={dag.dag_id}
                                  onClick={() => {
                                    if (loadDAG) loadDAG(dag.dag_id);
                                    setIsOpen(false);
                                  }}
                                  onMouseEnter={(e) => {
                                    setHoveredDag(dag);
                                    const rect = e.currentTarget.getBoundingClientRect();
                                    setHoveredY(rect.top);
                                  }}
                                  onMouseLeave={() => {
                                    setHoveredDag(null);
                                  }}
                                  style={{
                                    padding: '8px 12px',
                                    borderBottom: '1px solid rgba(255, 255, 255, 0.03)',
                                    cursor: 'pointer',
                                    backgroundColor: isSelected ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                                    transition: 'background-color 0.2s',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '2px',
                                  }}
                                >
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span style={{ fontWeight: 600, color: isSelected ? '#60a5fa' : '#fff', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      [{seqNum}] {dag.name || dag.dag_id}
                                    </span>
                                    <span style={{
                                      fontSize: '9px',
                                      padding: '1px 5px',
                                      borderRadius: '4px',
                                      backgroundColor: dag.status === 'success' || dag.status === 'completed' ? 'rgba(34, 197, 94, 0.15)' :
                                                     dag.status === 'failed' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(234, 179, 8, 0.15)',
                                      color: dag.status === 'success' || dag.status === 'completed' ? '#4ade80' :
                                             dag.status === 'failed' ? '#f87171' : '#facc15',
                                      fontWeight: 600,
                                    }}>
                                      {dag.status}
                                    </span>
                                  </div>
                                  <div style={{ fontSize: '9px', color: 'rgba(255, 255, 255, 0.35)' }}>
                                    {dateStr}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Custom Tooltip Panel */}
              {hoveredDag && (
                <div style={{
                  position: 'fixed',
                  left: '320px',
                  top: `${Math.max(20, Math.min(window.innerHeight - 300, hoveredY - 50))}px`,
                  width: '280px',
                  backgroundColor: 'rgba(10, 13, 22, 0.96)',
                  backdropFilter: 'blur(16px)',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  borderRadius: '8px',
                  boxShadow: '0 10px 25px rgba(0,0,0,0.6)',
                  padding: '12px',
                  color: '#fff',
                  zIndex: 9999,
                  pointerEvents: 'none',
                }}>
                  <div style={{ fontWeight: 700, fontSize: '11px', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '6px', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#60a5fa', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Workflow Process</span>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)', textTransform: 'none' }}>
                      {hoveredDag.node_details?.length || 0} steps
                    </span>
                  </div>
                  {hoveredDag.node_details && hoveredDag.node_details.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {hoveredDag.node_details.map((node: any, idx: number) => {
                        let statusSymbol = '⚪';
                        let statusColor = 'rgba(255,255,255,0.4)';
                        if (node.status === 'green' || node.status === 'success') {
                          statusSymbol = '🟢';
                          statusColor = '#4ade80';
                        }
                        if (node.status === 'orange' || node.status === 'running') {
                          statusSymbol = '🟠';
                          statusColor = '#facc15';
                        }
                        if (node.status === 'red' || node.status === 'failed') {
                          statusSymbol = '🔴';
                          statusColor = '#f87171';
                        }
                        return (
                          <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '10px' }}>
                            <span style={{ flexShrink: 0 }}>{statusSymbol}</span>
                            <span style={{ color: statusColor, fontWeight: node.status === 'running' || node.status === 'orange' ? 700 : 500, wordBreak: 'break-word' }}>
                              {idx + 1}. {node.name}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)' }}>
                      No process steps defined for this task.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          
          {isExecutingRealTask ? (
            <button
              onClick={handleCancelTask}
              style={{
                backgroundColor: '#ef4444',
                color: '#fff',
                border: 'none',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                transition: 'background-color 0.2s',
              }}
            >
              <XCircle size={12} /> Stop Execution
            </button>
          ) : (
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={handleLaunchTask}
                disabled={!taskPrompt.trim()}
                style={{
                  flex: 1,
                  backgroundColor: !taskPrompt.trim() ? 'rgba(59, 130, 246, 0.2)' : '#3b82f6',
                  color: '#fff',
                  border: 'none',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: !taskPrompt.trim() ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  transition: 'background-color 0.2s',
                }}
              >
                <Terminal size={12} /> Execute Task
              </button>
              
              <button
                onClick={handleRestoreTask}
                style={{
                  flex: 1,
                  backgroundColor: '#eab308',
                  color: '#fff',
                  border: 'none',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  transition: 'background-color 0.2s',
                }}
              >
                <RefreshCw size={12} /> Restore Task
              </button>
            </div>
          )}

          {taskLauncherStatus && (
            <div style={{
              fontSize: '10px',
              color: taskLauncherStatus.startsWith('Error') ? '#ef4444' : '#22c55e',
              fontFamily: 'var(--font-mono)',
              backgroundColor: 'rgba(0,0,0,0.2)',
              padding: '6px',
              borderRadius: '4px',
              wordBreak: 'break-all',
            }}>
              {taskLauncherStatus}
            </div>
          )}
        </div>
      </div>

      <div>
        <h3 style={{ fontSize: '14px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '10px' }}>
          Token Billing & Flywheel
        </h3>
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>Local Engine (Llama-3-8B)</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{localTokenCost.toLocaleString()} tokens</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>Cloud Engine (GPT-4o)</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{cloudTokenCost.toLocaleString()} tokens</span>
          </div>

          <div style={{ margin: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }} />

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
            <span style={{ color: '#22c55e' }}>Local Prompt Save Ratio</span>
            <span style={{ fontWeight: 600, color: '#22c55e' }}>85.2% Saved</span>
          </div>
        </div>
      </div>

      <div>
        <h3 style={{ fontSize: '14px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '10px' }}>
          Flywheel prompt patcher
        </h3>
        <div className="glass-card" style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)', maxHeight: '200px', overflowY: 'auto' }}>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ padding: '2px 4px', background: 'rgba(34,197,94,0.1)', color: '#22c55e', borderRadius: '4px', fontSize: '9px', fontWeight: 700 }}>DIFF</span>
            <span>Optimized sandbox-executor skill parameters</span>
          </div>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ padding: '2px 4px', background: 'rgba(34,197,94,0.1)', color: '#22c55e', borderRadius: '4px', fontSize: '9px', fontWeight: 700 }}>DIFF</span>
            <span>Self-healed git-committer timeout exception</span>
          </div>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ padding: '2px 4px', background: 'rgba(34,197,94,0.1)', color: '#22c55e', borderRadius: '4px', fontSize: '9px', fontWeight: 700 }}>DIFF</span>
            <span>Injected robust concurrency lock timeouts</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
