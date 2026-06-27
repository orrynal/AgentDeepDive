import React from 'react';

interface SkillMarketDialogProps {
  isOpen: boolean;
  onClose: () => void;
  marketTab: 'market' | 'installed' | 'preview';
  setMarketTab: (tab: 'market' | 'installed' | 'preview') => void;
  marketSearchQuery: string;
  setMarketSearchQuery: (query: string) => void;
  fetchMarketSkills: (query?: string) => void;
  marketSkills: any[];
  installedSkills: any[];
  fetchInstalledSkills: () => void;
  handleToggleSkill: (skillId: string, currentIsActive: boolean) => void;
  handleDeleteSkill: (skillId: string) => void;
  installingSkillId: string | null;
  setInstallingSkillId: (id: string | null) => void;
  installWorkspacePath: string;
  setInstallWorkspacePath: (path: string) => void;
  installScope: 'global' | 'project';
  setInstallScope: (scope: 'global' | 'project') => void;
  installStatus: string;
  setInstallStatus: (status: string) => void;
  handleInstallSkill: (skillId: string) => void;
  previewContent: string;
  setPreviewContent: (content: string) => void;
  previewResult: any;
  previewLoading: boolean;
  previewError: string | null;
  handlePreviewSkill: () => void;
  handleInstallPreviewedSkill: (scope: 'global' | 'project') => void;
  activeWorkspace: string;
  wsConnected?: boolean;
}

