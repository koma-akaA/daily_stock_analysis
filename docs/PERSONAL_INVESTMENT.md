# 个人微信每日投资研究

本 Fork 基于 ZhuLinsen/daily_stock_analysis，保留原版主要功能。个人研究入口是 `scripts/personal_investment.py`，工作流是 **每日投资分析（个人微信）**。新增加密适配仅用于本入口；原版 Web/API/自选股解析仍是股票语义，不能在那里直接输入 BTC/ETH 并假定是加密资产。

## 日常使用

1. 个人微信关注 **pushplus 推送加**，官网 https://www.pushplus.plus 微信扫码登录并按官方要求完成实名，打开接收消息。
2. 在仓库 Settings → Secrets and variables → Actions 的 Repository secrets 中保存 `PUSHPLUS_TOKEN`。推荐专用消息 Token；不使用企业微信 Webhook，不使用个人微信逆向登录。
3. AI Key 至少一个。当前已验证的 DeepSeek 预设：Secret `DEEPSEEK_API_KEY`，Repository variable `LITELLM_CONFIG=config/personal-investment-llm.yaml`、`LITELLM_MODEL=investment`。预设模型可在 YAML 中调整；Key 仅通过 `os.environ/DEEPSEEK_API_KEY` 引用。关闭默认 thinking 是为避免短 JSON 输出预算被推理耗尽。
4. `INVESTMENT_ASSETS` 是 Repository variable，默认 `CRCL,HOOD,COIN,TSLA,BTC,ETH`。CRCL始终优先分析，只代表Circle美股；BTC/ETH是明确登记的Coinbase现货交易对，不查询同名链上代币。
5. Fork首次需要在Actions启用工作流；仓库应允许该工作流的 `GITHUB_TOKEN` 写入代码内容，用于独立的 `investment-history` 报告分支。分析不修改主分支。
6. 手动测试：Actions → 每日投资分析（个人微信）→ Run workflow → `mode=push-test`。收到公众号通知后打开全文，核对中文、换行和链接。`mode=analysis` 执行完整分析；`no_notify=true` 只生成报告；当天已推送需要再次发送时才勾选 `resend`。

## 密钥与数据服务

| 配置 | 获取/用途 | 费用与权限 |
|---|---|---|
| `PUSHPLUS_TOKEN` | https://www.pushplus.plus 一对一消息/专用消息Token | 官方微信渠道免费额度；需实名。只有通知权限，无证券账户权限 |
| `DEEPSEEK_API_KEY` | https://platform.deepseek.com/api_keys | 按Token计费；不是ChatGPT订阅，需自行检查余额与限额。不会替用户充值 |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | 原版支持的可替换AI服务 | 按服务商套餐；更换时同时移除/调整本Fork的DeepSeek预设变量，避免配置优先级覆盖 |
| `TAVILY_API_KEYS` | https://app.tavily.com | 可选新闻搜索；优先利用账户免费额度，是否需要绑卡/超额计费以控制台为准 |
| `SERPAPI_API_KEYS` / `BRAVE_API_KEYS` | https://serpapi.com / https://api-dashboard.search.brave.com | 可选搜索替代；按服务商套餐，不能将搜索摘要等同于已证实新闻 |
| `SOCIAL_SENTIMENT_API_KEY` | https://api.adanos.org/docs | 可选，复用原项目的美股Reddit/X/Polymarket聚合模块；需检查覆盖、来源授权、配额及价格。不代表所有社区样本 |
| `COINGECKO_DEMO_API_KEY` | https://www.coingecko.com/en/api | 可选免费Demo，用 `bitcoin` / `ethereum` 的明确ID补充加密市值；绝不需要交易所Key或钱包私钥 |

所有 Key 都放 Repository secrets，不放 Variables、不写 `.env.example` 实值、不写日志。模型名、资产列表和配置文件路径可以放 Variables。GitHub内置 `GITHUB_TOKEN` 由Actions注入，不需要另建长期PAT用于日常分析。

Adanos Key/URL的工作流映射、已确认的 `REDDIT_SECRET` 兼容名，以及CRCL/HOOD低请求量接口测试见 [研究接口检查](RESEARCH_API_CHECK.md)。

## 报告真实性与口径

