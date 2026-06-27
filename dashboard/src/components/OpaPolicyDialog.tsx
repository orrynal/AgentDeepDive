import React, { useState, useEffect } from 'react';
import { Shield, Save, RefreshCw, AlertTriangle, HelpCircle } from 'lucide-react';

interface OpaPolicyDialogProps {
  isOpen: boolean;
  onClose: () => void;
  activeWorkspace?: string;
  wsConnected?: boolean;
}

export const OpaPolicyDialog: React.FC<OpaPolicyDialogProps> = ({
  isOpen,
  onClose,
  activeWorkspace,
  wsConnected = true,
}) => {
  const [policyContent, setPolicyContent] = useState<string>('');
  const [originalContent, setOriginalContent] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [uploadedSuccess, setUploadedSuccess] = useState<boolean | null>(null);
  const [showHelp, setShowHelp] = useState<boolean>(true);
  const [hotReloadedMsg, setHotReloadedMsg] = useState<string | null>(null);

  // Policy Tester States
  const [mockInputStr, setMockInputStr] = useState<string>(
    JSON.stringify({
      tool_name: "file_write",
      arguments: {
        target_path: "../etc/passwd"
      }
    }, null, 2)
  );
  const [testResult, setTestResult] = useState<{ risk_level?: string; error?: string } | null>(null);
  const [testing, setTesting] = useState<boolean>(false);

  // Fetch policy when the dialog opens
  useEffect(() => {
    if (isOpen) {
      fetchPolicy();
    }
  }, [isOpen]);

  // Silent background hot-reload when activeWorkspace changes
  useEffect(() => {
    if (isOpen && activeWorkspace) {
      silentFetchPolicy();
    }
  }, [activeWorkspace]);

  const silentFetchPolicy = async () => {
    try {
      const response = await fetch('/api/v1/opa/policy');
      if (!response.ok) return;
      const data = await response.json();
      const newContent = data.policy_content || '';
      
      if (policyContent !== newContent) {
        const isDirty = policyContent !== originalContent;
        if (isDirty) {
          setHotReloadedMsg('Workspace changed & rules reloaded. Kept your unsaved draft.');
        } else {
          setPolicyContent(newContent);
          setOriginalContent(newContent);
          setHotReloadedMsg('Workspace changed. OPA rules hot-reloaded successfully.');
        }
        setTimeout(() => setHotReloadedMsg(null), 5000);
      }
    } catch (err) {
      console.log('Silent OPA reload failed', err);
    }
  };

  const fetchPolicy = async () => {
    setLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const response = await fetch('/api/v1/opa/policy');
      if (!response.ok) {
        throw new Error(`Failed to load policy: HTTP ${response.status}`);
      }
      const data = await response.json();
      setPolicyContent(data.policy_content || '');
      setOriginalContent(data.policy_content || '');
    } catch (err: any) {
      setError(err.message || 'Unknown error fetching Rego policy.');
    } finally {
      setLoading(false);
    }
  };

  const handleSavePolicy = async () => {
    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    setUploadedSuccess(null);
    try {
      const response = await fetch('/api/v1/opa/policy', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ policy_content: policyContent }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
      }
      const result = await response.json();
      setUploadedSuccess(result.uploaded_to_opa);
      if (result.uploaded_to_opa) {
        setSuccessMsg('rego policy saved and successfully pushed to OPA engine.');
      } else {
        setSuccessMsg('rego policy saved to disk, but failed to push to OPA. Check OPA server status.');
      }
      setOriginalContent(policyContent);
    } catch (err: any) {
      setError(err.message || 'Unknown error saving Rego policy.');
    } finally {
      setSaving(false);
    }
  };

  const handleTestPolicy = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      let parsedInput;
      try {
        parsedInput = JSON.parse(mockInputStr);
      } catch (e: any) {
        throw new Error(`Invalid JSON format: ${e.message}`);
      }

      const response = await fetch('/api/v1/opa/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          policy_content: policyContent,
          mock_input: parsedInput
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const result = await response.json();
      setTestResult({ risk_level: result.risk_level });
    } catch (err: any) {
      setTestResult({ error: err.message });
    } finally {
      setTesting(false);
    }
  };

  const isDirty = policyContent !== originalContent;

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
        width: showHelp ? '1200px' : '850px',
        maxWidth: '95vw',
        height: '750px',
        maxHeight: '95vh',
        padding: '24px',
        borderRadius: '16px',
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        background: 'rgba(15, 23, 42, 0.95)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        transition: 'all 0.3s ease-in-out'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Shield style={{ color: '#a78bfa' }} size={24} />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <h3 style={{ margin: 0, fontSize: '18px', color: '#fff', fontWeight: 700 }}>
                  🛡️ OPA (Open Policy Agent) Rego Rule Editor
                </h3>
                <button
                  onClick={() => setShowHelp(!showHelp)}
                  style={{
                    background: showHelp ? 'rgba(167, 139, 250, 0.2)' : 'rgba(255,255,255,0.05)',
                    border: `1px solid ${showHelp ? '#a78bfa' : 'rgba(255,255,255,0.1)'}`,
                    borderRadius: '50%',
                    width: '24px',
                    height: '24px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: showHelp ? '#c084fc' : 'rgba(255,255,255,0.6)',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    outline: 'none',
                    padding: 0
                  }}
                  title="Toggle Rego Reference Guide"
                >
                  <HelpCircle size={14} />
                </button>
              </div>
              <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
                Dynamically adjust active sandbox interception guardrails and policy declarations.
              </span>
            </div>
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

        {/* Warning / Notes */}
        <div style={{
          background: 'rgba(245, 158, 11, 0.05)',
          border: '1px solid rgba(245, 158, 11, 0.2)',
          borderRadius: '8px',
          padding: '10px 14px',
          fontSize: '11.5px',
          color: '#f59e0b',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          lineHeight: '1.4'
        }}>
          <AlertTriangle size={16} style={{ flexShrink: 0 }} />
          <span>
            <strong>Warning:</strong> Invalid syntax in Rego rules will prevent OPA policy compilation. Double-check your rules, target paths, and whitelist logic before publishing updates to the production sandboxes.
          </span>
        </div>

        {/* Hot Reload Status Message */}
        {hotReloadedMsg && (
          <div style={{
            background: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            borderRadius: '8px',
            padding: '10px 14px',
            fontSize: '11.5px',
            color: '#34d399',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            lineHeight: '1.4',
            animation: 'fadeIn 0.3s ease-in-out'
          }}>
            <span style={{ fontSize: '14px' }}>⚡</span>
            <span>{hotReloadedMsg}</span>
          </div>
        )}

        {/* Action Bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.02)', padding: '8px 12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>Policy State:</span>
            <span style={{ 
              background: uploadedSuccess === true ? 'rgba(34,197,94,0.15)' : uploadedSuccess === false ? 'rgba(249,115,22,0.15)' : 'rgba(148,163,184,0.15)',
              color: uploadedSuccess === true ? '#22c55e' : uploadedSuccess === false ? '#f97316' : '#94a3b8',
              padding: '2px 8px',
              borderRadius: '4px',
              fontWeight: 700,
              fontSize: '10px',
              textTransform: 'uppercase'
            }}>
              {uploadedSuccess === true ? 'Synchronized with OPA' : uploadedSuccess === false ? 'Failed to upload' : 'Unsaved / Cached'}
            </span>
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={fetchPolicy}
              disabled={loading || saving || !wsConnected}
              style={{
                background: 'rgba(255,255,255,0.05)',
                color: wsConnected ? '#fff' : 'rgba(255,255,255,0.3)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '6px',
                padding: '6px 12px',
                cursor: wsConnected ? 'pointer' : 'not-allowed',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <RefreshCw size={14} className={loading ? 'spin-animation' : ''} />
              Reload
            </button>
            <button
              onClick={handleSavePolicy}
              disabled={saving || !isDirty || !wsConnected}
              style={{
                background: (isDirty && wsConnected) ? 'linear-gradient(135deg, #a78bfa, #8b5cf6)' : 'rgba(255,255,255,0.02)',
                color: (isDirty && wsConnected) ? '#fff' : 'rgba(255,255,255,0.3)',
                border: (isDirty && wsConnected) ? 'none' : '1px solid rgba(255,255,255,0.05)',
                borderRadius: '6px',
                padding: '6px 14px',
                cursor: (isDirty && wsConnected) ? 'pointer' : 'not-allowed',
                fontSize: '12px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                transition: 'all 0.2s'
              }}
            >
              <Save size={14} />
              Save & Apply
            </button>
          </div>
        </div>

        {/* Editor and Help Sidebar Flex Layout */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'row', gap: '16px', minHeight: 0 }}>
          {/* Left Column: Editor & Feedback */}
          <div style={{ flex: 1.8, display: 'flex', flexDirection: 'column', gap: '12px', minHeight: 0 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
              {!wsConnected && (
                <div style={{
                  position: 'absolute',
                  top: 0, left: 0, right: 0, bottom: 0,
                  background: 'rgba(15, 23, 42, 0.85)',
                  backdropFilter: 'blur(3px)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: '8px',
                  border: '1px solid rgba(255,255,255,0.05)',
                  zIndex: 10,
                  padding: '20px',
                  textAlign: 'center'
                }}>
                  <div style={{ fontSize: '32px', marginBottom: '8px', animation: 'pulse 2s infinite ease-in-out' }}>🔒</div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#f59e0b', marginBottom: '4px' }}>OPA Editor Locked</div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)', maxWidth: '280px', lineHeight: '1.4' }}>
                    Agent server is offline. Rego sandbox guardrails cannot be retrieved or modified until the orchestrator is connected.
                  </div>
                </div>
              )}
              {loading ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.1)', borderRadius: '8px', color: 'rgba(255,255,255,0.6)', gap: '10px' }}>
                  <RefreshCw size={20} className="spin-animation" />
                  <span>Fetching policy from server...</span>
                </div>
              ) : (
                <textarea
                  value={policyContent}
                  onChange={(e) => setPolicyContent(e.target.value)}
                  disabled={saving}
                  style={{
                    flex: 1,
                    background: 'rgba(0, 0, 0, 0.3)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px',
                    padding: '16px',
                    color: '#22c55e',
                    fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                    fontSize: '13px',
                    lineHeight: '1.5',
                    resize: 'none',
                    outline: 'none'
                  }}
                  placeholder="# Enter Rego rules here..."
                />
              )}
            </div>

            {/* Feedback Messages */}
            {error && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#ef4444',
                padding: '10px 14px',
                borderRadius: '8px',
                fontSize: '12px',
                fontFamily: 'monospace'
              }}>
                <strong>❌ Error:</strong> {error}
              </div>
            )}

            {successMsg && (
              <div style={{
                background: uploadedSuccess ? 'rgba(34,197,94,0.1)' : 'rgba(249,115,22,0.1)',
                border: uploadedSuccess ? '1px solid rgba(34,197,94,0.3)' : '1px solid rgba(249,115,22,0.3)',
                color: uploadedSuccess ? '#22c55e' : '#f97316',
                padding: '10px 14px',
                borderRadius: '8px',
                fontSize: '12px'
              }}>
                <strong>✨ Status Update:</strong> {successMsg}
              </div>
            )}
          </div>

          {/* Right Column: Rego Policy Guide & Simulator */}
          {showHelp && (
            <div style={{
              flex: 1.2,
              background: 'rgba(0, 0, 0, 0.2)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '8px',
              padding: '16px',
              overflowY: 'auto',
              fontSize: '12px',
              color: 'rgba(255,255,255,0.8)',
              lineHeight: '1.5',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              maxHeight: '100%'
            }}>
              {/* Guides */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <h4 style={{ margin: 0, color: '#fff', fontSize: '13px', fontWeight: 600, borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '6px' }}>
                  📖 Rego Policy Quick Guide
                </h4>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontWeight: 600, color: '#a78bfa' }}>Risk Levels:</span>
                  <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)' }}>
                    • <strong>L0 / L1</strong>: Safe. No intervention.<br/>
                    • <strong>L2</strong>: Allowed, but audited/logged.<br/>
                    • <strong>L3</strong>: Risky. Suspends task and triggers <strong>HIL approval (Slack/Feishu)</strong>.<br/>
                    • <strong>L4</strong>: Forbidden. Blocks tool call immediately.
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontWeight: 600, color: '#a78bfa' }}>Input JSON Structure (input):</span>
                  <pre style={{
                    margin: 0,
                    background: 'rgba(0,0,0,0.4)',
                    padding: '8px',
                    borderRadius: '4px',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    color: '#22c55e',
                    overflowX: 'auto'
                  }}>{`{
  "tool_name": "file_write",
  "workspace_path": "/home/user/workspace",
  "arguments": {
    "target_path": "../etc/passwd"
  }
}`}</pre>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontWeight: 600, color: '#a78bfa' }}>Example Rules:</span>
                  <pre style={{
                    margin: 0,
                    background: 'rgba(0,0,0,0.4)',
                    padding: '8px',
                    borderRadius: '4px',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    color: '#e2e8f0',
                    overflowX: 'auto'
                  }}>{`# 1. Block Path Traversal (L4)
risk_level = "L4" {
    input.tool_name == "file_write"
    contains(input.arguments.target_path, "..")
}

# 2. Block Outside Workspace (L4)
risk_level = "L4" {
    input.tool_name == "file_write"
    startswith(input.arguments.target_path, "/")
    not startswith(input.arguments.target_path, input.workspace_path)
}

# 3. Intercept sensitive files (L3)
risk_level = "L3" {
    input.tool_name == "file_write"
    re_match(".*\\\\.env$", input.arguments.target_path)
}

# 4. Block forbidden shell commands
risk_level = "L4" {
    input.tool_name == "shell_exec"
    re_match(".*\\\\b(sudo|chmod)\\\\b.*", input.arguments.command)
}`}</pre>
                </div>
              </div>

              {/* Divider */}
              <div style={{ height: '1px', background: 'rgba(255,255,255,0.1)', margin: '8px 0' }} />

              {/* Interactive Policy Tester Section */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', position: 'relative' }}>
                {!wsConnected && (
                  <div style={{
                    position: 'absolute',
                    top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(15, 23, 42, 0.85)',
                    backdropFilter: 'blur(3px)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.05)',
                    zIndex: 10,
                    padding: '10px',
                    textAlign: 'center'
                  }}>
                    <span style={{ fontSize: '11px', fontWeight: 600, color: '#f59e0b' }}>Tester Disabled (Offline)</span>
                  </div>
                )}
                <h4 style={{ margin: 0, color: '#fff', fontSize: '13px', fontWeight: 600 }}>
                  🔍 Interactive Policy Tester
                </h4>
                <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
                  Simulate a mock tool call input to dry-run your draft Rego policy.
                </span>

                {/* Template Preset Buttons */}
                <div style={{ display: 'flex', gap: '8px', marginBottom: '2px' }}>
                  <button
                    onClick={() => setMockInputStr(JSON.stringify({
                      tool_name: "file_write",
                      workspace_path: "/path/to/AgentDeepDive",
                      arguments: {
                        target_path: "../etc/passwd"
                      }
                    }, null, 2))}
                    style={{
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '4px',
                      color: '#a78bfa',
                      fontSize: '10px',
                      padding: '4px 8px',
                      cursor: 'pointer',
                      outline: 'none',
                      transition: 'all 0.2s'
                    }}
                    title="Load mock file write input schema"
                  >
                    📄 File Write Input
                  </button>
                  <button
                    onClick={() => setMockInputStr(JSON.stringify({
                      tool_name: "shell_exec",
                      workspace_path: "/path/to/AgentDeepDive",
                      arguments: {
                        command: "sudo rm -rf /"
                      },
                      whitelist_enabled: false,
                      whitelist_commands: [],
                      parsed_command: {
                        ast_risk: "L4"
                      }
                    }, null, 2))}
                    style={{
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '4px',
                      color: '#a78bfa',
                      fontSize: '10px',
                      padding: '4px 8px',
                      cursor: 'pointer',
                      outline: 'none',
                      transition: 'all 0.2s'
                    }}
                    title="Load mock shell command input schema"
                  >
                    📄 Shell Exec Input
                  </button>
                </div>

                <textarea
                  value={mockInputStr}
                  onChange={(e) => setMockInputStr(e.target.value)}
                  style={{
                    background: 'rgba(0, 0, 0, 0.4)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '6px',
                    padding: '8px',
                    color: '#38bdf8',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    height: '100px',
                    resize: 'vertical',
                    outline: 'none'
                  }}
                  placeholder="Enter input JSON..."
                />

                <button
                  onClick={handleTestPolicy}
                  disabled={testing || loading}
                  style={{
                    background: 'rgba(167, 139, 250, 0.15)',
                    color: '#c084fc',
                    border: '1px solid rgba(167, 139, 250, 0.3)',
                    borderRadius: '6px',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    fontSize: '11px',
                    fontWeight: 600,
                    textAlign: 'center',
                    transition: 'all 0.2s',
                    outline: 'none'
                  }}
                >
                  {testing ? 'Evaluating...' : '⚡ Run Policy Dry-Run'}
                </button>

                {testResult && (
                  <div style={{
                    marginTop: '4px',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    background: testResult.error ? 'rgba(239, 68, 68, 0.1)' : 'rgba(255,255,255,0.03)',
                    border: testResult.error ? '1px solid rgba(239, 68, 68, 0.2)' : '1px solid rgba(255,255,255,0.08)',
                    color: testResult.error ? '#ef4444' : '#fff'
                  }}>
                    {testResult.error ? (
                      <div><strong>Error:</strong> {testResult.error}</div>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span>Evaluation Outcome:</span>
                        <span style={{
                          background: testResult.risk_level === 'L4' ? 'rgba(239,68,68,0.15)' :
                                      testResult.risk_level === 'L3' ? 'rgba(249,115,22,0.15)' :
                                      testResult.risk_level === 'L2' ? 'rgba(234,179,8,0.15)' : 'rgba(34,197,94,0.15)',
                          color: testResult.risk_level === 'L4' ? '#ef4444' :
                                 testResult.risk_level === 'L3' ? '#f97316' :
                                 testResult.risk_level === 'L2' ? '#eab308' : '#22c55e',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          fontWeight: 700,
                          fontSize: '10px'
                        }}>
                          {testResult.risk_level}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
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