export const SkillMarketDialog: React.FC<SkillMarketDialogProps> = ({
  isOpen,
  onClose,
  marketTab,
  setMarketTab,
  marketSearchQuery,
  setMarketSearchQuery,
  fetchMarketSkills,
  marketSkills,
  installedSkills,
  fetchInstalledSkills,
  handleToggleSkill,
  handleDeleteSkill,
  installingSkillId,
  setInstallingSkillId,
  installWorkspacePath,
  setInstallWorkspacePath,
  installScope,
  setInstallScope,
  installStatus,
  setInstallStatus,
  handleInstallSkill,
  previewContent,
  setPreviewContent,
  previewResult,
  previewLoading,
  previewError,
  handlePreviewSkill,
  handleInstallPreviewedSkill,
  activeWorkspace,
  wsConnected = true,
}) => {
  if (!isOpen && !installingSkillId) return null;

  return (
    <>
      {isOpen && (
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

        width: '850px',
        maxHeight: '85vh',
        padding: '24px',
        borderRadius: '16px',
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        background: 'rgba(15, 23, 42, 0.9)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '20px', color: '#fff', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              🛒 AgentDeepDive Skill Market
            </h3>
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
              Discover and install official & custom agent skills into global or project-specific scope.
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

        {!wsConnected ? (
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '30px 10px',
            textAlign: 'center'
          }}>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '12px',
              maxWidth: '500px'
            }}>
              <div style={{
                fontSize: '48px',
                animation: 'pulse 2s infinite ease-in-out',
                opacity: 0.8
              }}>🔌</div>
              <h4 style={{ margin: 0, color: '#f59e0b', fontSize: '16px', fontWeight: 600 }}>
                Backend Agent Server Offline
              </h4>
              <p style={{ margin: 0, fontSize: '12px', color: 'rgba(255,255,255,0.6)', lineHeight: '1.5' }}>
                The Skill Marketplace, Installed catalog, and Import validator are unavailable. 
                Please start your FastAPI agent server backend (e.g., <code>uvicorn src.api.main:app</code>) 
                to synchronise skills.
              </p>
            </div>

            <div style={{
              width: '100%',
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '16px',
              opacity: 0.45,
              pointerEvents: 'none'
            }}>
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="glass-card" style={{
                  padding: '16px',
                  borderRadius: '12px',
                  border: '1px solid rgba(255,255,255,0.06)',
                  background: 'rgba(255,255,255,0.01)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div className="shimmer-skeleton" style={{ width: '40%', height: '14px' }}></div>
                    <div className="shimmer-skeleton" style={{ width: '20%', height: '12px' }}></div>
                  </div>
                  <div className="shimmer-skeleton" style={{ width: '90%', height: '10px' }}></div>
                  <div className="shimmer-skeleton" style={{ width: '75%', height: '10px' }}></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                    <div className="shimmer-skeleton" style={{ width: '30%', height: '8px' }}></div>
                    <div className="shimmer-skeleton" style={{ width: '25%', height: '16px' }}></div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <>
            {/* Tabs */}
            <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '10px' }}>
              <button
                onClick={() => setMarketTab('market')}
                style={{
                  background: marketTab === 'market' ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                  border: marketTab === 'market' ? '1px solid #3b82f6' : '1px solid transparent',
                  color: marketTab === 'market' ? '#3b82f6' : 'rgba(255,255,255,0.6)',
                  borderRadius: '6px',
                  padding: '6px 16px',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                🛒 Skill Marketplace
              </button>
              <button
                onClick={() => {
                  setMarketTab('installed');
                  fetchInstalledSkills();
                }}
                style={{
                  background: marketTab === 'installed' ? 'rgba(16, 185, 129, 0.2)' : 'transparent',
                  border: marketTab === 'installed' ? '1px solid #10b981' : '1px solid transparent',
                  color: marketTab === 'installed' ? '#10b981' : 'rgba(255,255,255,0.6)',
                  borderRadius: '6px',
                  padding: '6px 16px',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                ⚙️ Installed Skills
              </button>
              <button
                onClick={() => setMarketTab('preview')}
                style={{
                  background: marketTab === 'preview' ? 'rgba(167, 139, 250, 0.2)' : 'transparent',
                  border: marketTab === 'preview' ? '1px solid #a78bfa' : '1px solid transparent',
                  color: marketTab === 'preview' ? '#a78bfa' : 'rgba(255,255,255,0.6)',
                  borderRadius: '6px',
                  padding: '6px 16px',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                ⚡ Import Preview
              </button>
            </div>

            {/* Marketplace Tab Content */}
            {marketTab === 'market' && (
              <>
                {/* Search Bar & Custom URL */}
                <div style={{ display: 'flex', gap: '12px' }}>
                  <input 
                    type="text" 
                    value={marketSearchQuery}
                    onChange={(e) => {
                      setMarketSearchQuery(e.target.value);
                      fetchMarketSkills(e.target.value);
                    }}
                    placeholder="Search official skills (e.g. web-searcher, bug_fixer) or paste custom YAML URL..."
                    style={{
                      flex: 1,
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '8px',
                      padding: '10px 14px',
                      color: '#fff',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  />
                  {marketSearchQuery.startsWith('http') && (
                    <button
                      onClick={() => {
                        setInstallingSkillId(marketSearchQuery);
                        setInstallWorkspacePath(activeWorkspace);
                      }}
                      style={{
                        background: 'linear-gradient(135deg, #10b981, #059669)',
                        border: 'none',
                        color: '#fff',
                        borderRadius: '8px',
                        padding: '10px 20px',
                        cursor: 'pointer',
                        fontSize: '13px',
                        fontWeight: 600
                      }}
                    >
                      ⚡ Install URL
                    </button>
                  )}
                </div>

                {/* Skills Grid */}
                <div style={{
                  flex: 1,
                  overflowY: 'auto',
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '12px',
                  paddingRight: '6px'
                }}>
                  {marketSkills.length > 0 ? (
                    marketSkills.map((skill) => {
                      const installed = installedSkills.find(s => s.skill_id === skill.skill_id);
                      const isInstalled = !!installed;
                      const isUpgrade = installed && installed.version !== skill.version;
                      const btnText = isUpgrade ? 'Upgrade (升级)' : isInstalled ? 'Reinstall (重新安装)' : 'Install Skill';
                      const btnColor = isUpgrade ? '#8b5cf6' : isInstalled ? '#06b6d4' : '#3b82f6';
                      const btnBg = isUpgrade ? 'rgba(139, 92, 246, 0.2)' : isInstalled ? 'rgba(6, 182, 212, 0.2)' : 'rgba(59, 130, 246, 0.2)';
                      return (
                        <div key={skill.skill_id} className="glass-card" style={{
                          padding: '14px',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          border: '1px solid rgba(255,255,255,0.06)',
                          background: 'rgba(255,255,255,0.02)',
                          borderRadius: '10px'
                        }}>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                              <h4 style={{ margin: 0, fontSize: '14px', color: '#38bdf8', fontWeight: 600 }}>
                                {skill.name}
                              </h4>
                              <div style={{ display: 'flex', gap: '4px' }}>
                                <span style={{ fontSize: '10px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                                  v{skill.version}
                                </span>
                                {isInstalled && (
                                  <span style={{ fontSize: '10px', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                                    Installed
                                  </span>
                                )}
                              </div>
                            </div>
                            <p style={{ margin: '0 0 12px 0', fontSize: '12px', color: 'rgba(255,255,255,0.7)', lineHeight: '1.4' }}>
                              {skill.description}
                            </p>
                            
                            {/* Tags */}
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '12px' }}>
                              {skill.tags.map((tag: string) => (
                                <span key={tag} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.5)', padding: '1px 6px', borderRadius: '4px' }}>
                                  {tag}
                                </span>
                              ))}
                            </div>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px', marginTop: '6px' }}>
                            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', display: 'flex', gap: '8px' }}>
                              <span>Risk: <strong style={{ color: skill.risk_level === 'high' ? '#ef4444' : '#22c55e' }}>{skill.risk_level.toUpperCase()}</strong></span>
                              <span>Approval: <strong>{skill.approval_required ? 'YES' : 'NO'}</strong></span>
                            </div>
                            <button
                              onClick={() => {
                                setInstallingSkillId(skill.url || skill.skill_id);
                                setInstallWorkspacePath(activeWorkspace);
                              }}
                              style={{
                                background: btnBg,
                                border: `1px solid ${btnColor}66`,
                                color: btnColor,
                                borderRadius: '6px',
                                padding: '4px 12px',
                                cursor: 'pointer',
                                fontSize: '11px',
                                fontWeight: 600,
                                transition: 'all 0.2s'
                              }}
                            >
                              {btnText}
                            </button>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div style={{ gridColumn: 'span 2', padding: '40px', textAlign: 'center', color: 'rgba(255,255,255,0.3)' }}>
                      No skills matched your search criteria.
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Installed Skills Tab Content */}
            {marketTab === 'installed' && (
              <div style={{
                flex: 1,
                overflowY: 'auto',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '12px',
                paddingRight: '6px'
              }}>
                {installedSkills.length > 0 ? (
                  installedSkills.map((skill) => (
                    <div key={skill.skill_id} className="glass-card" style={{
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      border: skill.is_active ? '1px solid rgba(255,255,255,0.06)' : '1px dashed rgba(255,255,255,0.15)',
                      background: skill.is_active ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.005)',
                      borderRadius: '10px',
                      opacity: skill.is_active ? 1 : 0.65,
                      transition: 'all 0.3s'
                    }}>
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <h4 style={{ margin: 0, fontSize: '14px', color: skill.is_active ? '#10b981' : '#a3a3a3', fontWeight: 600 }}>
                              {skill.name}
                            </h4>
                            {skill.workspace_path ? (
                              <span style={{ fontSize: '9px', background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6', padding: '1px 5px', borderRadius: '4px', fontWeight: 600 }}>
                                Project Scope
                              </span>
                            ) : (
                              <span style={{ fontSize: '9px', background: 'rgba(34, 197, 94, 0.15)', color: '#22c55e', padding: '1px 5px', borderRadius: '4px', fontWeight: 600 }}>
                                Global Scope
                              </span>
                            )}
                          </div>
                          <div style={{ display: 'flex', gap: '4px' }}>
                            <span style={{ fontSize: '10px', background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.6)', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                              v{skill.version}
                            </span>
                            <span style={{
                              fontSize: '10px',
                              background: skill.is_active ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                              color: skill.is_active ? '#10b981' : '#f59e0b',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              fontWeight: 600
                            }}>
                              {skill.is_active ? 'Active' : 'Disabled'}
                            </span>
                          </div>
                        </div>
                        <p style={{ margin: '0 0 12px 0', fontSize: '12px', color: 'rgba(255,255,255,0.7)', lineHeight: '1.4' }}>
                          {skill.description}
                        </p>
                        
                        {/* Tags */}
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '12px' }}>
                          {skill.tags.map((tag: string) => (
                            <span key={tag} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.5)', padding: '1px 6px', borderRadius: '4px' }}>
                              {tag}
                            </span>
                          ))}
                        </div>
                        {skill.workspace_path && (
                          <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', background: 'rgba(0,0,0,0.2)', padding: '6px 8px', borderRadius: '4px', fontFamily: 'monospace', wordBreak: 'break-all', marginBottom: '12px' }}>
                            📁 Path: {skill.workspace_path}
                          </div>
                        )}
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px', marginTop: '6px' }}>
                        <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', display: 'flex', gap: '8px' }}>
                          <span>Risk: <strong style={{ color: skill.risk_level === 'high' ? '#ef4444' : '#22c55e' }}>{skill.risk_level.toUpperCase()}</strong></span>
                          <span>Approval: <strong>{skill.approval_required ? 'YES' : 'NO'}</strong></span>
                        </div>
                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button
                            onClick={() => handleToggleSkill(skill.skill_id, skill.is_active)}
                            style={{
                              background: skill.is_active ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                              border: skill.is_active ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid rgba(16, 185, 129, 0.4)',
                              color: skill.is_active ? '#f59e0b' : '#10b981',
                              borderRadius: '6px',
                              padding: '4px 12px',
                              cursor: 'pointer',
                              fontSize: '11px',
                              fontWeight: 600,
                              transition: 'all 0.2s'
                            }}
                          >
                            {skill.is_active ? 'Disable' : 'Enable'}
                          </button>
                          <button
                            onClick={() => handleDeleteSkill(skill.skill_id)}
                            style={{
                              background: 'rgba(239, 68, 68, 0.15)',
                              border: '1px solid rgba(239, 68, 68, 0.4)',
                              color: '#ef4444',
                              borderRadius: '6px',
                              padding: '4px 12px',
                              cursor: 'pointer',
                              fontSize: '11px',
                              fontWeight: 600,
                              transition: 'all 0.2s'
                            }}
                          >
                            🗑️ Uninstall
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div style={{ gridColumn: 'span 2', padding: '40px', textAlign: 'center', color: 'rgba(255,255,255,0.3)' }}>
                    No installed skills found in the current workspace.
                  </div>
                )}
              </div>
            )}

            {/* Skill Import Preview Tab Content */}
            {marketTab === 'preview' && (
              <div style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
                overflow: 'hidden'
              }}>
                <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.6)' }}>
                  Paste raw Markdown or YAML Skill package content to preview parsed metadata, validation warnings, and system prompts before actual DB/workspace installation.
                </div>
                
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', flex: 1, minHeight: 0 }}>
                  {/* Left: Input Textarea */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', fontWeight: 600, textTransform: 'uppercase' }}>
                      Skill Content (Markdown or YAML)
                    </span>
                    <textarea
                      value={previewContent}
                      onChange={(e) => setPreviewContent(e.target.value)}
                      placeholder="Paste your custom YAML or Markdown skill here...&#10;Example YAML:&#10;skill_id: custom-code-helper&#10;name: Code Helper&#10;version: 1.0.0&#10;system_prompt: Write high-quality Python code.&#10;risk_level: low"
                      style={{
                        flex: 1,
                        background: 'rgba(0,0,0,0.3)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '8px',
                        padding: '12px',
                        color: '#fff',
                        fontFamily: 'monospace',
                        fontSize: '11px',
                        resize: 'none',
                        outline: 'none'
                      }}
                    />
                    <button
                      onClick={handlePreviewSkill}
                      disabled={previewLoading}
                      style={{
                        background: 'linear-gradient(135deg, #a78bfa, #8b5cf6)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: '8px',
                        padding: '10px',
                        cursor: previewLoading ? 'not-allowed' : 'pointer',
                        fontSize: '12px',
                        fontWeight: 600
                      }}
                    >
                      {previewLoading ? 'Analyzing & Parsing...' : '🔍 Analyze & Preview'}
                    </button>
                  </div>

                  {/* Right: Results / Warnings Panel */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px' }}>
                    {previewError && (
                      <div style={{
                        background: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        color: '#ef4444',
                        padding: '10px 14px',
                        borderRadius: '8px',
                        fontSize: '12px'
                      }}>
                        <strong>❌ Parsing Error:</strong> {previewError}
                      </div>
                    )}

                    {previewResult ? (
                      <>
                        {/* Warnings Check */}
                        {previewResult.warnings && previewResult.warnings.length > 0 ? (
                          <div style={{
                            background: 'rgba(245, 158, 11, 0.1)',
                            border: '1px solid rgba(245, 158, 11, 0.3)',
                            color: '#f59e0b',
                            padding: '10px 14px',
                            borderRadius: '8px',
                            fontSize: '12px'
                          }}>
                            <strong>⚠️ Parser Warnings ({previewResult.warnings.length}):</strong>
                            <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                              {previewResult.warnings.map((w: string, idx: number) => (
                                <li key={idx}>{w}</li>
                              ))}
                            </ul>
                          </div>
                        ) : (
                          <div style={{
                            background: 'rgba(16, 185, 129, 0.1)',
                            border: '1px solid rgba(16, 185, 129, 0.3)',
                            color: '#10b981',
                            padding: '10px 14px',
                            borderRadius: '8px',
                            fontSize: '12px',
                            fontWeight: 600
                          }}>
                            ✅ Metadata validation check passed! No errors or warnings found.
                          </div>
                        )}

                        {/* Metadata Details Card */}
                        <div className="glass-card" style={{ padding: '14px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px' }}>
                          <h4 style={{ margin: '0 0 10px 0', fontSize: '13px', color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Parsed Skill Metadata
                          </h4>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                            <div><strong>ID:</strong> <code style={{ color: '#fff' }}>{previewResult.metadata.skill_id}</code></div>
                            <div><strong>Name:</strong> {previewResult.metadata.name}</div>
                            <div><strong>Version:</strong> {previewResult.metadata.version || '1.0.0'}</div>
                            <div><strong>Risk Level:</strong> <span style={{ color: previewResult.metadata.risk_level === 'high' ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{(previewResult.metadata.risk_level || 'low').toUpperCase()}</span></div>
                            <div><strong>Approval Required:</strong> {previewResult.metadata.approval_required ? 'Yes (HITL Enabled)' : 'No (Auto-Execute)'}</div>
                            
                            {/* Triggers */}
                            <div>
                              <strong>Trigger Patterns:</strong>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                                {(previewResult.metadata.trigger_patterns || []).map((t: string) => (
                                  <span key={t} style={{ fontSize: '9px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '1px 5px', borderRadius: '4px' }}>
                                    {t}
                                  </span>
                                ))}
                              </div>
                            </div>

                            {/* Required Tools */}
                            <div>
                              <strong>Required Tools:</strong>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                                {(previewResult.metadata.required_tools || []).map((t: string) => (
                                  <span key={t} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.5)', padding: '1px 6px', borderRadius: '4px' }}>
                                    {t}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* System Prompt Box */}
                        {previewResult.metadata.system_prompt && (
                          <div className="glass-card" style={{ padding: '12px', background: 'rgba(0,0,0,0.2)', borderRadius: '8px' }}>
                            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', fontWeight: 600 }}>Parsed System Prompt:</span>
                            <pre style={{
                              margin: '6px 0 0 0',
                              whiteSpace: 'pre-wrap',
                              fontSize: '10px',
                              color: 'rgba(255,255,255,0.7)',
                              maxHeight: '120px',
                              overflowY: 'auto',
                              fontFamily: 'monospace'
                            }}>
                              {previewResult.metadata.system_prompt}
                            </pre>
                          </div>
                        )}

                        {/* Actions */}
                        <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                          <button
                            onClick={() => handleInstallPreviewedSkill('project')}
                            style={{
                              flex: 1,
                              background: 'rgba(59, 130, 246, 0.2)',
                              border: '1px solid #3b82f6',
                              color: '#3b82f6',
                              borderRadius: '8px',
                              padding: '8px',
                              fontSize: '12px',
                              fontWeight: 600,
                              cursor: 'pointer'
                            }}
                          >
                            Install to Project Scope
                          </button>
                          <button
                            onClick={() => handleInstallPreviewedSkill('global')}
                            style={{
                              flex: 1,
                              background: 'rgba(34, 197, 94, 0.2)',
                              border: '1px solid #22c55e',
                              color: '#22c55e',
                              borderRadius: '8px',
                              padding: '8px',
                              fontSize: '12px',
                              fontWeight: 600,
                              cursor: 'pointer'
                            }}
                          >
                            Install Globally
                          </button>
                        </div>
                      </>
                    ) : (
                      <div style={{
                        flex: 1,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'rgba(255,255,255,0.2)',
                        fontSize: '12px',
                        border: '1px dashed rgba(255,255,255,0.1)',
                        borderRadius: '8px',
                        padding: '40px',
                        textAlign: 'center'
                      }}>
                        Paste content on the left and click 'Analyze' to run validation checks.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
        </div>
      </div>
    )}

      {/* Scope Choice Installation Dialog (Nested) */}
      {installingSkillId && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          backgroundColor: 'rgba(0,0,0,0.85)',
          zIndex: 10000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <div className="glass-panel" style={{
            width: '450px',
            padding: '24px',
            borderRadius: '16px',
            border: '1px solid rgba(255,255,255,0.15)',
            boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
            background: 'rgba(30,41,59,0.9)'
          }}>
            <h3 style={{ margin: '0 0 8px 0', fontSize: '18px', color: '#fff', fontWeight: 700 }}>
              Set Skill Scope & Install
            </h3>
            <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.6)', margin: '0 0 20px 0' }}>
              Choose whether to register <strong>{installingSkillId}</strong> globally or only for a specific project workspace.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '24px' }}>
              {/* Radio Global */}
              <label style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                cursor: 'pointer',
                padding: '10px',
                borderRadius: '8px',
                background: installScope === 'global' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(255,255,255,0.02)',
                border: installScope === 'global' ? '1px solid #22c55e' : '1px solid rgba(255,255,255,0.05)'
              }}>
                <input 
                  type="radio" 
                  name="scope" 
                  value="global" 
                  checked={installScope === 'global'}
                  onChange={() => setInstallScope('global')}
                  style={{ cursor: 'pointer' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>🟢 Global Scope</div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>Available across all workspaces and RAG routes.</div>
                </div>
              </label>

              {/* Radio Project */}
              <label style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                cursor: 'pointer',
                padding: '10px',
                borderRadius: '8px',
                background: installScope === 'project' ? 'rgba(59, 130, 246, 0.1)' : 'rgba(255,255,255,0.02)',
                border: installScope === 'project' ? '1px solid #3b82f6' : '1px solid rgba(255,255,255,0.05)'
              }}>
                <input 
                  type="radio" 
                  name="scope" 
                  value="project" 
                  checked={installScope === 'project'}
                  onChange={() => setInstallScope('project')}
                  style={{ cursor: 'pointer' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>🔵 Project-Only Scope</div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>Isolated to the specified workspace path below.</div>
                </div>
              </label>

              {/* Project Workspace Path Input (Conditional) */}
              {installScope === 'project' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
                  <label style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', fontWeight: 600 }}>
                    Workspace Path
                  </label>
                  <input 
                    type="text" 
                    value={installWorkspacePath}
                    onChange={(e) => setInstallWorkspacePath(e.target.value)}
                    placeholder="e.g. /home/user/projects/my-project"
                    style={{
                      background: 'rgba(0,0,0,0.3)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '6px',
                      padding: '8px 12px',
                      color: '#fff',
                      fontSize: '12px',
                      outline: 'none'
                    }}
                  />
                </div>
              )}
            </div>

            {/* Install Status Notification */}
            {installStatus && (
              <div style={{
                fontSize: '12px',
                color: installStatus.includes('Succeeded') ? '#22c55e' : (installStatus.includes('Error') ? '#ef4444' : '#38bdf8'),
                marginBottom: '16px',
                textAlign: 'center',
                fontWeight: 600
              }}>
                {installStatus}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
              <button 
                onClick={() => {
                  setInstallingSkillId(null);
                  setInstallStatus('');
                }}
                disabled={installStatus === 'Installing...'}
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
              <button 
                onClick={() => handleInstallSkill(installingSkillId)}
                disabled={installStatus === 'Installing...'}
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
                Confirm Install
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

