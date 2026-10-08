# 数据治理(Data Governance)设计

- 日期:2026-09-20
- 状态:已与用户对齐,待实施
- 背景:系统 26+ 定时 job 写约 25 张表,但无任何数据健康体检、job 失败无通知无状态记录,存量脏点(legu 孤儿行、sw 双源混杂、change_pct 历史为 0)无清理路径。曾发生 stock_valuation 漏跑两周无人察觉。

## 已确认的决策

| 决策点 | 结论 |
|---|---|
| 治理形态 | 分阶段全都要:大扫除 → 监控告警 → 自愈闭环 |
| legu 孤儿行 | CSV 备份后删除,读侧过滤保留作防御(2026-09-20 实测修正规模为 17,258 行、含 2005-2017 独占历史,**待用户按新规模重新确认**) |
| 告警触达 | Feishu + 站内健康页双通道 |
| 监控架构 | 方案A:代码内声明式检查框架 + 结果落库 + APScheduler 事件监听 |
| 健康页挂载 | system-logs 页扩双 Tab(日志/数据健康),不加菜单项 |
| 自愈上线 | 先干跑一周(只建议+审计,不动表),确认无误报后开真回补 |

## 阶段一:存量大扫除(纯修复,无新功能)

### 1.0 现役断线修复(2026-09-20 DB 实测发现,优先于一切)

实测 max(日期) 与 job 应写频率对照,确认以下断线(而 K 线/资金流/国家队/业绩预告均正常,说明服务在跑、是部分 job 失败):

| 表 | 断线起点 | 对应 job | 备注 |
|---|---|---|---|
| north_flow_daily、margin_balance_daily | 2026-08-18 | market_sentiment_daily(每日17:00) | 两表同日断,job 整体失败;注意北向数据可能是外部停发(结构性失败) |
| stock_valuation | 2026-09-02 | fundamentals_weekly(周六03:00) | 09-06/09-13 两个周六均未写入 |
| industry_pb_break_daily、industry_prosperity_daily | 2026-09-02 | 每日 16:40 / 17:20 job | 与 stock_valuation 同日断,疑似共同依赖失效 |

动作:逐 job 诊断根因(akshare 接口变更 / 依赖异常),修复后按缺口日期回补;若属外部源停发,标记为结构性失败——只做口径注记+告警,不假装能自愈。stock_shareholder_count(08-18)与 stock_financials(06-30)是报告期口径天然稀疏,不算断线,诊断时确认写入侧即可。

### 1.1 legu 孤儿行清理(规模已按实测修正,待用户重新确认)

- 对象:`index_valuation_daily` 中 `source='legu'` 的 **17,258 行**(2026-09-20 实测;此前按 ~1929 行估计是单指数天数,非总行数),覆盖 2005-01-05 ~ 2026-08-14。
- **风险披露**:computed 口径仅 701 行、2018-01 起、月度粒度;legu 行含有 2005-2017 computed 从未覆盖的独占历史。删除后库内不再有 2018 年前的指数估值,CSV 备份是唯一存档。所有 index 侧读点已过滤 computed,故线上功能不受影响。
- 动作:导出全量到 `backend/reports/legu_orphan_backup_<date>.csv`(校验行数),DELETE;读侧 computed 过滤保留作防御。
- 验收:`count(source='legu') = 0`;回归测试 `tests/api/test_index_pe.py::test_legu_source_rows_excluded` 仍通过。

### 1.2 sw 估值表双源口径统一(实测两源零重叠,原诊断设计不可行,已重写)

实测(2026-09-20):computed 11,973 行、1992-03 ~ 2026-08-17、**月度粒度**;akshare 806 行、2026-08-07 起、**日度粒度**;两源**零个 (code, day) 精确重叠**。原"重叠日期偏差 ≤5% 分支"前提不成立,且"读侧统一 computed 为主"会丢失日度粒度、且 computed 未延伸到今天。

修订后的统一目标:**computed 口径日度化并延伸至今**——扩展每日 job 复用 index 侧成分股聚合链路,为申万行业每日计算 computed 估值;诊断阶段用**最近邻日期匹配**(akshare 日度值 vs computed 最近一期,|Δt| ≤ 10 日)校验自算口径与乐咕口径的偏差:
- 中位偏差 ≤5%:读侧统一 computed(补齐三个漏过滤点:`get_sw_range` 加 source 参数、分位端点 sw 分支、批量分位、行业评分输入 `get_sw_valuation_window`),akshare 保留写入作对照。
- 中位偏差 >5%:先解释偏差来源(整体法加权 vs 乐咕官方口径),在端点披露口径差异后再统一,不盲目二选一。
- 省工程备选(若日度化链路成本超预期):历史月度 computed + 2026-08 后日度 akshare 的**拼接口径**,读侧拼接并标注切换点,分位数分段计算;需用户接受口径断点。

### 1.3 change_pct/amplitude 历史修复

- 跑既有 `scripts/fix_market_data_quality.py fix-change-pct` 一次,抽样(含已知除权日)验收,不重建设施。

### 1.4 /system/status 假覆盖率修复

