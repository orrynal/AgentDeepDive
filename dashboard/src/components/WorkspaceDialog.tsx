import React from 'react';

interface WorkspaceDialogProps {
  isOpen: boolean;
  activeWorkspace: string;
  newWorkspacePath: string;
  setNewWorkspacePath: (path: string) => void;
  handleCreateWorkspace: (path: string) => void;
  onClose: () => void;
}

export const WorkspaceDialog: React.FC<WorkspaceDialogProps> = ({
  isOpen,
  activeWorkspace,
  newWorkspacePath,
  setNewWorkspacePath,
  handleCreateWorkspace,
  onClose,
}) => {
  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: '100vw',
      height: '100vh',
      backgroundColor: 'rgba(0,0,0,0.7)',
      backdropFilter: 'blur(10px)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }}>
      <div className="glass-panel" style={{
        width: '450px',
        padding: '24px',
        borderRadius: '16px',
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        background: 'rgba(30,41,59,0.7)',
        position: 'relative'
      }}>
        {activeWorkspace && (
          <button 
            onClick={onClose}
            style={{
              position: 'absolute',
              top: '16px',
              right: '16px',
              background: 'transparent',
              border: 'none',
              color: 'rgba(255,255,255,0.5)',
              fontSize: '18px',
              cursor: 'pointer',
              lineHeight: 1,
              padding: '4px'
            }}
            title="Close"
          >
            ✕
          </button>
        )}
        <h3 style={{ margin: '0 0 16px 0', fontSize: '18px', color: '#fff' }}>
          {activeWorkspace ? 'Create / Switch Workspace' : 'Welcome! Set Your Workspace'}
        </h3>
        <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.6)', margin: '0 0 20px 0', lineHeight: '1.5' }}>
          Workspaces isolate your source code, local git history, RAG search index, and DAG configuration state.
        </p>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '24px' }}>
          <label style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', fontWeight: 600 }}>
            Workspace Path (Absolute Path)
          </label>
          <input 
            type="text" 
            value={newWorkspacePath}
            onChange={(e) => setNewWorkspacePath(e.target.value)}
            placeholder="e.g. /home/user/projects/tetris"
            style={{
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px',
              padding: '10px 14px',
              color: '#fff',
              fontSize: '13px',
              outline: 'none'
            }}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          {activeWorkspace && (
            <button 
              onClick={onClose}
              style={{
                background: 'transparent',
                border: '1px solid rgba(255,255,255,0.15)',
                color: '#fff',
                borderRadius: '8px',
                padding: '8px 16px',
                cursor: 'pointer',
                fontSize: '12px'
              }}
            >
              Cancel
            </button>
          )}
          <button 
            onClick={() => handleCreateWorkspace(newWorkspacePath)}
            style={{
              background: 'linear-gradient(135deg, #3b82f6, #2563eb)',
              border: 'none',
              color: '#fff',
              borderRadius: '8px',
              padding: '8px 20px',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 600
            }}
          >
            Confirm & Initialize
          </button>
        </div>
      </div>
    </div>
  );
};
