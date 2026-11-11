# 登录与服务可用性四项修复计划

> 使用 writing-plans 编制，在当前会话按 executing-plans 执行；独立代理只读审查计划及结果。不提交推送。

**Goal:** 消除登录密码哈希泄露、流式请求持有连接、启动重建异常阻断及用户名锁定滥用。

**Architecture:** 登录响应采用 LoginOut/UserOut 白名单，前端读取及保存用户信息时移除遗留敏感字段；问答在启动流之前快照原始值并结束请求事务；启动重建每文件独立提交/回滚，记录失败继续启动；登录限流按可信代理提供或直接连接的客户端 IP，计数有过期时间和容量上限。沿用现有依赖及结构，无数据库迁移。

**Tech Stack:** FastAPI、SQLAlchemy、pytest、Vue、Node 内置测试。

## 执行步骤

- [x] 1. 在 backend/tests/test_auth.py 和 frontend/tests/Store.spec.js 先补失败回归：成功登录仅公开字段，存储白名单与旧缓存清理；然后实现 schemas.py、routers/auth.py、store.js。
- [x] 2. 在 backend/tests/test_chat.py 补模型等待时请求事务已关闭的回归，覆盖 settings 缺失时创建；chat.py 在 commit 后读取设置并提交，捕获 kb_id/top_k/thread_id 等基本值，生成期间不访问请求 ORM 对象。
- [x] 3. 在 backend/tests/test_file_updates.py 补两文件中首文件 embedding 失败，旧块回滚、后一文件成功；document_service.py 查询 ID 后结束事务，每文件 try/commit/except rollback；main.py 对重建查询等顶层错误记录并继续初始化。
- [x] 4. auth.py 限流按客户端 IP；Vite/nginx 覆盖来源头，run.py 仅信任 TRUSTED_PROXY_IPS，默认 loopback；Compose 将 frontend 固定在专用代理网段地址，后端仅信任该地址且不暴露端口。用户已明确批准同步修改这些项目配置模板，不改实际生产环境。补同一可信代理后两个客户端互不锁定、非可信来源伪造 XFF 无效、过期清理、容量上限、窗口内失败计数与锁定回归。成功登录不清失败预算，避免低权限账号清空计数；同公网 NAT 地址共享限额，多进程限流不共享。
- [x] 5. 运行后端全量 pytest、前端全部 Node 测试和 build、内存 Python 编译及 diff --check；独立只读审查。补充变更记录，说明单进程限流及已泄露缓存的历史边界。

## 验证命令

```powershell
# backend/
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
# frontend/
node --test tests/*.spec.js
npm run build
```

验证不调用真实模型，不改原用户密码或真实业务数据。已有未提交 M0-6 与样式修改保留。

## 执行与验证

- 新增回归修复前后端 7 failed、51 passed，前端 Store 2 failed；均确认对应原缺陷。代理信任入口和 Vite 覆盖测试也在最终实现前确认失败。
- 最终后端全量 118 passed、2 skipped；前端 50 passed，build 成功，Compose config --quiet 校验通过。Compose 校验未使用真实生产凭证，缺少根环境变量的提示不代表已部署。
- 同一独立代理指出并复审代理共享 IP 和成功登录重置预算两个绕过点，最终 Approved。用户明确批准修改代理配置模板。
- 实际本地后端成功重启，健康接口 200；真实 Vite 代理验证两来源隔离，攻击来源伪造 XFF 仍被 429 限制，另一来源仍进入凭据校验。未创建业务测试数据或调用模型。
- 原先 10 个本轮 Python 模块内存语法编译通过；最终增加配置文件后再次编译及 diff 检查。未自动提交推送。
