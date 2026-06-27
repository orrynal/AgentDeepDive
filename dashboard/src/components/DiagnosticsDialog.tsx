import React from 'react';

interface DiagnosticsDialogProps {
  isOpen: boolean;
  onClose: () => void;
  diagnosingChannel: string;
  setDiagnosingChannel: (channel: string) => void;
  diagnosticResult: any;
  diagnosticLoading: boolean;
  diagnosticError: string | null;
  handleTestWebhookConnection: () => void;
}

export const DiagnosticsDialog: React.FC<DiagnosticsDialogProps> = ({
  isOpen,
  onClose,
  diagnosingChannel,
  setDiagnosingChannel,
  diagnosticResult,
  diagnosticLoading,
  diagnosticError,
  handleTestWebhookConnection,
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
        width: '600px',
        padding: '24px',
        borderRadius: '16px',
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        background: 'rgba(15, 23, 42, 0.95)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '18px', color: '#fff', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              🔌 Approval Webhook Diagnostics Panel
            </h3>
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
              Simulate and test connectivity status for Human-in-the-Loop approval channels.
            </span>
          </div>
          <button 
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'rgba(255,255,255,0.6)',
              fontSize: '20px',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            &times;
          </button>
        </div>

        {/* Select Channel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', fontWeight: 600, textTransform: 'uppercase' }}>
            Select Notification Channel
          </span>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {['telegram', 'slack', 'feishu', 'dingtalk'].map((ch) => {
              const label = ch.charAt(0).toUpperCase() + ch.slice(1);
              const active = diagnosingChannel === ch;
              return (
                <button
                  key={ch}
                  onClick={() => setDiagnosingChannel(ch)}
                  style={{
                    background: active ? 'rgba(167, 139, 250, 0.15)' : 'rgba(255,255,255,0.02)',
                    border: active ? '1px solid #a78bfa' : '1px solid rgba(255,255,255,0.05)',
                    color: active ? '#a78bfa' : 'rgba(255,255,255,0.6)',
                    padding: '12px',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    fontWeight: 600,
                    textAlign: 'left',
                    fontSize: '13px',
                    transition: 'all 0.2s'
                  }}
                >
                  {ch === 'telegram' && '🤖 '}
                  {ch === 'slack' && '💬 '}
                  {ch === 'feishu' && '🕊️ '}
                  {ch === 'dingtalk' && '📌 '}
                  {label} Webhook
                </button>
              );
            })}
          </div>
        </div>

        {/* Diagnostic Details */}
        <div style={{
          background: 'rgba(0,0,0,0.2)',
          border: '1px solid rgba(255,255,255,0.05)',
          borderRadius: '8px',
          padding: '12px',
          fontSize: '12px',
          color: 'rgba(255,255,255,0.7)',
          lineHeight: '1.4'
        }}>
          <strong>Webhook Target:</strong> The test simulates a high-priority approval request, sends a JSON payload to the corresponding endpoint, and monitors the API gateway's HTTP response.
        </div>

        {/* Action & Status */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <button
            onClick={handleTestWebhookConnection}
            disabled={diagnosticLoading}
            style={{
              background: 'linear-gradient(135deg, #a78bfa, #8b5cf6)',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '12px',
              cursor: diagnosticLoading ? 'not-allowed' : 'pointer',
              fontSize: '13px',
              fontWeight: 600,
              transition: 'all 0.2s'
            }}
          >
            {diagnosticLoading ? 'Diagnosing Gateway Response...' : '⚡ Trigger Diagnostic Connection Test'}
          </button>

          {/* Diagnostic Output Results */}
          {diagnosticError && (
            <div style={{
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              color: '#ef4444',
              padding: '12px',
              borderRadius: '8px',
              fontSize: '12px',
              fontFamily: 'monospace'
            }}>
              <strong>❌ Diagnosis Failed:</strong> {diagnosticError}
            </div>
          )}

          {diagnosticResult && (
            <div style={{
              background: diagnosticResult.status === 'success' || diagnosticResult.status_code === 200 || diagnosticResult.ok ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
              border: diagnosticResult.status === 'success' || diagnosticResult.status_code === 200 || diagnosticResult.ok ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(245, 158, 11, 0.3)',
              color: diagnosticResult.status === 'success' || diagnosticResult.status_code === 200 || diagnosticResult.ok ? '#10b981' : '#f59e0b',
              padding: '12px',
              borderRadius: '8px',
              fontSize: '12px',
              fontFamily: 'monospace',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px'
            }}>
              <div><strong>Connection Status:</strong> {diagnosticResult.status || 'Success'}</div>
              {diagnosticResult.status_code && <div><strong>HTTP Status Code:</strong> {diagnosticResult.status_code}</div>}
              {diagnosticResult.channel && <div><strong>Channel:</strong> {diagnosticResult.channel}</div>}
              {diagnosticResult.detail && <div><strong>Response Detail:</strong> {diagnosticResult.detail}</div>}
              {diagnosticResult.latency_ms && <div><strong>Latency:</strong> {diagnosticResult.latency_ms} ms</div>}
              {diagnosticResult.payload_sent && (
                <div style={{ marginTop: '6px', background: 'rgba(0,0,0,0.2)', padding: '6px', borderRadius: '4px' }}>
                  <strong>Payload Sent:</strong>
                  <pre style={{ margin: '4px 0 0 0', fontSize: '10px', whiteSpace: 'pre-wrap', color: 'rgba(255,255,255,0.7)' }}>
                    {JSON.stringify(diagnosticResult.payload_sent, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '12px' }}>
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
            Close Panel
          </button>
        </div>
      </div>
    </div>
  );
};