- 美股日线复用YfinanceFetcher，技术指标复用StockTrendAnalyzer；免费Yahoo数据可能延迟、限流或缺字段，不承诺交易所级实时行情。美股“当前价格”明确标注为最近已收盘日线，不冒充实时盘中价。
- CRCL基本面快照核验 `quoteType=EQUITY`、USD和Circle公司名称。CRCL不走加密接口。Yahoo证券身份/基本面不可用时分别记录缺项；不会自行补财报。
- 加密现货使用Coinbase Exchange只读公共GET接口；涨跌口径为24h，日线指标采用已完成UTC自然日，剔除正在形成的K线。量为Coinbase单一市场成交量，不是全市场量。
- 市值/PE/Forward PE/P/S为供应商最新快照，字段时点未必与价格一致；Forward PE是预期，不是已发生业绩。加密资产无股票PE。CoinGecko Key未配置时，加密市值显示不可用。
- MA5/10/20/60必须有足够历史；不足60根不拿MA20代替MA60。RSI沿用项目6/12/24期Wilder EMA口径，MACD为12/26/9，柱值沿用原项目定义。
- 双均线使用MA20/MA60，区分新交叉与已经处于上/下方。右侧候选同时要求价格高于MA20/MA60且MA20上行；左侧和过渡状态不等同于确定性交易指令。
- 支撑/压力复用原项目并补充MA5/10/20/60与近20根日K高低点，选参考价格两侧最近的候选。股票参考最近收盘，加密参考当前现货快照；候选并非确定性底部/顶部。止损参考为最近支撑减去ATR14简单均值，属于计算参考，跳空可越过。没有支撑或历史不足时显示不可用。
- 股票日线必须覆盖连续的实际NYSE交易日；加密日线必须连续。过期、非有限数、缺日线或不一致OHLC不能参与技术判断。模型不生成报价、指标数值或外链。
- Yahoo带日期新闻优先，缺失时使用已配置的原版搜索服务，新闻须有HTTPS来源与近三日发布时间。拿不到时显示不可用；这不等于当天没有重要新闻。
- 未配置社交服务或无覆盖时，Reddit/X显示不可用，不写“情绪中性”。当前加密社区数据未接入，不能拿美股BTC同名代码的社交数据替代。
- 客观数据/规则计算和AI推断分区；AI解读须引用输入中的证据键，数字统一由Python展示。没有连续财报对比时，基本面变化明确显示不可用；不能用价格变化推断基本面改善。
- 均线高低、价格所在位置和MACD正负由程序计算为固定证据；AI只能选择证据键并解释研究含义，不能在自由文本中改写技术事实。措辞违规最多调用模型修正一次，仍违规则AI状态不可用；不会把比较关系说反的文本当作成功报告。
- 完整报告分别列长期逻辑、估值、风险、潜在催化和观察条件，以及现货波段趋势、双均线、支撑/压力、止损参考和趋势失效条件。不接入自动交易或用户持仓。

## 调度、节假日与失败

- 默认北京时间周二至周六 **08:30**；对应UTC `30 0 * * 2-6`。10:15补查对应 `15 2 * * 2-6`。北京时间没有夏令时。
- `exchange-calendars` 的XNYS日历按纽约时区查找最近已收盘交易日，覆盖美国夏令时、节假日和提前收市；留15分钟收盘缓冲。美股非交易日沿用最近收盘并标注，仍生成当天加密研究。日历错误直接失败。
- 定时任务只有北京时间周二至周六08:00至14:00前允许执行，防止严重延迟任务在下午/夜间发送过期“早报”；手动运行不受此限制。
- GitHub可能延迟或丢弃定时任务，两个时间点降低单次漏跑概率，不承诺08:30准点或永不漏跑。公共仓库长时间无活动（官方规则为60天）可能停用定时，需要检查Actions提示；本项目不依靠虚假提交维持活跃。
- 原版 `每日股票分析` 的18:00 schedule在此Fork移除，保留手动入口，避免使用默认A股列表重复通知。
- 使用workflow concurrency串行；`investment-history/state/日期.json` 以Git引用非强制更新先认领、后发送。认领写入失败不发送；超时/进程中断也保留认领，避免10:15或重跑再次发送。代价是崩溃可能漏发，应检查后显式勾选resend。
- 这是至多一次自动发送尝试，不是严格的exactly-once送达保证。不要删除认领记录来盲目重试，先检查PushPlus最新请求。
- HTTP/数据源异常按字段降级并保留质量信息；AI缺失、关键行情/指标缺失或推送失败使该次任务失败，不伪装为全部成功。新闻/社交/可选市值缺失会在报告明示。

