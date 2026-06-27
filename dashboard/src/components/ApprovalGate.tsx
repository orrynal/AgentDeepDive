import React from 'react';
import { UserCheck, CheckCircle2 } from 'lucide-react';

interface ApprovalEntry {
  approval_id: string;
  task_id: string;
  agent_id: string;
  tool_name: string;
  arguments: any;
  priority: number;
  status: 'pending' | 'approved' | 'rejected';
}

interface ApprovalGateProps {
  currentActiveApproval: ApprovalEntry | null;
  editableArgs: string;
  setEditableArgs: (args: string) => void;
  handleResolveApproval: (status: 'approved' | 'rejected') => void;
}

export const ApprovalGate: React.FC<ApprovalGateProps> = ({
  currentActiveApproval,
  editableArgs,
  setEditableArgs,
  handleResolveApproval,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <h3 style={{ fontSize: '13px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <UserCheck size={14} style={{ color: '#f97316' }} />
        Human-in-the-Loop Approval (L3/L4)
      </h3>

      {currentActiveApproval ? (
        <div className="glass-card" style={{
          flex: 1,
          border: '1px solid rgba(249, 115, 22, 0.4)',
          background: 'rgba(249, 115, 22, 0.03)',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '12px',
          overflowY: 'auto'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', fontWeight: 700, color: '#f97316' }}>{currentActiveApproval.approval_id}</span>
            <span style={{ fontSize: '9px', padding: '2px 6px', background: 'rgba(239, 68, 68, 0.2)', color: '#ef4444', borderRadius: '4px', fontWeight: 700 }}>
              PRIORITY {currentActiveApproval.priority}
            </span>
          </div>

          <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)' }}>
            Task ID: <code style={{ color: '#fff' }}>{currentActiveApproval.task_id}</code>
          </div>

          <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)' }}>
            Triggered Tool: <code style={{ color: '#fff' }}>{currentActiveApproval.tool_name}</code>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)' }}>Edit Arguments (JSON):</span>
            <textarea
              value={editableArgs}
              onChange={(e) => setEditableArgs(e.target.value)}
              style={{
                width: '100%',
                flex: 1,
                minHeight: '80px',
                background: 'rgba(0,0,0,0.5)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '4px',
                color: '#38bdf8',
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                padding: '6px'
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
            <button
              onClick={() => handleResolveApproval('approved')}
              style={{
                flex: 1,
                background: '#22c55e',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                padding: '8px',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              ✅ Approve
            </button>
            <button
              onClick={() => handleResolveApproval('rejected')}
              style={{
                flex: 1,
                background: 'rgba(239, 68, 68, 0.1)',
                color: '#ef4444',
                border: '1px solid #ef4444',
                borderRadius: '4px',
                padding: '8px',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              ❌ Reject
            </button>
          </div>
        </div>
      ) : (
        <div className="glass-card" style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'rgba(255,255,255,0.3)',
          fontSize: '12px'
        }}>
          <CheckCircle2 size={32} style={{ color: 'rgba(255,255,255,0.1)', marginBottom: '8px' }} />
          <span>No pending approvals</span>
        </div>
      )}
    </div>
  );
};
