# AgentArts 独立部署与使用说明

本目录为新增的平台适配层。原 src、原测试、原启动脚本、原8765端口和原项目数据保持不变。适配层导入同一核心代码，不维护另一份业务实现。修改前的本地代码基线位于 runtime/baselines，latest.json 包含原文件哈希，可逐项核对。

## 当前交付边界

已提供：标准HTTP入口、独立可视化本地预览、平台模型代理或MaaS鉴权适配、会话隔离、持久化快照、ARM64镜像构建文件、干净源码导出工具与配置说明。

未完成：真实模型联调、Docker镜像实际构建、SWR上传和平台部署、完整公共网页鉴权接入、Windows远程执行端。它们需要实际账号资源和构建环境。不能把源码ZIP当作已构建镜像，也不能把本地预览当作线上部署。

云端首版范围为需求分析、资料工具、约束与文档交付。代码执行、Keil、MCU工具和USB均在云端明确禁用，需后续本地执行端。原本地完整工作台仍保留这些能力。平台默认镜像只含通用知识卡片；完整手册须另行选入源码包，不能声称默认镜像已包含全部本地知识库。

## 现在需要安装客户端吗

SWR客户端不是必装。镜像可以通过网页上传，也可以docker push。

但必须先有Docker构建环境，才能把代码变成镜像。两种选择：

1. 已有ARM64 Linux机器：解压干净源码包，在该机器安装并使用Docker和Buildx。
2. 本机安装Docker Desktop并启用Linux容器及linux/arm64构建支持；这涉及系统组件和资源，本文不自动安装。先完成本地Python预览，再决定是否安装。

不需要现在购买服务器。没有Docker时，本项目仍可运行本地工作台和平台适配预览。

## 本地使用 两个入口分别保留

原智能体：继续双击根目录 start-workbench.cmd，地址 http://127.0.0.1:8765/。

平台适配预览：双击本目录“启动平台适配预览.cmd”，地址 http://127.0.0.1:8786/。新预览使用 runtime/agentarts-preview 保存独立会话快照；不会加载或迁移旧项目。首次可不配置模型，页面会显示“模型未接入”，而不会返回预设分析。

停止预览不会停止原服务。预览PID记录于 runtime/agentarts-preview/preview.pid；需先核对其命令行为 deployments.agentarts.app 再停止对应进程，不要结束所有Python进程。模型配置修改后需重启这个预览进程；再次双击仅复用已有健康服务，不会自动重启。

## 创建账号资源的顺序

1. 在计划参赛的实际区域开通AgentArts并完成必要服务授权；不要把示例区域当成账号已开通区域。
2. 在SWR建立组织，例如选择你自己的队伍名称。组织名用于管理镜像，与Agent名称、模型名称不是同一项。
3. 在AgentArts的模型页面配置模型提供商/代理，或在MaaS获取可用模型服务。记录实际模型名、完整Chat Completions地址及鉴权请求头。免费控制台调测额度不代表任意自研程序都已获得可调用接口，以账号实际开放能力为准。
4. 本地用模型配置向导验证输入，再明确点击预览页面“开始分析”才会发模型请求。
5. 准备ARM64镜像并上传SWR。
6. 镜像可选后再创建托管运行时。先不要在镜像栏仍为空时点击“立即托管”。

不要将模型密钥、SWR登录凭据和运行时入站密钥混用：

| 凭据 | 用途 | 放在哪里 |
|---|---|---|
| 模型API Key | Agent调用模型 | 本机忽略目录或控制台运行时环境配置 |
| 运行时入站API Key | 用户/客户端访问线上Agent | API调用客户端或后端；不固化进公共前端 |
| SWR登录凭据 | 推送容器镜像 | Docker登录工具；不写入镜像或源码 |

## 配置模型

双击“配置平台模型.cmd”。完整接口地址、模型名和鉴权头必须来自你自己的控制台；不要把运行时 /invocations 地址当模型地址。

向导在终端隐藏输入密钥，保存到 runtime/agentarts-local-config.json。此文件含明文密钥，不分享、不上传；根目录现有runtime忽略规则和源码打包白名单会排除它。向导只保存配置，不执行模型请求，不改变原本地智能体的EMBEDDED_AGENT_*环境变量。