## PushPlus具体限制

截至本次核对，官方文档列实名普通用户微信渠道每日200次、每分钟5次、同内容每小时3次，标题100字、内容2万字。错误请求也可能计入次数。配额可变化，以 https://www.pushplus.plus/doc/help/limit.html 为准。

发送使用HTTPS POST JSON和 `channel=wechat`，不在URL携带令牌。原模块的字节预算比官方字数限制更保守；日常发一条简报并链接全文。长消息分片间隔至少13秒，某片失败后立即停止。完整内容超预算时截短摘要并保留历史入口。

同步 `code=200` **仅表示已受理**，不能标记最终微信送达。保存状态 `accepted/rejected/unknown`，不在可能公开的历史分支保存可访问消息的短链码。最终送达应在微信/PushPlus“最新请求”核验。官方状态查询需要额外开放接口密钥、安全IP白名单；GitHub共享runner无固定出口，不为此扩大权限或自动配置白名单。

合规替代：Server酱³、WxPusher等公众号订阅渠道需分别核对服务与账号认证；原项目的Server酱³可复用。邮件可作为备用并可在微信QQ邮箱提醒中接收通知，但不是个人微信机器人。企业微信Webhook只属于企业微信，不作为本方案的个人微信接口。

## 历史、保密与回滚

- 完整Markdown及证据JSON存入 `investment-history/reports/日期/运行编号.*`，微信提供GitHub报告链接；公共Fork的历史也是公开的，只包含公共市场资料，不保存持仓、账户信息或任何Key。
- Actions artifacts保留30天，含全文、证据JSON、HTML手机宽度预览、通知状态。Git历史保留更久；本项目不会擅自删除历史。
- GitHub页面在微信内可打开，网络可达性取决于接收端环境；私有仓库需要GitHub登录。没有为了手机页面购买服务器或开启公开Web服务。
- 回滚：禁用个人工作流，保留历史；如需恢复原版日常分析，先确认STOCK_LIST和通知渠道，再恢复原workflow的schedule，避免两个定时入口同时启用。

## 增加标的

在Repository variables修改 `INVESTMENT_ASSETS`，例如 `CRCL,HOOD,COIN,TSLA,AAPL,BTC,ETH`，不用改代码。上限15个，防止请求和长消息失控。仅支持美股标准ticker（包括一位类股后缀）和已注册BTC/ETH。新增其他加密资产必须在加密适配器中登记Coinbase交易对与CoinGecko ID，并补身份/日线测试，不能只把同名代码放入股票列表。

## 微信互动问股：评估方案，未部署

目前只交付定时/手动分析与通知。普通个人微信没有可任意接管好友聊天的官方机器人接口，禁止外挂、逆向协议或扫码托管个人号。

1. **优先：微信通知→移动Web问股。** 复用原项目FastAPI和 `/chat` 工作台，在独立托管服务上持续运行，设置HTTPS、认证、请求限额与AI费用上限。现有GitHub历史浏览无需新增固定服务器成本；实时交互需要常驻服务，GitHub Actions不能充当公网HTTP服务。
2. **公众号关键词交互。** 使用自己公众号实际获批的官方消息接收/客服回复接口和回调服务器。能否自动回复、认证要求与会话限制取决于账号类型和平台权限；不能假定个人订阅号等同于认证服务号。PushPlus发送Token本身不提供通用的“分析CRCL”聊天机器人接口。
3. 成本在选定供应商前核对：可能包含主机月费、域名年费、AI按量费及公众号相关认证/服务费用。可先试免费托管额度；可靠常驻运行通常需付费。本次没有购买或开通任何收费服务。

## 本地验证命令

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest flake8
LITELLM_CONFIG=config/personal-investment-llm.yaml LITELLM_MODEL=investment \
  .venv/bin/python scripts/personal_investment.py --no-notify --no-history
.venv/bin/python -m pytest -q tests/test_personal_investment.py tests/test_pushplus_safety.py tests/test_investment_history.py tests/test_notification_sender.py
```

`--no-history`只用于显式本地测试，生产保留GitHub持久化认领。真实验收结果、失败记录与未验证项见交付验收报告；不能将mock测试替代真实微信收件。

本指南针对个人中文部署；原版英文文档保留通用产品说明，没有将本Fork独有行为推广为上游全局能力。
