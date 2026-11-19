## 1. 契约改成如实

- [x] 1.1 删除「Jenkins→Harbor 永久兜底（jobs preserved）」承诺，改为两条已验证的回滚路径；验证＝`openspec validate fix-image-delivery-fallback-claim --strict`
- [x] 1.2 把「Jenkins 已不存在」的证据写进 requirement 正文（四个 context 无工作负载 / `:31000` 无监听 / 域名回空 200）；验证＝本文件与 spec 正文逐条对得上
- [x] 1.3 补场景：无可用 tag 时走私有快照仓，而不是找 Jenkins；验证＝scenario 覆盖该分支