- MaaS直连：通常使用Authorization头，值由代码组合为Bearer加密钥；完整路径需包含实际Chat Completions路径。
- AgentArts模型代理：按控制台真实配置填写请求头名称，前缀留空；不能默认一定是Bearer。
- JSON模式不支持时，可将本地配置中的 CLOUD_MODEL_JSON_MODE 改成字符串0；仍要求模型输出JSON对象，是否稳定需要实测。

程序只接受HTTPS模型地址，不跟随鉴权重定向。配置文件不会被复制到镜像。当前没有真实凭据，因此尚未验证接口联通或独立模型解决未知任务的效果。

## 导出源码与制作镜像

从项目根目录执行（python指本机可用的Python 3.11及以上）：

```text
python deployments/agentarts/package_source.py
```

输出 runtime/agentarts-release/embedded-agent-agentarts-source.zip 和同名干净目录。该ZIP是源码交付包，不可上传到SWR镜像上传页。它不含个人项目、运行记录、依赖缓存、密钥或本地Keil。

若要完整官方手册，另指定新目录：

```text
python deployments/agentarts/package_source.py --include-official --output runtime/agentarts-release-full
```

完整资料体积较大，应核对资料的使用与分发范围。原始手册和页码文件可打包，检索索引在云端临时盘重建，不把SQLite放在会话FUSE挂载目录。默认轻量包不会伪造缺失资料。

将干净目录传至Docker构建环境，进入目录执行：

```sh
export IMAGE=embedded-engineer-agent:0.1.0
sh deployments/agentarts/build-image.sh
```

脚本需要Docker及Buildx，明确构建linux/arm64并检查Architecture，然后用docker save生成 embedded-engineer-agent-arm64.tar。脚本不登录SWR、不购买资源、不自动部署。源码包、Dockerfile、普通项目tar均不是容器镜像归档。

若要本地容器验证（在构建环境中）：

```sh
docker run --rm -p 8080:8080 \
  -v agentarts-session:/home/session \
  -e CLOUD_STORAGE_MOUNT=/home/session \
  -e CLOUD_STATE_DIR=/home/session/embedded-engineer \
  embedded-engineer-agent:0.1.0
```

模型未配置也能检查标准入口与明确的未接入提示。容器不能直接接收公网流量，应放在配置入站认证的平台网关后。云入口启动时检查挂载点；缺少会话存储会拒绝启动，避免将临时磁盘误当持久化。

## 对照你的截图填写控制台

| 页面项目 | 本版本建议 |
|---|---|
| 名称 | embedded-engineer-agent-v1，可按队伍命名规则修改 |
| 描述 | 自研嵌入式工程Agent，支持需求分析、证据追溯、工具编排与文档交付 |
| 来源镜像 | 选择刚上传的ARM64镜像及固定版本标签；不要填写本地路径或源码ZIP |
| 委托 | 已有默认运行时委托，先检查控制台所需权限；不额外授予管理员权限 |
| 入网配置 | 账号中已创建且可用的网关；截图defaultgw需确认在当前区域可用 |
| 入站协议 | HTTP |
| 入站认证 | API Key，记录控制台给出的实际头名称与值；不要照抄截图默认选中的IAM而不准备签名 |
| 日志 | 初次连通可暂关LTS；需要诊断和比赛展示时按实际资源开通，确认费用与日志脱敏 |
| 空闲超时 / 最大存活 | 首次可保持截图15分钟/24小时；不代表会话永久保留 |
| 实例规格 | 首次可保持截图2000mCPU/8192MiB，之后根据测量调整 |
| 出网 | 首次公网，便于模型接口访问；私网代理需按实际VPC配置 |
| 会话存储 | 勾选，挂载路径填写 /home/session；未启用会导致应用拒绝启动 |
| SFS Turbo / OBS挂载 | 当前公网首版不用；不把灰色选项当成已配置 |
| 启动命令 | 留空，使用镜像CMD；如需填写，使用 python -m deployments.agentarts.app |
| 监听端口 | 8080 |
| 路由 | 前缀匹配，为后续健康检查、UI与自定义接口保留入口 |
| 文件上传下载 | 若准备上传资料、下载会话产物，可创建时开启；程序自身也有文档包响应，二者不是同一接口 |
| 环境变量 | 复制 console-environment.example.json，并在控制台补实际模型参数 |
| 标签 | 可填项目、队伍和版本，不填密钥 |

