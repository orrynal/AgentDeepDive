import React, { useState, useEffect, useRef } from 'react';
import { Activity, Play, CheckCircle, AlertTriangle, Clock, RefreshCw } from 'lucide-react';

interface TaskStatPoint {
  time: string;
  latency: number;
  runs: number;
}

interface CeleryStatsDialogProps {
  isOpen: boolean;
  onClose: () => void;
  apiBase: string;
}

export const CeleryStatsDialog: React.FC<CeleryStatsDialogProps> = ({
  isOpen,
  onClose,
  apiBase,
}) => {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [history, setHistory] = useState<{ [taskName: string]: TaskStatPoint[] }>({});
  const [activeTab, setActiveTab] = useState<'latency' | 'throughput'>('latency');

  const historyRef = useRef<{ [taskName: string]: TaskStatPoint[] }>({});

  const fetchStats = async () => {
    try {
      const res = await fetch(`${apiBase}/health/celery-stats`);
      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.status === 'ok' && data.stats) {
        setStats(data.stats);
        
        // Update history
        const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const newHistory = { ...historyRef.current };
        
        Object.entries(data.stats).forEach(([taskName, taskData]: [string, any]) => {
          const taskHistory = newHistory[taskName] ? [...newHistory[taskName]] : [];
          taskHistory.push({
            time: nowStr,
            latency: taskData.avg_duration_ms || 0,
            runs: taskData.total_runs || 0,
          });
          
          // Keep last 15 points
          if (taskHistory.length > 15) {
            taskHistory.shift();
          }
          newHistory[taskName] = taskHistory;
        });

        historyRef.current = newHistory;
        setHistory(newHistory);
        setError(null);

        // Auto select first task if none selected
        const taskNames = Object.keys(data.stats);
        if (taskNames.length > 0 && !selectedTask) {
          setSelectedTask(taskNames[0]);
        }
      }
    } catch (err: any) {
      console.error('Failed to fetch celery stats', err);
      setError(err.message || 'Unknown network error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;

    setLoading(true);
    fetchStats();

    const interval = setInterval(() => {
      fetchStats();
    }, 3000);

    return () => clearInterval(interval);
  }, [isOpen, apiBase]);

  if (!isOpen) return null;

  const taskNames = stats ? Object.keys(stats) : [];
  const currentTaskData = selectedTask && stats ? stats[selectedTask] : null;
  const currentTaskHistory = selectedTask ? history[selectedTask] || [] : [];

  // SVG Chart Helper Coordinates calculation
  const chartWidth = 500;
  const chartHeight = 180;
  const padding = 30;

  const renderSVGChart = () => {
    if (currentTaskHistory.length < 2) {
      return (
        <div style={{
          height: `${chartHeight}px`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'rgba(255, 255, 255, 0.3)',
          fontSize: '12px',
          border: '1px dashed rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          background: 'rgba(0,0,0,0.1)'
        }}>
          Waiting for more performance metrics to stream...
        </div>
      );
    }

    const values = currentTaskHistory.map(p => activeTab === 'latency' ? p.latency : p.runs);
    const maxVal = Math.max(...values, activeTab === 'latency' ? 50 : 5) * 1.1; // Add 10% headroom
    const minVal = 0;
    const range = maxVal - minVal;

    const points = currentTaskHistory.map((p, index) => {
      const x = padding + (index * (chartWidth - padding * 2)) / (currentTaskHistory.length - 1);
      const val = activeTab === 'latency' ? p.latency : p.runs;
      const y = chartHeight - padding - ((val - minVal) / range) * (chartHeight - padding * 2);
      return { x, y, label: p.time, value: val };
    });

    const linePath = `M ${points.map(p => `${p.x} ${p.y}`).join(' L ')}`;
    const areaPath = `${linePath} L ${points[points.length - 1].x} ${chartHeight - padding} L ${points[0].x} ${chartHeight - padding} Z`;

    return (
      <div style={{ position: 'relative' }}>
        <svg width="100%" height={chartHeight} viewBox={`0 0 ${chartWidth} ${chartHeight}`} style={{ overflow: 'visible' }}>
          <defs>
            <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={activeTab === 'latency' ? '#c084fc' : '#38bdf8'} stopOpacity="0.4" />
              <stop offset="100%" stopColor={activeTab === 'latency' ? '#c084fc' : '#38bdf8'} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio, i) => {
            const y = padding + ratio * (chartHeight - padding * 2);
            const val = maxVal - ratio * range;
            return (
              <g key={i}>
                <line
                  x1={padding}
                  y1={y}
                  x2={chartWidth - padding}
                  y2={y}
                  stroke="rgba(255, 255, 255, 0.05)"
                  strokeDasharray="4 4"
                />
                <text
                  x={padding - 5}
                  y={y + 4}
                  fill="rgba(255, 255, 255, 0.4)"
                  fontSize="9px"
                  textAnchor="end"
                  fontFamily="monospace"
                >
                  {activeTab === 'latency' ? `${val.toFixed(1)}ms` : Math.round(val)}
                </text>
              </g>
            );
          })}

          {/* X axis labels */}
          {points.map((p, i) => {
            if (i % 3 !== 0 && i !== points.length - 1) return null;
            return (
              <text
                key={i}
                x={p.x}
                y={chartHeight - 8}
                fill="rgba(255, 255, 255, 0.4)"
                fontSize="8px"
                textAnchor="middle"
                fontFamily="monospace"
              >
                {p.label}
              </text>
            );
          })}

          {/* Filled Area */}
          <path d={areaPath} fill="url(#chartGradient)" />

          {/* Line Path */}
          <path
            d={linePath}
            fill="none"
            stroke={activeTab === 'latency' ? '#c084fc' : '#38bdf8'}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data Points */}
          {points.map((p, i) => (
            <g key={i} className="chart-dot-group">
              <circle
                cx={p.x}
                cy={p.y}
                r="4"
                fill={activeTab === 'latency' ? '#c084fc' : '#38bdf8'}
                stroke="#0f172a"
                strokeWidth="1.5"
              />
              <circle
                cx={p.x}
                cy={p.y}
                r="8"
                fill={activeTab === 'latency' ? '#c084fc' : '#38bdf8'}
                opacity="0"
                style={{ cursor: 'pointer' }}
              >
                <title>{`${p.label}: ${p.value.toFixed(1)}${activeTab === 'latency' ? 'ms' : ' runs'}`}</title>
              </circle>
            </g>
          ))}
        </svg>
      </div>
    );
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: '100vw',
      height: '100vh',
      backgroundColor: 'rgba(0,0,0,0.75)',
      backdropFilter: 'blur(12px)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '850px',
        height: '560px',
        padding: '24px',
        borderRadius: '16px',
        border: '1px solid rgba(255,255,255,0.08)',
        boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
        background: 'rgba(15, 23, 42, 0.96)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        boxSizing: 'border-box'
      }}>
        {/* Title Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '12px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '18px', color: '#fff', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity style={{ color: '#c084fc' }} size={20} />
              ⚡ Celery Scheduled & Async Task Monitor
            </h3>
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
              Real-time asynchronous worker queues execution metrics, latency trends, and failure diagnostic feeds.
            </span>
          </div>
          <button 
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'rgba(255,255,255,0.6)',
              fontSize: '22px',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            &times;
          </button>
        </div>

        {loading ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
            <RefreshCw className="animate-spin" style={{ color: '#c084fc' }} size={28} />
            <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>Loading worker queues metrics...</span>
          </div>
        ) : error ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
            <AlertTriangle style={{ color: '#ef4444' }} size={32} />
            <span style={{ fontSize: '13px', color: '#ef4444', fontWeight: 600 }}>Failed to sync Celery stats</span>
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', fontFamily: 'monospace' }}>{error}</span>
          </div>
        ) : taskNames.length === 0 ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
            <Clock style={{ color: 'rgba(255,255,255,0.3)' }} size={32} />
            <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}>No background tasks recorded yet</span>
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', textAlign: 'center', maxWidth: '300px' }}>
              Run some scheduled workflows or tasks to start capturing runtime metrics and performance parameters.
            </span>
          </div>
        ) : (
          <div style={{ display: 'flex', flex: 1, gap: '20px', minHeight: 0 }}>
            {/* Sidebar list of tasks */}
            <div style={{
              width: '240px',
              borderRight: '1px solid rgba(255,255,255,0.06)',
              paddingRight: '16px',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px'
            }}>
              <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', fontWeight: 700, textTransform: 'uppercase', marginBottom: '4px' }}>
                Active Worker Tasks
              </span>
              {taskNames.map((name) => {
                const isActive = selectedTask === name;
                const taskData = stats[name];
                return (
                  <div
                    key={name}
                    onClick={() => setSelectedTask(name)}
                    style={{
                      background: isActive ? 'rgba(192, 132, 252, 0.12)' : 'rgba(255,255,255,0.02)',
                      border: isActive ? '1px solid rgba(192, 132, 252, 0.4)' : '1px solid rgba(255,255,255,0.04)',
                      padding: '10px 12px',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      transition: 'all 0.2s'
                    }}
                  >
                    <span style={{ fontSize: '12px', fontWeight: 600, color: isActive ? '#c084fc' : '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={name}>
                      {name.split('.').pop() || name}
                    </span>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: 'rgba(255,255,255,0.4)' }}>
                      <span>Runs: {taskData.total_runs}</span>
                      <span style={{ color: taskData.failure_runs > 0 ? '#ef4444' : '#22c55e' }}>
                        Failures: {taskData.failure_runs}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Main Content Area */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '16px', minHeight: 0, overflowY: 'auto' }}>
              {/* Three Stat Cards */}
              {currentTaskData && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px' }}>
                  <div className="glass-card" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '2px', background: 'rgba(255,255,255,0.02)' }}>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase' }}>Run Count</span>
                    <strong style={{ fontSize: '18px', color: '#fff' }}>{currentTaskData.total_runs} runs</strong>
                    <span style={{ fontSize: '9px', color: '#22c55e' }}>
                      Success rate: {currentTaskData.total_runs > 0 ? Math.round(((currentTaskData.total_runs - currentTaskData.failure_runs) / currentTaskData.total_runs) * 100) : 100}%
                    </span>
                  </div>

                  <div className="glass-card" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '2px', background: 'rgba(255,255,255,0.02)' }}>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase' }}>Average Latency</span>
                    <strong style={{ fontSize: '18px', color: '#c084fc' }}>{currentTaskData.avg_duration_ms ? currentTaskData.avg_duration_ms.toFixed(1) : '0.0'} ms</strong>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)' }}>
                      Last run duration: {currentTaskData.last_duration_ms ? currentTaskData.last_duration_ms.toFixed(1) : '0.0'} ms
                    </span>
                  </div>

                  <div className="glass-card" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '2px', background: 'rgba(255,255,255,0.02)' }}>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase' }}>Last Status</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                      {currentTaskData.last_run_status === 'SUCCESS' ? (
                        <CheckCircle size={14} style={{ color: '#22c55e' }} />
                      ) : currentTaskData.last_run_status === 'FAILURE' ? (
                        <AlertTriangle size={14} style={{ color: '#ef4444' }} />
                      ) : (
                        <Play size={14} style={{ color: '#eab308' }} />
                      )}
                      <strong style={{
                        fontSize: '14px',
                        color: currentTaskData.last_run_status === 'SUCCESS' ? '#22c55e' :
                               currentTaskData.last_run_status === 'FAILURE' ? '#ef4444' : '#eab308'
                      }}>
                        {currentTaskData.last_run_status || 'UNKNOWN'}
                      </strong>
                    </div>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      Last run: {currentTaskData.last_run_time ? new Date(currentTaskData.last_run_time).toLocaleTimeString() : 'N/A'}
                    </span>
                  </div>
                </div>
              )}

              {/* Time-Series Curve Chart Area */}
              <div className="glass-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', background: 'rgba(0,0,0,0.2)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', fontWeight: 600, textTransform: 'uppercase' }}>
                    📈 Real-time Stream Analytics
                  </span>
                  
                  {/* Chart Tabs */}
                  <div style={{ display: 'flex', background: 'rgba(255,255,255,0.04)', padding: '2px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <button
                      onClick={() => setActiveTab('latency')}
                      style={{
                        background: activeTab === 'latency' ? 'rgba(192, 132, 252, 0.15)' : 'transparent',
                        color: activeTab === 'latency' ? '#c084fc' : 'rgba(255,255,255,0.5)',
                        border: 'none',
                        padding: '4px 10px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                      }}
                    >
                      Latency (ms)
                    </button>
                    <button
                      onClick={() => setActiveTab('throughput')}
                      style={{
                        background: activeTab === 'throughput' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                        color: activeTab === 'throughput' ? '#38bdf8' : 'rgba(255,255,255,0.5)',
                        border: 'none',
                        padding: '4px 10px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                      }}
                    >
                      Run Throughput
                    </button>
                  </div>
                </div>

                {renderSVGChart()}
              </div>

              {/* Exception diagnostic display */}
              {currentTaskData && currentTaskData.last_run_status === 'FAILURE' && currentTaskData.last_error && (
                <div style={{
                  background: 'rgba(239, 68, 68, 0.05)',
                  border: '1px solid rgba(239, 68, 68, 0.15)',
                  borderRadius: '8px',
                  padding: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px'
                }}>
                  <div style={{ fontSize: '11px', color: '#ef4444', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <AlertTriangle size={12} />
                    Last Run Execution Failure Traceback
                  </div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.85)', fontWeight: 600 }}>
                    Error: {currentTaskData.last_error}
                  </div>
                  {currentTaskData.last_error_traceback && (
                    <pre style={{
                      margin: 0,
                      padding: '8px',
                      background: 'rgba(0,0,0,0.3)',
                      borderRadius: '4px',
                      fontSize: '10px',
                      fontFamily: 'monospace',
                      color: 'rgba(255,255,255,0.6)',
                      overflowX: 'auto',
                      maxHeight: '80px',
                      whiteSpace: 'pre-wrap'
                    }}>
                      {currentTaskData.last_error_traceback}
                    </pre>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '12px' }}>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid rgba(255,255,255,0.15)',
              color: '#fff',
              borderRadius: '8px',
              padding: '8px 16px',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 600,
              transition: 'all 0.2s'
            }}
          >
            Close Panel
          </button>
        </div>
      </div>
    </div>
  );
};