- 撤掉 `_backfill_progress` 中恒 100% 的占位 coverage(`api/router/system_router.py:124-146`);阶段二 data_health 上线后接真值。

### 1.5 进度文件收敛

- 实测更正:ProgressTracker 仍被 fundamentals_weekly、financial_full_sync、portfolio_daily 等活跃 job 用于断点续传,不存在"无人引用"。
- 动作改为:设计滚动清理/压缩(按 job-key 保留近期状态)或迁移 DB;不删除活动状态。`.news_backfill_progress.json` 是 news_backfill.py 的活动状态文件,保留不动。

## 阶段二:监控与告警

### 2.1 job 执行留痕

- 新表 `job_run_log`(job_id, started_at, finished_at, status, error_summary, duration_ms),沿用 create_all 模式建表(本项目无 Alembic,不在此引入)。
- `src/infra/scheduler.py` 注册 APScheduler `EVENT_JOB_EXECUTED` / `EVENT_JOB_ERROR` 监听器写表;轻量,不侵入各 job 函数。
- `/system/scheduler` 端点补 last_run、近 30 天成功率。
- 保留策略:留 180 天(与 data_health_result 一致,清理挂进体检 job 收尾)。

### 2.2 data_health 检查框架(方案A)

- 新模块 `src/domain/market/health/`:`registry.py`(装饰器注册)+ `checks/`(按领域分文件)+ `runner.py`。
- 规则产出:`check_id`、`table`、`severity`、`status(ok/warn/fail)`、`metric`(jsonb)、`message`。
- 体检 job `data_health_daily`:每日 **18:30**(更正:原定 17:45,但 macro_validate 每日 18:00 仍写 macro_view,17:45 不在所有写入 job 之后)统一跑,结果写 `data_health_result`(check_id, checked_at, status, metric, message)。
- 初始规则集(约 12 条,按表):
  - freshness:核心日频表(stock_valuation/stock_ohlcv/行业三件套/north_flow 等)距最新交易日 ≤2 交易日;周频表 ≤9 天;月频 ≤35 天。
  - coverage:stock_valuation 近 5 日平均行数 vs 90 日基线,骤降 >30% 告 warn——**披露门控白名单除外**(财报季 PE 断线是 `fundamental/index_pe.py` 80% 门控的设计内行为,检查需引用白名单跳过或降级为 info)。
  - gap:日频序列缺日检测。
  - 零值:关键列全零检测(change_pct 事故的通用化)。
  - orphan:表内 source 遗留检测(legu 类问题复发即报)。
- 规则纯函数化(输入连接/日期上下文,输出 CheckResult),可单测。
- 上表为规则**类型**;覆盖哪些表、各自的频率与容忍度,在实施计划中逐表枚举成清单,不留在代码里临时挑。

### 2.3 Feishu 通知

- 复用 `src/infra/notification/feishu.py`(env 已备)。
- **边沿触发去重**:ok→fail/warn 推异常卡片(表+指标+建议动作);fail→ok 推恢复;持续 fail 不重复推。同一 job 连续失败只推第一次。
- 去重状态从 `data_health_result` / `job_run_log` 历史推导,不另设状态表。

### 2.4 站内健康页(system-logs 双 Tab)

- Tab1 日志:现状不动。Tab2 数据健康:检查结果按表分组红黄绿、job 成功率、缺口清单。
- 新端点 3 个:`GET /system/data-health`(summary+明细)、`GET /system/data-health/history/{check_id}`(单检查历史)、`GET /system/jobs/runs`(分页 job 运行记录)。

## 阶段三:自愈闭环

- 检查规则可挂 `heal` 动作;heal **复用各 domain 现有 sync 函数**回补,不重写拉取逻辑。
- **干跑模式**:上线首周 heal 只推 Feishu 建议 + 写审计,不动表;一周无误报后切真回补(配置开关)。
- 安全阀:每表每日回补窗口上限 30 天;单次体检最多触发 5 个 heal;heal 写 `heal_run` 审计表(check_id, target, window, rows, status, mode)。
- 升级:同一检查连续 3 天 fail 且 heal 无效 → Feishu 推"需人工"卡片。
- 明确不自愈:K 线类已有周六 `quant_weekly_catchup` 兜底,不重复建;外部源接口结构性失败(akshare 接口变更)只告警不重试。

## 横切

- 测试:检查规则单测(门控白名单、边沿去重、安全阀、干跑开关);sw 统一后三个读点回归测试;legu 清零断言。
- 不引入 Alembic、不动 DSN/凭据;新表走 create_all + main.py ALTER 兜底惯例。
- 验收:
  - 阶段一:4 条现役断线修复并回补(或定性为结构性失败并注记);legu=0;sw 读点全带口径且有测试;change_pct 非零率抽检通过。
  - 阶段二:人为停一个 job 两天,健康页与 Feishu 均可见异常与恢复。
  - 阶段三:干跑周内无动作;开启后手动删除几日数据能自动补回且审计有记录。

## 明确不做(YAGNI)

- DB 配置化规则引擎/前端编辑(方案B)。
- 无状态现算健康页(方案C)。
- Alembic 迁移体系。
- 分钟线级实时监控(体检日频足够)。