环境变量模板中的CLOUD_STORAGE_MOUNT必须与存储挂载路径相同，CLOUD_STATE_DIR位于其下。CLOUD_TRUST_GATEWAY=1表示应用信任平台已完成入站认证；必须真的配置IAM/API Key/OAuth，不能将它理解为免认证公网服务。

网页上传镜像时：先创建/选择SWR组织，再选择docker save导出的tar。按截图，文件及解压后大小均不得超过2GB，超出时需按平台指引使用客户端方式。上传成功后回到运行时页选择镜像与标签。

## 调用线上接口

平台调用地址从运行时详情复制，不自行猜域名和区域。示例中的Runtime-API-Key-Header必须替换为实际入站请求头名：

```sh
curl -X POST 'https://<实际网关域名>/runtimes/<实际运行时名称>/invocations' \
  -H 'Content-Type: application/json' \
  -H 'X-Hw-Agentarts-Session-Id: <新建并保留的随机会话ID>' \
  -H 'Runtime-API-Key-Header: <在本地填写，不提交源码>' \
  -d '{"message":"设计电池供电的环境监测设备，先交付设计文档"}'
```

也可用API调试工具，避免把密钥留在终端历史。相同会话后续请求保留头中的会话ID，并带上响应里的run.id。

支持action：start、continue、status、reply、confirm、select、supplement、download；高级确认另有design_accept、continue_selection、proceed_estimated_design。confirm/select/supplement需携带project_revision；reply需run_revision。每次请求最多推进两个决策步骤，返回continue可再请求；不是后台永久运行任务。请求超时先查询status，不盲目重复start或确认。

download返回ZIP的base64及SHA-256。本地预览页面自动下载；平台控制台调用时按实际接口响应处理。

浏览器不能在普通地址栏导航时附带自定义API Key请求头，因此有认证的网关地址不能简单当成公开网页链接。本次提供的是本地可视化预览和云端API适配。正式比赛线上可视化入口仍需一个受保护的网站后端/BFF代理，把入站密钥留在后端；这一步不应通过把密钥写进静态HTML来绕过。

## 会话数据与首版限制

同一平台Session ID对应独立项目与运行目录。平台会话存储只能保证其支持的会话生命周期范围，不等于长期项目数据库；会话彻底删除、版本切换与保留策略须按控制台实际规则验证。项目与运行用带哈希的不可变JSON快照保存，保留最近5代；中断写入恢复上一完整快照，避免在FUSE上运行SQLite事务。

此版针对单队伍演示、每个平台会话一个应用写入进程，不宣称已实现跨租户身份授权、跨副本分布式锁或数据库级事务。并发生产部署、长期项目归档需后续RDS/OBS等持久化后端。运行时API Key为调用认证，不能把用户自行提供的会话ID当成完整用户授权系统。

首版每会话快照8MB、每进程64会话，每次调用两步；模型单次连接超时45秒。真实模型耗时与平台网关请求超时仍需联调；暂不承诺大型工程持续自主运行。阶段结果保留未审核、估算与未实测边界。

## 官方依据

- https://support.huaweicloud.com/highcode-agentarts/agentarts_10_183.html
- https://support.huaweicloud.com/highcode-agentarts/agentarts_10_029.html
- https://support.huaweicloud.com/highcode-agentarts/agentarts_10_119.html
- https://support.huaweicloud.com/highcode-agentarts/agentarts_10_124.html
- https://support.huaweicloud.com/highcode-agentarts/agentarts_10_255.html

配置按2026年10月16日查阅的文档与用户截图整理；账号实际开放区域、权限、接口、挂载点与套餐以控制台为准。上线前还须实际构建镜像、验证挂载恢复、完成模型联调与端到端调用。
