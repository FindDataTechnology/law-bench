# Clause Library Audit & Optimization - Design

## Audit scope and priority tiers

The audit targets clauses that actually enter assembly. Priority is proportional to blast radius:

```
Tier   Source        Ready count   Why it matters
─────────────────────────────────────────────────────────────
P0     base              329       Every contract of the type uses it. A defect
                                   here infects 100% of that type's output.
P1     custom             73       Overrides base per section (custom>tagged>base).
                                   A thin/wrong custom shadows a rich base.
P2     tagged           2976       Scenario-selected; enters only on match,
                                   but 112 carry region leakage today.
P3     tagged(dormant) 2688       NOT audited by LLM. Deterministic dedupe only:
                                   171 exact body_hash dupes -> rejected.
─────────────────────────────────────────────────────────────────────
       Total audited (P0-P2): ~3378 ready  (3378, not 3780 - exclude
                                          non-ready base/custom from the
                                          P0/P1 ready counts already)
```

> Note: P0-P2 counts are *assembly-ready* rows. Non-ready base/custom (175+192) stay as-is; they don't enter contracts until approved, at which point the lint gate catches new issues.

## Problem classes and detection

| Class | Signal | Detection | Example |
|-------|--------|-----------|---------|
| region_leak | province/city name + 地方性法规/办法/条例/局 | regex pre-filter, LLM confirms | 《深圳市员工工资支付条例》 in employment base |
| missing_slot (commercial) | hardcoded 金额/比例/期限 that is negotiable | LLM (regex only catches ~60, misses most) | "违约金为合同总额的20%" should be {{penalty_pct}} |
| missing_slot (statutory) | hardcoded value that IS the law | LLM marks keep-hardcoded | "设计变更10日内通知" (商品房销售管理办法 art.24) |
| wrong_scenario | narrow-scenario clause in a general section | LLM (e.g. 建筑垃圾清运 in service/权利义务) | overrides general clause |
| extraction_artifact | 示范文本 boilerplate | regex + LLM | 合同编号:___, 签订地点:___ headers |
| duplicate | identical body_hash | deterministic (no LLM) | 171 clauses, 71 groups |

## Pipeline (per clause)

```
                    ┌──────────────────────────────────────┐
                    │  P0/P1/P2 clause  (3378 ready)      │
                    └───────────────┬──────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   kimi-k3 classify          glm-5.2 classify          deepseek-v3 classify
   (ok/region/slot/          (same schema)            (same schema)
    scenario/artifact/dup
    + suggested_fix)           │                         │
          └───────────┬─────────┴───────────┬──────────┘
                      ▼ majority vote
              ┌───────────────┐
              │ needs_change? │── no ──▶ skip (keep clause)
              └───────┬───────┘
                      │ yes
                      ▼
          single-model rewrite (kimi-k3)
          rules: region->genericize; slot->{{slot}};
                 statutory->keep; artifact->strip
                      │
                      ▼
          verify (different model, glm-5.2 or deepseek)
          "defect fixed? legal point preserved?"
                      │
                ┌─────┴─────┐
                ▼           ▼
            pass         fail -> keep original, log for manual review
                │
                ▼
        clause_update(body=rewrite)
        -> manual=true, slot_instructions/body_hash/law_refs rederived
```

Concurrency: relay caps at 12 concurrent per uid (not per model). Run 3 classify calls per clause as a parallel trio; serialize rewrite+verify per clause. Effective throughput ~1 clause / (classify ~2s // rewrite ~3s) => ~3378 clauses in ~30-45 min wall-clock if classification fans out fully.

## Rewrite rules (normative)

### Region genericization
- Provincial regulation (《XX省/市XX条例/办法》) -> replace with the corresponding **national** law if one exists (《中华人民共和国劳动合同法》); if none, replace the citation with "按照国家及当地有关规定执行".
- Provincial agency (XX市工商局/XX省住建厅) -> "当地相关主管部门".
- Bare city/province name in an obligation -> "当地".
- **Never delete the obligation itself.** Genericize the source, keep the duty.

### Slot-ification
- Commercial blanks -> `{{snake_case_or_pinyin_slot}}` following the existing slot ontology (SLOT_PATTERN is Unicode/CJK-aware; `create_clause`/`clause_update` auto-derive `slot_instructions`).
- Statutory defaults (legal time limits, mandatory ratios set by law) -> **keep hardcoded**, add a `law_refs` note citing the article.
- If uncertain whether a value is statutory or commercial -> keep hardcoded, flag `uncertain` for a second pass.

### Extraction-artifact cleanup
- Strip leading 合同编号/签订地点/签订日期 header lines that belong to the contract shell, not the clause.

## Deterministic dedupe (P3, no LLM)

```
SELECT body_hash, array_agg(id)
FROM clauses
WHERE tags->>'source'='tagged' AND body_hash IS NOT NULL
GROUP BY 1 HAVING count(*) > 1
```
For each group: keep the lowest `id` (canonical), `clause_review(reject)` the rest. Recoverable via re-approval. Near-duplicates (same section, high text similarity, dormant) handled by the same reject-keep-canonical rule in a second pass over P3.

## Region lint gate (post-rewrite, deterministic)

Regex over the 31 province names + common 市局 patterns. Per clause residual count + per-type aggregate. This is a **quality metric**, not a hard block - surfaced alongside eval scores so regressions are visible. Runs cheaply after every audit batch.

## Re-evaluation gate

After all rewrites land:
1. Re-run `scripts/self_iterate.py` across all 43 types (existing batch, 3-judge serial streams, FAIL_CONF_THRESHOLD=0.6).
2. **Pass criterion**: all-pass count >= 39/43 (no regression vs V4/V5 baseline).
3. **Stretch**: unblock >=1 of {lease, land_transfer, film_production, service}.
4. If a type regresses: diff its assembled contract pre/post; likely cause is a custom override shadowing an improved base -> re-merge or retire the custom (merge-not-replace principle, per `sale-quanyi-override-drops-rich-base` memory).

## Risks

- **Base rewrite may drop content judges liked.** Mitigation: verify pass checks "legal point preserved"; re-eval gate catches score drops; keep original body in git/audit log for diff.
- **Custom<->base shadowing after rewrite.** A thin custom that was compensating for a bad base may now be redundant or harmful. Mitigation: post-rewrite, for each (type, section) with both base and custom, run a coherence check; retire customs that no longer add value.
- **LLM relay rate-limiting.** Same 12-concurrent ceiling as self-iteration; classify trios serialize within the concurrency budget. Multi-judge must run effectively serial per the `v4-sale-10of10-breakthrough` finding.
- **Statutory-vs-commercial misclassification.** Default-keep-hardcoded on uncertainty prevents accidentally slot-ifying a legal requirement.
