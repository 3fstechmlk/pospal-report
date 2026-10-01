# Project Instructions

## 部署触发规则（强制）

**只有用户明确说出以下关键词时才执行部署，任何其他情况一律不得自行部署：**
「部署上线」/「上线去console」/「部署」/「上线」

不得因为"改完了顺便部署"、"之前部署过"、"用户可能想看效果"等理由主动部署。

---

## Deploy SOP ("部署上线" / "上线去console" / "部署" / "上线")

六步，按顺序走，不得跳步。前四步不碰服务器，随时可以中止。

### Step 1 — 问用户要发什么版本（**不得自行决定**）

每次部署前都要先问，把当前版本号、这次改了什么、建议的新版本号一起列出来，
等用户确认后才改 `run.py` 的 `VERSION`。

建议遵循：

- 行为/功能变化 → minor（1.3.0 → 1.4.0）
- 只修 bug 或改 UI，不改行为 → patch（1.3.0 → 1.3.1）

但**最终版本号由用户定**，不要自己 bump 完就往下走。

版本号是验证部署有没有生效最省事的手段：页面右上角的徽章和 `/api/version` 都读它。
**版本号没动的部署，无法从外部确认新代码真的跑起来了。**

### Step 2 — 更新 Update History

把这次的改动写进 `CHANGELOG.md`，格式照抄已有条目（`## v1.3.1 — YYYY-MM-DD` +
`### Fixed` / `### New` / `### Security` 分节）。

这个文件就是 `/admin` 版本徽章点开后显示的 Update History（经 `/api/changelog`
下发），所以它是写给商户和自己看的，不是写给 git 看的 —— 要写清楚**用户能感知到
什么**，而不是改了哪个函数。

### Step 3 — 本地验证

- `python -m py_compile run.py`
- 改过的每个页面：抽出 `<script>` 跑 `node --check`
- **改了 `public/` 下任何带 `?v=` 的 js/css，必须同步 bump 所有引用它的页面**。
  HTML 响应带 `no-store` 每次都是新的，但这些静态资源靠 URL 上的 `?v=` 区分版本 ——
  版本号不变，浏览器就一直用缓存里的旧文件，代码部署了也等于没上线。
  v1.3.0 的发票备注就是这么"部署成功但看不到"的：`invoice-template.js` 改了，
  引用还停在 `?v=9`。
  一条命令对一遍引用的版本号和文件 mtime：
  ```bash
  grep -ho '/[a-z-]*\.\(js\|css\)?v=[0-9]*' public/*.html | sort -u; ls -l --time-style=long-iso public/*.js public/*.css
  ```
- 能在本地起服务就起（`preview_start`，端口 8081），实际点一遍改动的地方

### Step 4 — Push 到 GitHub（**部署前必须完成**）

```bash
git add -A && git commit && git push
```

远端：`https://github.com/3fstechmlk/pospal-report`，分支 `pospal-main`。

**先推后部署，不能反过来。** 服务器上没有代码的版本管理，部署是直接 tar 覆盖；
推上去的那个 commit 就是这次上线内容的唯一凭据，出事了才知道线上到底是什么。

**push 没成功就不许部署。** 不管是被权限拦、认证失败还是网络问题，一律**停下来**
交给用户处理，不要"先部署了回头再推"。v1.3.0 就是这么上的线：push 被拦，照样部署，
结果那段时间线上跑的代码在任何地方都没有记录，出问题无从比对。

> 历史包袱：仓库里另有 `main` / `master` 两条旧线和 4 个 tag，含一家在营商户
> （YOU MI KITCHEN）硬编码在旧 PHP/Node 实现里的真实 appId/appKey。**那两条线和
> 那些 tag 永远不要推。** 只推 `pospal-main`。那把 key 该轮换。

### Step 5 — 部署上线

**5.1 先快照线上代码** —— 这是唯一的回滚点，`backup.sh` 只备份 `data/` 和
`cache/`，不备份代码：

```bash
ssh -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no root@5.223.80.199 "cd /opt/pospal-report && tar -czf /opt/pospal-backups/code_before_$(date +%Y%m%d_%H%M%S).tar.gz --exclude='./data' --exclude='./cache' --exclude='./.git' --exclude='./__pycache__' --exclude='./pospal-report' --exclude='./legacy' --exclude='./.playwright-mcp' . && ls -lh /opt/pospal-backups/code_before_*.tar.gz | tail -1"
```

排除项不能省：服务器上那个 stale 的 `pospal-report/` 嵌套目录里有它自己的 cache，
少排一项，快照就从 500K 变成 626M。

