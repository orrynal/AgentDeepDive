import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

const CustomNode = ({ data }: any) => {
  const getMappedColorClass = (c: string) => {
    if (!c) return 'ready';
    switch (c.toLowerCase()) {
      case 'green':
      case 'success':
        return 'success';
      case 'yellow':
      case 'running':
        return 'running';
      case 'blue':
      case 'queued':
        return 'queued';
      case 'orange':
      case 'suspended':
        return 'suspended';
      case 'red':
      case 'failed':
        return 'failed';
      case 'gray':
      case 'ready':
      default:
        return 'ready';
    }
  };

  const isInactive = data.isInactive;
  const color = isInactive ? 'inactive' : getMappedColorClass(data.color);
  const name = data.name || 'Task Node';
  const skillId = data.skillId || 'unknown';
  const roleId = data.roleId || '';
  const progress = data.progress || 0;
  const tokenCost = data.tokenCost || 0;

  const getRoleBadge = (rId: string) => {
    if (!rId) return null;
    const id = rId.toLowerCase();
    if (id.includes('coder') || id.includes('dev')) {
      return { label: 'DEV 💻', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.15)' };
    }
    if (id.includes('qa') || id.includes('tester')) {
      return { label: 'QA 🧪', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' };
    }
    if (id.includes('security') || id.includes('auditor')) {
      return { label: 'SEC 🛡️', color: '#f43f5e', bg: 'rgba(244, 63, 94, 0.15)' };
    }
    if (id.includes('writer') || id.includes('doc')) {
      return { label: 'DOC 📝', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' };
    }
    if (id.includes('supervisor') || id.includes('orchestrator') || id.includes('mgmt')) {
      return { label: 'MGMT 👑', color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)' };
    }
    if (id.includes('designer') || id.includes('ui')) {
      return { label: 'UI 🎨', color: '#ec4899', bg: 'rgba(236, 72, 153, 0.15)' };
    }
    if (id.includes('analyst') || id.includes('data')) {
      return { label: 'DATA 📊', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)' };
    }
    if (id.includes('translator') || id.includes('lang')) {
      return { label: 'LANG 🌐', color: '#14b8a6', bg: 'rgba(20, 184, 166, 0.15)' };
    }
    return { label: rId.toUpperCase().slice(0, 6), color: '#38bdf8', bg: 'rgba(56, 189, 248, 0.15)' };
  };

  const roleBadge = getRoleBadge(roleId);

  return (
    <div className={`react-flow__node-custom ${color}`}>
      <Handle type="target" position={Position.Top} style={{ background: '#555' }} />
      
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontWeight: 600, fontSize: 13, letterSpacing: '-0.01em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {name}
        </span>
        <span style={{
          fontSize: 8,
          padding: '2px 6px',
          borderRadius: 20,
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.1)',
          color: 'rgba(255,255,255,0.6)',
          textTransform: 'uppercase',
          fontWeight: 700,
          letterSpacing: '0.05em'
        }}>
          {skillId}
        </span>
      </div>

      {roleBadge && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: 8 }}>
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>Role:</span>
          <span style={{
            fontSize: 9,
            padding: '2px 8px',
            borderRadius: '4px',
            background: roleBadge.bg,
            color: roleBadge.color,
            border: `1px solid ${roleBadge.color}33`,
            fontWeight: 600,
            textTransform: 'uppercase',
            display: 'inline-flex',
            alignItems: 'center',
          }}>
            {roleBadge.label}
          </span>
        </div>
      )}

      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: '4px' }}>
        <div style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          backgroundColor: getStatusColorHex(color),
          boxShadow: `0 0 8px ${getStatusColorHex(color)}`
        }} />
        Status: <span style={{ textTransform: 'capitalize', color: getStatusColorHex(color), fontWeight: 600 }}>{color === 'inactive' ? 'Pending' : color}</span>
      </div>

      {tokenCost > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 4 }}>
          <span>Tokens: {tokenCost}</span>
          <span>{progress}%</span>
        </div>
      )}

      <div className="node-gauge-container">
        <div className="node-gauge-bar" style={{
          width: `${progress}%`,
          backgroundColor: getStatusColorHex(color),
          boxShadow: `0 0 10px ${getStatusColorHex(color)}`
        }} />
      </div>

      <Handle type="source" position={Position.Bottom} style={{ background: '#555' }} />
    </div>
  );
};

function getStatusColorHex(status: string) {
  switch (status.toLowerCase()) {
    case 'queued':
    case 'blue':
      return '#3b82f6';
    case 'running':
    case 'yellow':
      return '#eab308';
    case 'success':
    case 'green':
      return '#22c55e';
    case 'failed':
    case 'red':
      return '#ef4444';
    case 'suspended':
    case 'orange':
      return '#f97316';
    default:
      return '#64748b';
  }
}

export default memo(CustomNode, (prevProps, nextProps) => {
  if (!prevProps.data || !nextProps.data) return false;
  return (
    prevProps.data.name === nextProps.data.name &&
    prevProps.data.skillId === nextProps.data.skillId &&
    prevProps.data.roleId === nextProps.data.roleId &&
    prevProps.data.color === nextProps.data.color &&
    prevProps.data.progress === nextProps.data.progress &&
    prevProps.data.tokenCost === nextProps.data.tokenCost &&
    prevProps.data.isInactive === nextProps.data.isInactive
  );
});
