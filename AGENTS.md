# Project Instructions

## 部署触发规则（强制）

**只有用户明确说出以下关键词时才执行部署，任何其他情况一律不得自行部署：**
「部署上线」/「上线去console」/「部署」/「上线」

不得因为"改完了顺便部署"、"之前部署过"、"用户可能想看效果"等理由主动部署。

---

## Deploy ("部署上线" / "上线去console" / "部署" / "上线")

When the user says any of the above, run these steps in order (same pattern as the
Workflow project: tar → scp → extract + restart).

**Step 1 — Package project (excluding runtime data and local-only files)**
```bash
cd "/c/project/pospal-report" && tar -czf /tmp/pospal_deploy.tar.gz --exclude='./data' --exclude='./cache' --exclude='./ssh' --exclude='./.git' --exclude='./.Codex' --exclude='./pospal-report' --exclude='./__pycache__' --exclude='*.pyc' --exclude='./.DS_Store' --exclude='./node_modules' --exclude='./legacy' .
```

**Step 2 — Upload to server**
```bash
scp -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no /tmp/pospal_deploy.tar.gz root@5.223.80.199:/tmp/pospal_deploy.tar.gz
```

**Step 3 — Extract and restart service**
```bash
ssh -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no root@5.223.80.199 "cd /opt/pospal-report && tar -xzf /tmp/pospal_deploy.tar.gz --exclude='./data' --exclude='./cache' && rm /tmp/pospal_deploy.tar.gz && systemctl restart pospal && sleep 2 && systemctl status pospal --no-pager | head -8"
```

- Server: 5.223.80.199
- SSH key: `C:\Users\JONA TAI\.ssh\id_ed25519`
- Remote path: `/opt/pospal-report/`
- Service name: `pospal`
- **Never upload or overwrite the `data/` folder (contains production DB) or the
  `cache/` folder (server-side ticket cache is newer than local)**
- Never upload `ssh/` (contains a private key copy), `.Codex/`, or the stale
  nested `pospal-report/` folder

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
