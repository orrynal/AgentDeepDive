import { Terminal } from 'lucide-react';

interface LogEntry {
  id: string;
  nodeId?: string;
  type: 'thought' | 'tool' | 'observation';
  text: string;
  time: string;
}

interface LogTelemetryProps {
  selectedNode: any;
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  filteredLogs: LogEntry[];
}

const BLUEPRINT_DESCRIPTIONS: { [key: string]: { desc: string; details: string[]; statusText: string; statusColor: string } } = {
  'bp-cli': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: '统一终端 CLI 入口。支持本地直连运行和远程 Docker/Kubernetes 协作的双轨命令行环境。',
    details: [
      '支持懒加载 (Lazy Loading)，--help 响应时间缩减至 100ms 级别。',
      '集成 doctor 运维自检诊断与 monitor TUI 终端实时刷新监控面板。',
      '包含 db 迁移与 lock 分布式锁清除命令。'
    ]
  },
  'bp-webui': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'Cockpit 工业级中控台。基于 React & Vite 构建的高颜值 Web 交互面板。',
    details: [
      '支持 DAG 编排引擎节点状态实时流式推送 (WebSocket)。',
      '提供 Skill Market 技能包五态生命周期管理和 HITL 决策响应。',
      '包含 Webhook 诊断与 OPA 安全规则发布入口。'
    ]
  },
  'bp-api': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'FastAPI 后端集成路由。核心 Web 服务的 REST API 与 WebSocket 信道枢纽。',
    details: [
      '承载 DAG 自动分解、运行状态查询及取消执行接口。',
      '提供多租户（Multi-Tenant）鉴权与基于 OPA/Rego 的安全依赖拦截。',
      '管理 Redis 分布式文件锁与心跳库事件派发。'
    ]
  },
  'bp-dag': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'DAG 编排调度引擎。负责自然语言任务的拓扑排序、分解、故障纠错突变与断点恢复。',
    details: [
      '将复杂指令编译为节点有向无环图，以 Topological 排序并行/串行执行。',
      '节点异常时支持动态突变 (Dynamic Mutation) 与故障交互式挂起。',
      '支持 /retry、/bypass、/patch 操作进行就地恢复执行。'
    ]
  },
  'bp-router': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: '自适应智能路由器。根据任务复杂度和文件规模，智能分流至最佳智能体梯度。',
    details: [
      'Tier 1: 针对微小任务自动采用通用单兵智能体 (GeneralistAgent)。',
      'Tier 2: 中型任务静态路由至指定名义角色的智能体 (RoleRouter)。',
      'Tier 3: 复杂任务启动多 Agent 招投标契约网系统 (ContractNet)。'
    ]
  },
  'bp-contract': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'FIPA-ACL 契约网竞标协议。实现去中心化多智能体自主报价、忙碌惩罚与招投标博弈。',
    details: [
      '依据 Agent 剩余 Token、耗时预算和排队队列长度加权评分竞标。',
      '智能体自主决策 Propose、Accept、Reject 等竞标状态。',
      '运行结束后更新 Redis 资费统计，以更新后续竞标水位。'
    ]
  },
  'bp-executor': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'AgentExecutor 运行时。智能体执行具体任务节点的底层沙箱调用与执行核心。',
    details: [
      '自动拼装父依赖节点 (Parent Context) 并限制单次预算水位。',
      '接入 LiteLLM 模型网关并利用 Redlock 分布式锁隔离临界资源。',
      '实时向 Redis 消息总线流式发布执行日志和状态突变。'
    ]
  },
  'bp-docker': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'Docker 物理沙箱隔离。在隔离的 Docker 容器中执行 Shell 指令与文件写操作。',
    details: [
      '通过 agentdeep-managed=true 元数据标签对容器生命周期进行强生命周期锁定。',
      '防止恶意代码或破坏性指令直接损毁宿主机环境。',
      '支持挂载本地临时 workspace 目录，以防数据丢失。'
    ]
  },
  'bp-k8s': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'Kubernetes 隔离运行时。为云原生部署提供更高级别的 gVisor / Firecracker 微隔离微服务。',
    details: [
      '动态拉起独立 Pod 并流式监听 v1.read_namespaced_pod_log 日志。',
      '配置 RuntimeClassName 启用内核级容器逃逸隔离防护屏障。',
      '由 Sentinel Daemon 守护进程定时强行 GC 清理孤立超期 Pod 资源。'
    ]
  },
  'bp-guardrails': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'OPA/Rego 安全守卫引擎。利用开放策略代理对智能体高危动作进行声明式拦截判定。',
    details: [
      '通过 guardrails.rego 策略文件对高危命令与写操作进行声明式评估。',
      '支持与 FastAST 解析结合，并在 OPA 挂掉或响应超时后自动安全级降级。'
    ]
  },
  'bp-hitl': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: '人机协同审批与 Unified Diff 系统。当 OPA 规则触发拦截或高危操作时挂起任务，等待人工确认。',
    details: [
      '支持 Telegram、Slack Block Kit、Feishu 互动卡片、DingTalk 卡片推送。',
      '自动生成写操作 Unified Diff，供人类审核员快速对比代码差异。',
      '包含网页版一键安全授权拦截页面与 Webhook 通道一键诊断诊断。'
    ]
  },
  'bp-sentinel': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'Sentinel 守护进程与 GC 回收服务。在后台定期打扫异常退出的孤立容器、Pod 以及过期的 Redis 锁。',
    details: [
      '轮询 Redis 状态并清除心跳超时的 Agent，主动释放分布式 Redlock 锁槽。',
      '物理层面自动强杀宿主机上的僵尸沙箱容器或微隔离 Pod，避免资源泄漏。',
      '提供脱离 FastAPI 主进程的 Cron 守护 GC 模式。'
    ]
  },
  'bp-memory': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: 'Milvus 向量知识检索 (RAG)。作为底层 Agent 长期情节记忆 (Episodic Memory) 的沉淀库。',
    details: [
      '缓存常用技能向量嵌入，出错时自动 query_episodic_memory 召回最相似报错的修复 Patch。',
      '以 Few-shot 方式喂给诊断 LLM，减少 Token 开销并实现自愈闭环。'
    ]
  },
  'bp-abtesting': {
    statusText: 'Under Development (开发迭代中)',
    statusColor: '#eab308',
    desc: '自演进 Prompt 灰度测试 A/B。实现主备版本智能体 Prompt 的灰度运行与自优化。',
    details: [
      '自愈派生 -beta.flywheel 分支，限制 20% 流量占比灰度分流。',
      '基于三法官加终审裁决共识（Judge A+B+C）评估模型输出分值。',
      '指标优于原版时自动回写 Prompt 并合并升级主版本。'
    ]
  },
  'bp-dialogue': {
    statusText: 'Planned (已规划待开发)',
    statusColor: '#64748b',
    desc: 'Agent 间交流与共识系统 ( dialogue )。支持多 Agent 分布式会话、通信与协同共识。',
    details: [
      '设计支持 Agent 多信道通信。',
      '包含协作共识算法，用于分布式任务决策。'
    ]
  },
  'bp-tiangan': {
    statusText: 'Planned (已规划待开发)',
    statusColor: '#64748b',
    desc: '天干地支时间记忆轮转 ( tgdz-cycle )。基于天干地支时间律动态轮转长短期记忆索引，调频模型敏感度和进化节律。',
    details: [
      '基于时间地支节律动态轮转长短期记忆索引。',
      '设计智能体时间生物钟，调频模型敏感度和进化节律。'
    ]
  },
  'bp-centralbrain': {
    statusText: 'Completed & Verified (已完成并校验)',
    statusColor: '#22c55e',
    desc: '中央大脑控制核心 ( central-brain )。作为全局意志控制中枢，负责多任务并发调度、Agent 对话与共识决策、以及全局资费预算风控。',
    details: [
      '全局意志控制与运行监督，实现多任务执行生命周期 (Session) 全局管控。',
      '集成 Agent 间信道通信与 FIPA-ACL 契约网招投标的共识决策中枢 (Consensus Resolution)。',
      '内置全局三级资费与 Token 预算安全熔断机制 (Safeguard Circuit Breaker)。'
    ]
  }
};

