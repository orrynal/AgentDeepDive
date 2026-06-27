import React from 'react';
import { Layers, ShieldCheck, Database, Coins, Settings } from 'lucide-react';

interface CockpitHeaderProps {
  wsConnected: boolean;
  activeWorkspace: string;
  workspaces: string[];
  handleSwitchWorkspace: (path: string) => void;
  setIsWorkspaceDialogOpen: (open: boolean) => void;
  setIsMarketOpen: (open: boolean) => void;
  fetchMarketSkills: () => void;
  setIsDiagnosticsOpen: (open: boolean) => void;
  setIsOpaDialogOpen: (open: boolean) => void;
  setIsCeleryStatsOpen: (open: boolean) => void;
  autoApprove: boolean;
  handleToggleAutoApprove: () => void;
  autoApproveL4: boolean;
  handleToggleAutoApproveL4: () => void;
  sentinelState: 'active' | 'recovery' | 'idle';
  totalCostUSD: number;
}

export const CockpitHeader: React.FC<CockpitHeaderProps> = ({
  wsConnected,
  activeWorkspace,
  workspaces,
  handleSwitchWorkspace,
  setIsWorkspaceDialogOpen,
  setIsMarketOpen,
  fetchMarketSkills,
  setIsDiagnosticsOpen,
  setIsOpaDialogOpen,
  setIsCeleryStatsOpen,
  autoApprove,
  handleToggleAutoApprove,
  autoApproveL4,
  handleToggleAutoApproveL4,
  sentinelState,
  totalCostUSD,
}) => {
  const [isSettingsOpen, setIsSettingsOpen] = React.useState(false);

  return (
    <header className="glass-panel" style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 20px',
      marginBottom: '10px',
      height: '60px',
      position: 'relative',
      zIndex: 1000
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <Layers style={{ color: '#3b82f6' }} size={24} />
        <div>
          <h2 style={{ fontSize: '18px', margin: 0, fontWeight: 700, letterSpacing: '-0.02em', background: 'linear-gradient(90deg, #fff, #94a3b8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            AgentDeepDive Cockpit
          </h2>
          <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.05em' }}>
            Orchestrator Control Center
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        {/* WS Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', background: 'rgba(255,255,255,0.03)', padding: '0 12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)', height: '32px' }}>
          <div className="status-dot-container">
            <div className="status-dot-core" style={{ backgroundColor: wsConnected ? '#22c55e' : '#ef4444', boxShadow: wsConnected ? '0 0 10px #22c55e' : '0 0 10px #ef4444' }} />
            <div className="status-dot-pulse" style={{ backgroundColor: wsConnected ? '#22c55e' : '#ef4444' }} />
          </div>
          <span>Server: {wsConnected ? 'Connected' : 'Offline'}</span>
        </div>

        {/* Workspace Switcher */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', background: 'rgba(255,255,255,0.03)', padding: '0 8px 0 12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)', height: '32px' }}>
          <span style={{ opacity: 0.6 }}>Workspace:</span>
          <select 
            value={activeWorkspace} 
            onChange={(e) => handleSwitchWorkspace(e.target.value)}
            style={{ 
              background: 'transparent', 
              color: '#fff', 
              border: 'none', 
              outline: 'none', 
              cursor: 'pointer',
              fontSize: '11px',
              fontWeight: 600,
              paddingRight: '4px'
            }}
          >
            {workspaces.map(w => (
              <option key={w} value={w} style={{ background: '#1e293b', color: '#fff' }}>
                {w.split('/').pop() || w}
              </option>
            ))}
          </select>
          <button 
            onClick={() => setIsWorkspaceDialogOpen(true)}
            style={{ 
              background: 'rgba(255,255,255,0.08)', 
              border: 'none', 
              color: '#fff', 
              borderRadius: '4px', 
              padding: '2px 8px', 
              cursor: 'pointer',
              fontSize: '10px',
              fontWeight: 600
            }}
            title="Create/Initialize new workspace"
          >
            + New
          </button>
        </div>

        {/* 🛒 Skill Market */}
        <button 
          onClick={() => {
            setIsMarketOpen(true);
            fetchMarketSkills();
          }}
          style={{ 
            background: 'linear-gradient(135deg, #3b82f6, #2563eb)', 
            border: 'none', 
            color: '#fff', 
            borderRadius: '8px', 
            padding: '0 14px', 
            cursor: 'pointer',
            fontSize: '11px',
            fontWeight: 600,
            boxShadow: '0 0 8px rgba(59, 130, 246, 0.3)',
            height: '32px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px'
          }}
        >
          <span>🛒</span>
          <span>Skill Market</span>
        </button>

        {/* Cost Flywheel */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', background: 'rgba(255,255,255,0.03)', padding: '0 12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)', height: '32px' }}>
          <Coins style={{ color: '#eab308' }} size={13} />
          <span>Cost: <strong style={{ color: '#eab308' }}>${totalCostUSD.toFixed(2)}</strong></span>
        </div>

        {/* Settings Dropdown Button Container */}
        <div style={{ position: 'relative' }}>
          <button 
            onClick={() => setIsSettingsOpen(!isSettingsOpen)}
            style={{ 
              background: isSettingsOpen ? 'rgba(255, 255, 255, 0.12)' : 'rgba(255, 255, 255, 0.05)', 
              border: '1px solid rgba(255,255,255,0.1)', 
              color: '#fff', 
              borderRadius: '8px', 
              padding: '0 12px', 
              cursor: 'pointer',
              fontSize: '11px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              height: '32px'
            }}
          >
            <Settings size={14} style={{ transform: isSettingsOpen ? 'rotate(45deg)' : 'none', transition: 'transform 0.2s' }} />
            <span>Settings</span>
          </button>

          {isSettingsOpen && (
            <>
              {/* Overlay to close dropdown when clicking outside */}
              <div 
                onClick={() => setIsSettingsOpen(false)}
                style={{
                  position: 'fixed',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  zIndex: 998
                }}
              />
              {/* Dropdown Menu */}
              <div style={{
                position: 'absolute',
                top: '38px',
                right: 0,
                background: 'rgba(15, 23, 42, 0.95)',
                backdropFilter: 'blur(16px)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '12px',
                boxShadow: '0 12px 30px rgba(0,0,0,0.6)',
                padding: '16px',
                width: '280px',
                zIndex: 999,
                display: 'flex',
                flexDirection: 'column',
                gap: '12px'
              }}>
                <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.05em', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '6px' }}>
                  Governance & Security
                </div>
                
                {/* L3 Toggle */}
                <div 
                  onClick={handleToggleAutoApprove}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    padding: '6px 8px',
                    borderRadius: '8px',
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.04)',
                    fontSize: '12px'
                  }}
                >
                  <span style={{ color: 'rgba(255,255,255,0.8)' }}>L3 Auto-Approve</span>
                  <div style={{
                    width: '36px',
                    height: '20px',
                    background: autoApprove ? '#22c55e' : 'rgba(255,255,255,0.15)',
                    borderRadius: '10px',
                    position: 'relative',
                    transition: 'background-color 0.2s'
                  }}>
                    <div style={{
                      width: '16px',
                      height: '16px',
                      background: '#fff',
                      borderRadius: '50%',
                      position: 'absolute',
                      top: '2px',
                      left: autoApprove ? '18px' : '2px',
                      transition: 'left 0.2s'
                    }} />
                  </div>
                </div>

                {/* L4 Toggle */}
                <div 
                  onClick={handleToggleAutoApproveL4}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    padding: '6px 8px',
                    borderRadius: '8px',
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.04)',
                    fontSize: '12px'
                  }}
                >
                  <span style={{ color: 'rgba(255,255,255,0.8)' }}>L4 Auto-Approve</span>
                  <div style={{
                    width: '36px',
                    height: '20px',
                    background: autoApproveL4 ? '#22c55e' : 'rgba(255,255,255,0.15)',
                    borderRadius: '10px',
                    position: 'relative',
                    transition: 'background-color 0.2s'
                  }}>
                    <div style={{
                      width: '16px',
                      height: '16px',
                      background: '#fff',
                      borderRadius: '50%',
                      position: 'absolute',
                      top: '2px',
                      left: autoApproveL4 ? '18px' : '2px',
                      transition: 'left 0.2s'
                    }} />
                  </div>
                </div>

                <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.05em', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '6px', marginTop: '4px' }}>
                  Diagnostics & Policy
                </div>

                {/* Webhook Test Button */}
                <button
                  onClick={() => {
                    setIsSettingsOpen(false);
                    setIsDiagnosticsOpen(true);
                  }}
                  style={{
                    background: 'rgba(167, 139, 250, 0.1)',
                    border: '1px solid rgba(167, 139, 250, 0.3)',
                    color: '#c084fc',
                    borderRadius: '8px',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: 600,
                    textAlign: 'left',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                >
                  <span>🔌</span>
                  <span>Webhook Test Panel</span>
                </button>

                {/* OPA Rules Button */}
                <button
                  onClick={() => {
                    setIsSettingsOpen(false);
                    setIsOpaDialogOpen(true);
                  }}
                  style={{
                    background: 'rgba(16, 185, 129, 0.1)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    color: '#34d399',
                    borderRadius: '8px',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: 600,
                    textAlign: 'left',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                >
                  <span>🛡️</span>
                  <span>OPA Policy Rules</span>
                </button>

                {/* Celery Task Monitor Button */}
                <button
                  onClick={() => {
                    setIsSettingsOpen(false);
                    setIsCeleryStatsOpen(true);
                  }}
                  style={{
                    background: 'rgba(236, 72, 153, 0.1)',
                    border: '1px solid rgba(236, 72, 153, 0.3)',
                    color: '#f472b6',
                    borderRadius: '8px',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: 600,
                    textAlign: 'left',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                >
                  <span>⚡</span>
                  <span>Celery Task Monitor</span>
                </button>

                <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px', marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <ShieldCheck style={{ color: sentinelState === 'recovery' ? '#f97316' : '#22c55e' }} size={12} />
                    <span>Sentinel: {sentinelState.toUpperCase()}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Database style={{ color: '#06b6d4' }} size={12} />
                    <span>Milvus DB: CONNECTED</span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
