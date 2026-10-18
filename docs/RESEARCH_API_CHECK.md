# CRCL / HOOD 舆情与新闻接口验收

适用于本个人Fork。原版入口 `.github/workflows/00-daily-analysis.yml` 保留手动分析；每日调度仍由 `01-personal-investment.yml` 负责，不增加第二个定时入口。

## 配置

两个工作流都映射如下配置，实际Python配置统一使用左侧名称：

| 环境变量 | GitHub来源 |
|---|---|
| `SOCIAL_SENTIMENT_API_KEY` | Repository secret同名优先；兼容此部署已确认存放Adanos Key的 `REDDIT_SECRET` |
| `SOCIAL_SENTIMENT_API_URL` | 同名Secret优先、Variable其次，默认 `https://api.adanos.org` |
| `TAVILY_API_KEYS` | 同名Repository secret；可选，多个用逗号分隔 |

`REDDIT_SECRET`别名只接受Adanos Key的语义，不能放Reddit官方OAuth client secret。Reddit OAuth不会自动授予X或Adanos访问权限。URL须为HTTPS根地址，不能带 `/docs`、路径、查询参数或密码；重定向不转发Key。个人日报已修正为将URL传给服务。未配置Tavily时标为未测试，不能声称已接入新闻搜索。

## 修复的接口契约

[Adanos官方OpenAPI](https://api.adanos.com/openapi.json)提供：

- `GET /reddit/stocks/v1/stock/{ticker}`；原代码的 `/report/{ticker}` 不在现行契约中。
- `GET /x/stocks/v1/stock/{ticker}`；直接查询CRCL/HOOD，不用热门榜过滤替代个股覆盖。
- 使用 `X-API-Key` 请求头。HTTP 200且 `found:false` 表示缺少该窗口的有效数据，不解释为情绪中性。缺字段不填零；真实零情绪值保留。

请求结果和失败缓存10分钟，并合并并发相同请求；等待超时不另发重复请求。401/429或已知月额度为零时，本实例不再继续请求。只对网络错误保留最多两次GET尝试，不对HTTP错误盲目重试。个人日报仅请求Reddit/X；原版入口仍可使用其Polymarket功能。

服务只记录HTTP状态和白名单额度数字，不记录请求头、原始响应或异常正文；Tavily错误日志也不再打印Key前缀。Tavily采用 `basic`、关闭自动参数升级、启用用量返回，鉴权或额度错误的Key在当前实例中停用。新闻成功但过滤为空也缓存，避免相同空查询重复计费。

## 实际运行检查

在Actions → 每日股票分析 → Run workflow → `mode=api-check`。新脚本 `scripts/check_research_apis.py` 使用项目配置和现有服务，固定检查CRCL与HOOD；只调用数据接口，不调用AI、不发送微信、不执行交易。

- 正常最多4个Adanos请求，重复调用由缓存响应，不额外请求热门榜、Polymarket、解释模型或全文提及接口。
- 若配置Tavily，仅检查第一个Key：先 `GET /usage`，每个标的一次新闻搜索并验证缓存，最后再查一次用量。最多两次basic搜索，不轮询其他Key。已知额度不足时停止，不自动消耗额外pay-as-you-go额度或更换套餐。
- 只输出存在性、状态、覆盖、提及数、情绪分数、可用新闻来源/日期、缓存验证和数字用量。缺钥显示 `not_tested`；鉴权、网络和额度失败显示真实状态。只有Adanos配置时整体为 `partial_tavily_not_configured`，不把Tavily标为成功。
- 结果：Actions artifact `analysis-reports-运行序号` 内的 `reports/api-check/result.json`。不输出密钥或密钥前缀，响应文本中的完整Key也作最后脱敏。配额数字可能随账户其他调用变化，不能当作当前实时余额。

## 额度口径

Adanos从正常受保护响应读取 `X-RateLimit-Limit-Monthly`、`Remaining-Monthly`、`Used-Monthly` 等头，不为查额度额外请求业务接口。官方月额度按账户窗口重置，不假定每月一日；见[官方更新记录](https://api.adanos.com/changelog)。未来正常四只美股每天各两次舆情请求，约8次/天，另加手动检查与网络重试；BTC/ETH社区当前仍未接入，不能误用股票接口。

Tavily使用[官方Usage接口](https://docs.tavily.com/documentation/api-reference/endpoint/usage)分别显示Key/账户已用与上限；[搜索接口](https://docs.tavily.com/documentation/api-reference/endpoint/search)返回单次credits。没有Key就无法检查真实额度，不能把公开套餐配额当作该账户余额。未开通充值、升级、自动交易或其他收费服务。

回滚可恢复前一提交；接口检查模式可停用，日常调度可单独禁用。中文个人部署说明不改变上游通用英文文档。
