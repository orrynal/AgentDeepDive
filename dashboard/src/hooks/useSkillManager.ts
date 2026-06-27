import { useState, useCallback } from 'react';
import { API_BASE } from '../App';

/**
 * Custom hook to encapsulate all Skill Market management logic.
 * Extracted from App.tsx to improve modularity and reduce main file size.
 */
export function useSkillManager(
  activeWorkspace: string,
  setCotLogs: React.Dispatch<React.SetStateAction<Array<any>>>
) {
  // Skill Market State
  const [isMarketOpen, setIsMarketOpen] = useState<boolean>(false);
  const [marketTab, setMarketTab] = useState<'market' | 'installed' | 'preview'>('market');
  const [marketSkills, setMarketSkills] = useState<Array<any>>([]);
  const [installedSkills, setInstalledSkills] = useState<Array<any>>([]);
  const [marketSearchQuery, setMarketSearchQuery] = useState<string>('');
  const [installingSkillId, setInstallingSkillId] = useState<string | null>(null);
  const [installScope, setInstallScope] = useState<'global' | 'project'>('project');
  const [installWorkspacePath, setInstallWorkspacePath] = useState<string>('');
  const [installStatus, setInstallStatus] = useState<string>('');

  // Skill Import Preview State
  const [previewContent, setPreviewContent] = useState<string>('');
  const [previewResult, setPreviewResult] = useState<any>(null);
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const fetchInstalledSkills = useCallback(async () => {
    try {
      const url = `${API_BASE}/api/v1/skills?active_only=false&workspace_path=${encodeURIComponent(activeWorkspace)}`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setInstalledSkills(data);
      }
    } catch (err) {
      console.error('Failed to fetch installed skills:', err);
    }
  }, [activeWorkspace]);

  const handleToggleSkill = useCallback(async (skillId: string, currentIsActive: boolean) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/skills/${skillId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !currentIsActive })
      });
      if (res.ok) {
        fetchInstalledSkills();
        setCotLogs(prev => [
          ...prev,
          {
            id: Math.random().toString(),
            type: 'observation',
            text: `${!currentIsActive ? 'Activated' : 'Disabled'} Skill [${skillId}] successfully.`,
            time: new Date().toLocaleTimeString()
          }
        ]);
      } else {
        const errData = await res.json();
        alert(`Failed to toggle skill: ${errData.detail || 'Unknown error'}`);
      }
    } catch (err: any) {
      alert(`Error: ${err.message}`);
    }
  }, [fetchInstalledSkills, setCotLogs]);

  const handleDeleteSkill = useCallback(async (skillId: string) => {
    if (!window.confirm(`Are you sure you want to completely UNINSTALL/DELETE the skill [${skillId}]? This will remove it from the database.`)) {
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/skills/${skillId}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        setCotLogs(prev => [
          ...prev,
          {
            id: Math.random().toString(),
            type: 'observation',
            text: `Uninstalled Skill [${skillId}] successfully.`,
            time: new Date().toLocaleTimeString()
          }
        ]);
        fetchInstalledSkills();
      } else {
        const errData = await res.json();
        alert(`Failed to delete/uninstall skill: ${errData.detail || 'Unknown error'}`);
      }
    } catch (err: any) {
      alert(`Error: ${err.message}`);
    }
  }, [fetchInstalledSkills, setCotLogs]);

  const fetchMarketSkills = useCallback(async (queryStr = '') => {
    try {
      const url = queryStr 
        ? `${API_BASE}/api/v1/skills/market/search?query=${encodeURIComponent(queryStr)}`
        : `${API_BASE}/api/v1/skills/market/search`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setMarketSkills(data);
      }
    } catch (err) {
      console.error('Failed to fetch market skills:', err);
    }
  }, []);

  const handleInstallSkill = useCallback(async (skillId: string) => {
    setInstallStatus('Installing...');
    try {
      const payload = {
        skill_name_or_url: skillId,
        scope: installScope,
        workspace_path: installScope === 'project' ? (installWorkspacePath || activeWorkspace) : null
      };
      const res = await fetch(`${API_BASE}/api/v1/skills/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setInstallStatus('Installation Succeeded! ✅');
        setTimeout(() => {
          setInstallingSkillId(null);
          setInstallStatus('');
        }, 1500);
        setCotLogs(prev => [
          ...prev,
          {
            id: Math.random().toString(),
            type: 'observation',
            text: `Installed Skill [${skillId}] with ${installScope.toUpperCase()} scope successfully.`,
            time: new Date().toLocaleTimeString()
          }
        ]);
      } else {
        const errData = await res.json();
        setInstallStatus(`Error: ${errData.detail || 'Failed to install'}`);
      }
    } catch (err: any) {
      setInstallStatus(`Error: ${err.message}`);
    }
  }, [installScope, installWorkspacePath, activeWorkspace, setCotLogs]);

  const handlePreviewSkill = useCallback(async () => {
    if (!previewContent.trim()) {
      setPreviewError('Please paste raw skill content (Markdown or YAML)');
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/skills/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: previewContent })
      });
      if (res.ok) {
        const data = await res.json();
        setPreviewResult(data);
      } else {
        const errData = await res.json();
        setPreviewError(errData.detail || 'Failed to parse skill preview.');
      }
    } catch (err: any) {
      setPreviewError(err.message || 'Network error.');
    } finally {
      setPreviewLoading(false);
    }
  }, [previewContent]);

  const handleInstallPreviewedSkill = useCallback(async (scope: 'global' | 'project') => {
    if (!previewResult || !previewResult.metadata) return;
    const skillData = {
      ...previewResult.metadata,
      workspace_path: scope === 'project' ? activeWorkspace : null
    };
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(skillData)
      });
      if (res.ok) {
        setCotLogs(prev => [
          ...prev,
          {
            id: Math.random().toString(),
            type: 'observation',
            text: `Successfully imported skill [${skillData.skill_id}] via preview panel.`,
            time: new Date().toLocaleTimeString()
          }
        ]);
        alert(`Skill [${skillData.name}] successfully installed/imported!`);
        setPreviewContent('');
        setPreviewResult(null);
        setMarketTab('installed');
        fetchInstalledSkills();
      } else {
        const errData = await res.json();
        setPreviewError(errData.detail || 'Failed to register skill.');
      }
    } catch (err: any) {
      setPreviewError(err.message || 'Network error.');
    } finally {
      setPreviewLoading(false);
    }
  }, [previewResult, activeWorkspace, setCotLogs, fetchInstalledSkills]);

  return {
    // Market dialog state
    isMarketOpen, setIsMarketOpen,
    marketTab, setMarketTab,
    marketSkills, marketSearchQuery, setMarketSearchQuery,
    installedSkills, fetchInstalledSkills,
    installingSkillId, setInstallingSkillId,
    installScope, setInstallScope,
    installWorkspacePath, setInstallWorkspacePath,
    installStatus, setInstallStatus,
    // Preview state
    previewContent, setPreviewContent,
    previewResult, previewLoading, previewError,
    // Handlers
    handleToggleSkill, handleDeleteSkill,
    fetchMarketSkills, handleInstallSkill,
    handlePreviewSkill, handleInstallPreviewedSkill,
  };
}
