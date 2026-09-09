/**
 * Settings page - Platform configuration
 */
import React, {useState, useEffect, useCallback} from 'react';
import {Card, CardHeader, CardTitle, CardContent, Button, Badge} from '@ytrader/common-components';
import {changeLanguage} from '@ytrader/arch-i18n';
import {Icons} from '../components/icons';
import './Settings.css';

const STORAGE_KEY_API = 'ytrader_api_base';
const DEFAULT_API = '/api/v1';

const providerTypeMap: Record<string, string> = {
  openai_chat: 'OpenAI Chat',
  openai_response: 'OpenAI Response',
  anthropic: 'Anthropic',
};

function getStoredApiBase() {
  const stored = localStorage.getItem(STORAGE_KEY_API);
  if (stored && /^https?:\/\//.test(stored)) return DEFAULT_API;
  return stored || DEFAULT_API;
}

export const Settings: React.FC<{forceTab?: 'ai' | 'system'}> = ({forceTab}) => {
  // 顶层 tab：AI 配置 | 系统设置（forceTab 时锁定；独立页默认系统设置，
  // 因为 AI 配置已迁移到 AI 工作台设置页）
  const [topTab, setTopTab] = useState<'ai' | 'system'>(() => {
    if (forceTab) return forceTab;
    return 'system';
  });

  // API Config
  const [apiBase, setApiBase] = useState(getStoredApiBase);
  const [apiStatus, setApiStatus] = useState<'idle'|'testing'|'ok'|'error'>('idle');
  const [apiError, setApiError] = useState('');

  // LLM Model Config
  const [llmConfigs, setLlmConfigs] = useState<any[]>([]);
  const [llmLoading, setLlmLoading] = useState(false);
  const [showLlmModal, setShowLlmModal] = useState(false);
  const [editingConfig, setEditingConfig] = useState<any>(null);
  const [llmForm, setLlmForm] = useState({
    name: '', provider_type: 'openai_chat' as string,
    base_url: '', api_key: '', model: '', is_default: false,
  });
  const [llmTestResult, setLlmTestResult] = useState<{success: boolean; message: string; latency_ms?: number} | null>(null);
  const [llmTesting, setLlmTesting] = useState(false);

  // Language
  const [lang, setLang] = useState(() => localStorage.getItem('ytrader_lang') || 'en');

  // Feishu Notifications
  const [feishuOpenId, setFeishuOpenId] = useState('');
  const [feishuSaved, setFeishuSaved] = useState(false);
  const [feishuTesting, setFeishuTesting] = useState(false);
  const [feishuTestMsg, setFeishuTestMsg] = useState<{type: 'success' | 'error'; text: string} | null>(null);

  // Inline delete confirmation (replaces native confirm() on LLM).
  // id is string because LLM ids come as string from the API.
  const [confirmDelete, setConfirmDelete] = useState<{kind: 'llm'; id: string | number} | null>(null);

  const runConfirmedDelete = async () => {
    if (!confirmDelete) return;
    const {kind, id} = confirmDelete;
    setConfirmDelete(null);
    if (kind === 'llm') {
      await fetch(`${getStoredApiBase()}/llm/configs/${id}`, {method: 'DELETE'});
      fetchLlmConfigs();
    }
  };

  // Load feishu open_id on mount
  useEffect(() => {
    fetch(`${getStoredApiBase()}/settings`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data.feishu_user_open_id) {
          setFeishuOpenId(j.data.feishu_user_open_id);
        }
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveFeishuOpenId = async () => {
    if (!feishuOpenId.trim()) return;
    try {
      const res = await fetch(`${getStoredApiBase()}/settings/feishu_open_id`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({open_id: feishuOpenId.trim()}),
      });
      const j = await res.json();
      if (j.code === 0) {
        setFeishuSaved(true);
        setTimeout(() => setFeishuSaved(false), 2000);
      }
    } catch {}
  };

  const testFeishuNotification = async () => {
    setFeishuTesting(true);
    setFeishuTestMsg(null);
    try {
      const res = await fetch(`${getStoredApiBase()}/alerts/check/SH600000`);
      const j = await res.json();
      if (j.code === 0) {
        setFeishuTestMsg({
          type: 'success',
          text: `通知已发送！当前价格 ¥${j.data.current_price?.toFixed(2) ?? '—'}`,
        });
      } else {
        setFeishuTestMsg({type: 'error', text: j.detail || '发送失败'});
      }
    } catch (e: any) {
      setFeishuTestMsg({type: 'error', text: e.message || '发送失败'});
    } finally {
      setFeishuTesting(false);
    }
  };

  // ── API Connection Test ─────────────────────────────────────────────
  const testApiConnection = async () => {
    setApiStatus('testing');
    setApiError('');
    try {
      const res = await fetch(`${apiBase}/system/health`, {signal: AbortSignal.timeout(5000)});
      if (res.ok) {
        const json = await res.json();
        setApiStatus('ok');
      } else {
        setApiStatus('error');
        setApiError(`HTTP ${res.status}`);
      }
    } catch (e: any) {
      setApiStatus('error');
      setApiError(e.message || 'Connection failed');
    }
  };

  // Auto-test on mount if API base already set
  useEffect(() => {
    if (apiBase !== DEFAULT_API) {
      testApiConnection();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveApiBase = () => {
    localStorage.setItem(STORAGE_KEY_API, apiBase.trim());
    testApiConnection();
  };

  // ── Language ─────────────────────────────────────────────────────────
  const handleLanguageChange = (lng: string) => {
    setLang(lng);
    localStorage.setItem('ytrader_lang', lng);
    changeLanguage(lng);
  };

  // ── LLM Config CRUD ────────────────────────────────────────────────
  const fetchLlmConfigs = useCallback(() => {
    setLlmLoading(true);
    fetch(`${getStoredApiBase()}/llm/configs`)
      .then(r => r.json())
      .then(j => { if (j.code === 0) setLlmConfigs(j.data); })
      .catch(() => {})
      .finally(() => setLlmLoading(false));
  }, []);

  const saveLlmConfig = async () => {
    const url = editingConfig
      ? `${getStoredApiBase()}/llm/configs/${editingConfig.id}`
      : `${getStoredApiBase()}/llm/configs`;
    const method = editingConfig ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(llmForm),
    });
    const j = await res.json();
    if (j.code === 0 || j.code === 201) {
      setShowLlmModal(false);
      setEditingConfig(null);
      fetchLlmConfigs();
    }
  };

  const deleteLlmConfig = (id: string) => {
    setConfirmDelete({kind: 'llm', id});
  };

  const setDefaultConfig = async (id: string) => {
    await fetch(`${getStoredApiBase()}/llm/configs/${id}/default`, {method: 'PUT'});
    fetchLlmConfigs();
  };

  const testLlmConnection = async (configId?: string) => {
    setLlmTesting(true);
    setLlmTestResult(null);
    try {
      const res = await fetch(`${getStoredApiBase()}/llm/test`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({config_id: configId || null}),
      });
      const j = await res.json();
      if (j.code === 0) {
        setLlmTestResult(j.data);
      }
    } catch (e: any) {
      setLlmTestResult({success: false, message: e.message});
    } finally {
      setLlmTesting(false);
    }
  };

  const openEditModal = (config?: any) => {
    if (config) {
      setEditingConfig(config);
      setLlmForm({
        name: config.name,
        provider_type: config.provider_type,
        base_url: config.base_url,
        api_key: '',
        model: config.model,
        is_default: config.is_default,
      });
    } else {
      setEditingConfig(null);
      setLlmForm({
        name: '', provider_type: 'openai_chat',
        base_url: '', api_key: '', model: '', is_default: false,
      });
    }
    setShowLlmModal(true);
  };

  useEffect(() => {
    fetchLlmConfigs();
  }, [fetchLlmConfigs]);


  return (
    <div className="settings">
      {!forceTab && (
      <header className="settings__header">
        <h1 className="settings__title">Settings</h1>
        <p className="settings__subtitle">Configure your trading platform</p>
      </header>
      )}

      {/* tab 切换条：AI 配置已迁至工作台，全局 Settings 只剩系统设置，无需切换。 */}


      <div className="settings__sections">
        {topTab === 'system' && (
        <>
        {/* ── API Configuration ── */}
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="settings__section-icon">{Icons.link}</span>
              API Configuration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__field">
              <label className="settings__label">API Base URL</label>
              <div className="settings__input-row">
                <input
                  type="text"
                  className="settings__input"
                  value={apiBase}
                  onChange={(e) => setApiBase(e.target.value)}
                  placeholder="/api/v1"
                />
                <Button onClick={saveApiBase} size="sm">Save</Button>
              </div>
              <div className="settings__field-footer">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={testApiConnection}
                  disabled={apiStatus === 'testing'}
                >
                  {apiStatus === 'testing' ? 'Testing...' : 'Test Connection'}
                </Button>
                {apiStatus === 'ok' && <Badge variant="success">Connected</Badge>}
                {apiStatus === 'error' && (
                  <Badge variant="danger">Failed: {apiError}</Badge>
                )}
              </div>
            </div>

            <div className="settings__field">
              <label className="settings__label">WebSocket Endpoint</label>
              <input
                type="text"
                className="settings__input"
                value={apiBase.replace(/^http/, 'ws').replace('/api/v1', '/ws')}
                disabled
              />
              <span className="settings__hint">Auto-derived from API Base URL</span>
            </div>
          </CardContent>
        </Card>
        </>
        )}

        {/* ── LLM Model Config ── */}
        {topTab === 'ai' && (
        <>
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="settings__section-icon">{Icons.cpu}</span>
              LLM 模型配置
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__llm-toolbar">
              <Button size="sm" onClick={() => openEditModal()}>
                <span className="settings__section-icon" style={{width: 14, height: 14}}>{Icons.plus}</span>
                添加模型
              </Button>
              <Button variant="secondary" size="sm" onClick={() => testLlmConnection()} disabled={llmTesting}>
                {llmTesting ? '测试中...' : '测试连接'}
              </Button>
            </div>

            {llmTestResult && (
              <div className={`settings__test-msg settings__test-msg--${llmTestResult.success ? 'success' : 'error'}`}>
                {llmTestResult.message}
                {llmTestResult.latency_ms && ` (${llmTestResult.latency_ms}ms)`}
              </div>
            )}

            <div className="settings__llm-list">
              {llmConfigs.length === 0 && !llmLoading && (
                <div className="settings__llm-empty">暂无模型配置，请点击"添加模型"</div>
              )}
              {llmConfigs.map(cfg => {
                const isConfirming = confirmDelete?.kind === 'llm' && confirmDelete.id === cfg.id;
                return (
                <div key={cfg.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {cfg.is_default && <span className="settings__llm-default-badge">{Icons.star}</span>}
                      {cfg.name}
                    </span>
                    <div className="settings__llm-card-actions">
                      {isConfirming ? (
                        <span className="settings__confirm-row">
                          <button className="settings__confirm-btn settings__confirm-btn--danger" onClick={runConfirmedDelete}>删除</button>
                          <button className="settings__confirm-btn settings__confirm-btn--cancel" onClick={() => setConfirmDelete(null)}>取消</button>
                        </span>
                      ) : (
                        <>
                          {!cfg.is_default && (
                            <Button variant="secondary" size="sm" onClick={() => setDefaultConfig(cfg.id)}>
                              设为默认
                            </Button>
                          )}
                          <Button variant="secondary" size="sm" onClick={() => openEditModal(cfg)}>编辑</Button>
                          <Button variant="secondary" size="sm" onClick={() => deleteLlmConfig(cfg.id)}>删除</Button>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>协议: {providerTypeMap[cfg.provider_type] || cfg.provider_type}</span>
                    <span>模型: {cfg.model}</span>
                  </div>
                  <div className="settings__llm-card-url">{cfg.base_url}</div>
                </div>
                );
              })}
            </div>

            {showLlmModal && (
              <div className="settings__modal-overlay" onClick={() => setShowLlmModal(false)}>
                <div className="settings__modal" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">{editingConfig ? '编辑模型' : '添加模型'}</h3>
                  <div className="settings__field">
                    <label className="settings__label">名称</label>
                    <input className="settings__input" value={llmForm.name}
                      onChange={e => setLlmForm({...llmForm, name: e.target.value})} placeholder="GPT-4o" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">协议</label>
                    <select className="settings__input" value={llmForm.provider_type}
                      onChange={e => setLlmForm({...llmForm, provider_type: e.target.value})}>
                      <option value="openai_chat">OpenAI Chat</option>
                      <option value="openai_response">OpenAI Response</option>
                      <option value="anthropic">Anthropic</option>
                    </select>
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">Base URL</label>
                    <input className="settings__input" value={llmForm.base_url}
                      onChange={e => setLlmForm({...llmForm, base_url: e.target.value})}
                      placeholder="https://api.openai.com/v1" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">API Key</label>
                    <input type="password" className="settings__input" value={llmForm.api_key}
                      onChange={e => setLlmForm({...llmForm, api_key: e.target.value})}
                      placeholder={editingConfig ? '留空则保留原值' : 'sk-...'} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">模型</label>
                    <input className="settings__input" value={llmForm.model}
                      onChange={e => setLlmForm({...llmForm, model: e.target.value})}
                      placeholder="gpt-4o" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">
                      <input type="checkbox" checked={llmForm.is_default}
                        onChange={e => setLlmForm({...llmForm, is_default: e.target.checked})} />
                      {' '}设为默认模型
                    </label>
                  </div>
                  <div className="settings__modal-actions">
                    <Button onClick={saveLlmConfig}>保存</Button>
                    <Button variant="secondary" onClick={() => setShowLlmModal(false)}>取消</Button>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        </>
        )}

        {/* ── Feishu Notifications ── */}
        {topTab === 'system' && (
        <>
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="settings__section-icon">{Icons.bell}</span>
              Feishu Notifications
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__field">
              <label className="settings__label">Your Feishu Open ID</label>
              <div className="settings__input-row">
                <input
                  type="text"
                  className="settings__input"
                  value={feishuOpenId}
                  onChange={(e) => setFeishuOpenId(e.target.value)}
                  placeholder="ou_xxxxxxxxxxxxxxxxx"
                />
                <Button variant="secondary" size="sm" onClick={saveFeishuOpenId}>
                  {feishuSaved ? '已保存' : '保存'}
                </Button>
              </div>
              <span className="settings__hint">
                Required for price alert notifications. Found in Feishu → Profile → Open ID.
              </span>
            </div>
            {feishuOpenId.trim() && (
              <div className="settings__field">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={testFeishuNotification}
                  disabled={feishuTesting}
                >
                  <span className="settings__section-icon" style={{width: 14, height: 14}}>{Icons.flask}</span>
                  {feishuTesting ? '发送中...' : '发送测试通知'}
                </Button>
                {feishuTestMsg && (
                  <span className={`settings__test-msg settings__test-msg--${feishuTestMsg.type}`}>
                    {feishuTestMsg.text}
                  </span>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 亮色主题待令牌体系全量落地后开放（见 docs/superpowers/specs/2026-08-14-ui-unification-design.md §6） */}

        {/* ── Language ── */}
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="settings__section-icon">{Icons.globe}</span>
              Language
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__field">
              <label className="settings__label">Interface Language</label>
              <div className="settings__lang-options">
                {[
                  {label: '简体中文', value: 'zh-CN'},
                  {label: 'English', value: 'en'},
                ].map((opt) => (
                  <button
                    key={opt.value}
                    className={`settings__lang-btn ${lang === opt.value ? 'settings__lang-btn--active' : ''}`}
                    onClick={() => handleLanguageChange(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Data Stats ── */}
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="settings__section-icon">{Icons.analytics}</span>
              Market Data
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__stats">
              <div className="settings__stat-item">
                <span className="settings__stat-label">A-Share</span>
                <span className="settings__stat-value">5,193 stocks</span>
              </div>
              <div className="settings__stat-item">
                <span className="settings__stat-label">HK Stocks</span>
                <span className="settings__stat-value">3,211 stocks</span>
              </div>
              <div className="settings__stat-item">
                <span className="settings__stat-label">Data Range</span>
                <span className="settings__stat-value">2020-09-02 ~ 2026-04-03</span>
              </div>
            </div>
          </CardContent>
        </Card>
        </>
        )}

      </div>
    </div>
  );
};