export const LogTelemetry: React.FC<LogTelemetryProps> = ({
  selectedNode,
  selectedNodeId,
  setSelectedNodeId,
  filteredLogs,
}) => {
  const isBpNode = selectedNodeId?.startsWith('bp-');
  const bpInfo = isBpNode && selectedNodeId ? BLUEPRINT_DESCRIPTIONS[selectedNodeId] : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <h3 style={{ fontSize: '13px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Terminal size={14} style={{ color: isBpNode ? '#c084fc' : '#a78bfa' }} />
          {isBpNode && bpInfo 
            ? `Blueprint: ${selectedNode.data?.name}` 
            : selectedNode 
              ? `CoT: ${selectedNode.data?.name}` 
              : 'CoT Log Telemetry'}
        </h3>
        {selectedNodeId && (
          <button
            onClick={() => setSelectedNodeId(null)}
            style={{
              fontSize: '9px',
              padding: '2px 8px',
              borderRadius: '4px',
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'rgba(255,255,255,0.6)',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            Show All
          </button>
        )}
      </div>
      
      {isBpNode && bpInfo ? (
        <div className="glass-card" style={{
          flex: 1,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          padding: '16px',
          background: 'rgba(10, 13, 22, 0.4)',
          border: '1px solid rgba(168, 85, 247, 0.1)'
        }}>
          <div>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', display: 'block', marginBottom: '2px' }}>
              Lifecycle Status / 状态周期
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: bpInfo.statusColor, boxShadow: `0 0 10px ${bpInfo.statusColor}` }} />
              <span style={{ fontSize: '12px', fontWeight: 700, color: bpInfo.statusColor }}>
                {bpInfo.statusText}
              </span>
            </div>
          </div>

          <div>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', display: 'block', marginBottom: '4px' }}>
              Component Description / 模块描述
            </span>
            <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.85)', lineHeight: '1.6', margin: 0 }}>
              {bpInfo.desc}
            </p>
          </div>

          <div>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', display: 'block', marginBottom: '6px' }}>
              Key Technical Features / 关键技术特性
            </span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {bpInfo.details.map((detail, idx) => (
                <div key={idx} style={{ fontSize: '11px', color: 'rgba(255,255,255,0.7)', lineHeight: '1.5', paddingLeft: '8px', borderLeft: '2px solid rgba(168, 85, 247, 0.3)' }}>
                  {detail}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="glass-card" style={{
          flex: 1,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '10px',
          background: 'rgba(0, 0, 0, 0.3)',
          fontFamily: 'var(--font-mono)'
        }}>
          {filteredLogs.length > 0 ? (
            filteredLogs.map((log) => (
              <div key={log.id} className="log-stream-line">
                <span style={{ fontSize: '9px', opacity: 0.4, marginRight: '6px' }}>[{log.time}]</span>
                <span className={log.type}>
                  {log.type === 'thought' && '💭 [Thought] '}
                  {log.type === 'tool' && '🔧 [Tool] '}
                  {log.type === 'observation' && '📊 [Observation] '}
                </span>
                <span>{log.text}</span>
              </div>
            ))
          ) : (
            <div style={{ padding: '20px', textAlign: 'center', color: 'rgba(255,255,255,0.2)', fontSize: '11px' }}>
              No logs recorded for this module.
            </div>
          )}
        </div>
      )}
    </div>
  );
};
