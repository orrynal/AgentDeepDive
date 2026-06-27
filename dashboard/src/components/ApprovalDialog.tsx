import React, { useEffect } from 'react';
import { ShieldAlert, CheckCircle, XCircle, Edit, FileText } from 'lucide-react';

interface ApprovalDialogProps {
  isOpen: boolean;
  approval: {
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
  } | null;
  editableArgs: string;
  setEditableArgs: (args: string) => void;
  handleResolveApproval: (status: 'approved' | 'rejected') => void;
}

export const ApprovalDialog: React.FC<ApprovalDialogProps> = ({
  isOpen,
  approval,
  editableArgs,
  setEditableArgs,
  handleResolveApproval,
}) => {
  useEffect(() => {
    if (isOpen && approval) {
      setEditableArgs(JSON.stringify(approval.arguments, null, 2));
    }
  }, [isOpen, approval, setEditableArgs]);

  if (!isOpen || !approval) return null;

  // Format the unified diff if it exists
  const renderDiff = (diffText?: string) => {
    if (!diffText) return null;
    const lines = diffText.split('\n');
    return (
      <div style={{
        backgroundColor: 'rgba(0, 0, 0, 0.4)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '8px',
        padding: '12px',
        maxHeight: '260px',
        overflowY: 'auto',
        fontFamily: 'Consolas, Monaco, "Courier New", monospace',
        fontSize: '11px',
        lineHeight: '1.5',
      }}>
        {lines.map((line, idx) => {
          let color = 'rgba(255, 255, 255, 0.7)';
          let backgroundColor = 'transparent';
          if (line.startsWith('+')) {
            color = '#4ade80';
            backgroundColor = 'rgba(74, 222, 128, 0.08)';
          } else if (line.startsWith('-')) {
            color = '#f87171';
            backgroundColor = 'rgba(248, 113, 113, 0.08)';
          } else if (line.startsWith('@@')) {
            color = '#60a5fa';
            backgroundColor = 'rgba(96, 165, 250, 0.05)';
          }
          return (
            <div 
              key={idx} 
              style={{ 
                color, 
                backgroundColor, 
                padding: '2px 4px', 
                borderRadius: '2px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all'
              }}
            >
              {line}
            </div>
          );
        })}
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
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(12px)',
      zIndex: 10000,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      animation: 'fadeIn 0.2s ease-out',
    }}>
      <div className="glass-panel" style={{
        width: '780px',
        maxWidth: '90vw',
        padding: '24px',
        borderRadius: '16px',
        border: '1px solid rgba(245, 158, 11, 0.35)', // Amber glow boundary
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px rgba(245, 158, 11, 0.1)',
        background: 'rgba(15, 23, 42, 0.96)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            background: 'rgba(245, 158, 11, 0.15)',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            borderRadius: '8px',
            width: '40px',
            height: '40px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fbbf24',
          }}>
            <ShieldAlert size={24} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
            <h3 style={{ margin: 0, fontSize: '18px', color: '#fff', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              ⚠️ Human-in-the-Loop Authorization Required
            </h3>
            <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>
              Execution suspended by OPA security policy. Please review and authorize the tool call below.
            </span>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '6px' }}>
              {approval.project_name ? (
                <div style={{ 
                  fontSize: '12px', 
                  color: '#10b981', 
                  backgroundColor: 'rgba(16, 185, 129, 0.07)',
                  border: '1px solid rgba(16, 185, 129, 0.15)',
                  padding: '5px 10px',
                  borderRadius: '6px',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px'
                }}>
                  📁 Project: <span style={{ color: '#fff' }}>{approval.project_name}</span>
                </div>
              ) : (
                <div style={{ 
                  fontSize: '12px', 
                  color: '#f59e0b', 
                  backgroundColor: 'rgba(245, 158, 11, 0.07)',
                  border: '1px solid rgba(245, 158, 11, 0.15)',
                  padding: '5px 10px',
                  borderRadius: '6px',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px'
                }}>
                  ⚠️ Project: <span style={{ color: '#fff' }}>Simulation / Unspecified</span>
                </div>
              )}
              {approval.task_description && (
                <div style={{ 
                  fontSize: '12px', 
                  color: '#38bdf8', 
                  backgroundColor: 'rgba(56, 189, 248, 0.07)',
                  border: '1px solid rgba(56, 189, 248, 0.15)',
                  padding: '5px 10px',
                  borderRadius: '6px',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px'
                }}>
                  🎯 Task: <span style={{ color: '#fff' }}>{approval.task_description}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Info Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: '12px',
          backgroundColor: 'rgba(255, 255, 255, 0.02)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '8px',
          padding: '12px',
        }}>
          <div>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Approval ID</div>
            <div style={{ fontSize: '12px', color: '#fff', fontWeight: 600, fontFamily: 'monospace' }}>{approval.approval_id}</div>
          </div>
          <div>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Task/DAG ID</div>
            <div style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 600, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={approval.task_id}>{approval.task_id}</div>
          </div>
          <div>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sensitive Tool</div>
            <div style={{ fontSize: '12px', color: '#fbbf24', fontWeight: 600, fontFamily: 'monospace' }}>{approval.tool_name}</div>
          </div>
          <div>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Priority Tier</div>
            <div style={{ fontSize: '12px', color: approval.priority >= 80 ? '#ef4444' : '#60a5fa', fontWeight: 600 }}>{approval.priority} (L3 Gate)</div>
          </div>
          <div>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Requester Agent</div>
            <div style={{ fontSize: '12px', color: '#fff', fontWeight: 600, fontFamily: 'monospace' }}>{approval.agent_id}</div>
          </div>
        </div>

        {/* Workspace Path Banner */}
        {approval.workspace_path && (
          <div style={{ 
            fontSize: '11px', 
            color: 'rgba(255, 255, 255, 0.45)', 
            display: 'flex', 
            alignItems: 'center', 
            gap: '6px',
            backgroundColor: 'rgba(0, 0, 0, 0.25)',
            padding: '8px 12px',
            borderRadius: '8px',
            border: '1px solid rgba(255, 255, 255, 0.04)',
            marginTop: '-4px'
          }}>
            <span style={{ fontWeight: 600, color: 'rgba(255,255,255,0.55)' }}>📁 Workspace Path:</span>
            <span style={{ fontFamily: 'monospace', color: 'rgba(255,255,255,0.75)', wordBreak: 'break-all' }}>{approval.workspace_path}</span>
          </div>
        )}

        {/* Content Tabs / Area */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', flex: 1, minHeight: 0 }}>
          {/* Unified Diff (if exists) */}
          {approval.diff && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'rgba(255,255,255,0.5)', fontWeight: 600 }}>
                <FileText size={12} />
                <span>Unified Source Diff</span>
              </div>
              {renderDiff(approval.diff)}
            </div>
          )}

          {/* Editable JSON Arguments */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'rgba(255,255,255,0.5)', fontWeight: 600 }}>
              <Edit size={12} />
              <span>Modify Target Arguments (JSON)</span>
            </div>
            <textarea
              value={editableArgs}
              onChange={(e) => setEditableArgs(e.target.value)}
              style={{
                width: '100%',
                height: '140px',
                backgroundColor: 'rgba(0, 0, 0, 0.4)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '8px',
                padding: '12px',
                color: '#38bdf8',
                fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                fontSize: '12px',
                lineHeight: '1.4',
                resize: 'none',
                outline: 'none',
                boxSizing: 'border-box'
              }}
            />
          </div>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '16px' }}>
          <button
            onClick={() => handleResolveApproval('rejected')}
            style={{
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.35)',
              color: '#f87171',
              borderRadius: '8px',
              padding: '10px 20px',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.2s',
            }}
          >
            <XCircle size={14} /> Reject & Terminate
          </button>
          
          <button
            onClick={() => handleResolveApproval('approved')}
            style={{
              background: 'linear-gradient(135deg, #10b981, #059669)',
              border: 'none',
              color: '#fff',
              borderRadius: '8px',
              padding: '10px 24px',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              boxShadow: '0 4px 12px rgba(16, 185, 129, 0.2)',
              transition: 'all 0.2s',
            }}
          >
            <CheckCircle size={14} /> Approve & Continue
          </button>
        </div>
      </div>
    </div>
  );
};