**5.2 打包**

```bash
cd "/c/project/pospal-report" && tar -czf /tmp/pospal_deploy.tar.gz --exclude='./data' --exclude='./cache' --exclude='./ssh' --exclude='./.git' --exclude='./.claude' --exclude='./pospal-report' --exclude='./__pycache__' --exclude='*.pyc' --exclude='./.DS_Store' --exclude='./node_modules' --exclude='./legacy' .
```

**5.3 上传**

```bash
scp -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no /tmp/pospal_deploy.tar.gz root@5.223.80.199:/tmp/pospal_deploy.tar.gz
```

**5.4 解包 + 重启**

```bash
ssh -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no root@5.223.80.199 "cd /opt/pospal-report && tar -xzf /tmp/pospal_deploy.tar.gz --exclude='./data' --exclude='./cache' && rm /tmp/pospal_deploy.tar.gz && systemctl restart pospal && sleep 3 && systemctl status pospal --no-pager | head -8"
```

### Step 6 — 验证

```bash
ssh -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no root@5.223.80.199 "curl -s http://localhost:8080/api/version; echo; systemctl is-active pospal; journalctl -u pospal --since '3 minutes ago' -p err --no-pager --quiet | tail -3"
```

`/api/version` 必须返回 Step 1 定的那个号。不对就是没生效。再打开 `/admin`，
点版本徽章，确认 Update History 里是这次写的条目。

---

## 部署须知

- Server: `5.223.80.199` ｜ Remote: `/opt/pospal-report/` ｜ Service: `pospal`
  ｜ Port: 8080 ｜ SSH key 见上面命令里的路径

- **`cache/` 在服务器上是符号链接**，指向 `/mnt/HC_Volume_105461195/pospal-cache`
  （45G 独立卷）。本地的 `cache/` 是真实目录。打包和解包的 `--exclude='./cache'`
  **一个都不能漏** —— 漏了会用本地目录覆盖掉那个符号链接，850 家商户的缓存当场
  与程序脱钩。`data/`（33M，含全部 appKey 和商户密码）同理。

- 重启的副作用，都是预期内的：所有商户会掉线（session 存在内存里，各页会把 401
  干净地送回登录页）；今天的 `_mem` 清空，下一个开报表的人会触发一次实时抓取。

- `data/config.json` 存的是**明文** admin 密码，`CONFIG` 只在启动时读一次 ——
  改密码必须重启才生效。

- 服务器上 `/opt/pospal-report/pospal-report/` 是旧版本的完整副本，占 8.1G，
  当前程序完全不碰它。要清理得先确认里面没有顶层 cache 缺失的日期。

---

## merchants.json 的 member_portal / join_member

两个字段互相独立，都由 Admin Console 的 Edit Merchant → Features 控制：

- `member_portal` — 只控制该商户在 Report 首页看不看得到「Member QR」按钮（`report.html`）。
  **它不控制会员门户本身**：pospal-member 的 `tryAutoProvision` 写死 `feature_member = 1`，
  任何人访问 `/p/{account}` 都会自动开通。
- `join_member` — 控制会员门户的「Join as Member」注册入口。pospal-member 读同一份
  `merchants.json`，通过 `/api/portal/:slug/info` 的 `feature_register` 下发，
  并在 `POST /api/portal/:slug/register` 做 403 拦截。字段缺失一律视为关闭。

后台改完开关**立即生效**。pospal-member 的 `readMerchantsJson` 按 mtime+size 判缓存是否失效
（`statSync` 0.004ms，全量解析 260KB 要 1.5ms 且是同步的，所以不能每次请求都解析）。

`_save_ms` 是**原子写**：先写 `merchants.json.tmp` 再 `os.replace` 换名，
与同文件里的 `_save_pay_methods_to_disk`、`_save_customers_to_disk` 写法一致（那两处原本就是
原子写，只有 merchants.json 漏了）。不要改回
`open(MERCHANTS_FILE,'w')` —— 那会先把文件截断成 0 字节再逐块写入 260KB，中途进程被
kill/OOM 就会让 850 家商户的数据永久停在残缺状态（实测可毁成 129221 字节且无法解析），
同时读方会读到半截 JSON（实测边写边读 231 次里失败 123 次）。

**跨项目改动注意**：任何外部进程写 `merchants.json` 都必须先 `systemctl stop pospal`，
因为 run.py 用 `_m_lock` 串行读写，外部写入会被下一次 `_save_ms` 整份覆盖。
（原子写解决的是"写到一半被中断"，不是多进程互斥，替代不了这条。）
