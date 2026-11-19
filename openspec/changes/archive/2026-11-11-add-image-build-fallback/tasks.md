## 1. 契约补真实形态

- [x] 1.1 `image-delivery` 的构建要求补入「私有额度耗尽时走私有快照仓」与「禁止改用公开仓」；验证＝`openspec validate add-image-build-fallback --strict` 通过
- [x] 1.2 补入「抬头仓用自己的 workflow，不用通用平台镜像工作流」；验证＝本次首跑踩过：通用闸按 3000/`/api/config` 判定，law-bench 必然失败
- [x] 1.3 补入溯源判据（`BUILD-INFO.json.baseCommit` + hkccr/ccr digest 一致），并明示镜像 label 不可用；验证＝`sha-75d95bd` 在两个源码仓历史里都查不到，`BUILD-INFO.json` 能查到

## 2. 闸门环境中立（实修）

- [x] 2.1 兄弟仓（fd-sentiment / fd-cn-gov）缺失时 skip 并写明路径；验证＝`test_pack_equivalence`、`test_three_domain_smoke` 本地在有仓时真跑、CI 上 skip
- [x] 2.2 soffice 缺失时 PDF 腿 skip，DOCX 腿照跑；验证＝`test_contract_artifact_storage` 两条
- [x] 2.3 autocommit 回滚用例显式带口令（`conn.info.dsn` 不含密码）；验证＝CI 上不再 `fe_sendauth: no password supplied`
- [x] 2.4 CI 全绿：`test` job 1907+ passed / 103 skipped，`build-push` 成功铸 `sha-afb4e71`

## 3. 实跑与上线

- [x] 3.1 私有出片仓 `law-ai-official/law-bench-images` 建立并灌 TCR secrets；验证＝`fd-build-org-setup` 输出 secrets ✓、relay 清单 PRESENT
- [x] 3.2 快照推送出片；验证＝run 42961293733 成功，日志"已铸 sha-afb4e71"，ccr 侧 digest 与 hkccr 一致（`sha256:5d47b15…`）
- [x] 3.3 清单 bump 并滚版；验证＝Argo `Synced 076b015`，pod `1/1` ready，容器内 `EXTRACT_MAX_TOKENS=4000` 与 `packs/gov/pack.yaml` 含 concept 岗
