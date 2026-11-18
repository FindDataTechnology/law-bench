# law-article-citation Specification (delta)

## Purpose

Resolves article-level citations in contract text ("《民法典》第1085条") to concrete statute articles — (law identity, article number, article text) — building on the law-catalog name resolution (from `link-law-catalog-audit`) and law-api full-text retrieval, so contracts can be linked to law provisions, not just law names.

## ADDED Requirements

### Requirement: Article citation parsing

The system SHALL parse citation strings of the form 法名 + 条号 out of contract/clause text, where the 条号 may appear as Arabic numerals (`第1085条`) or Chinese numerals (`第一千零八十五条`), optionally with 条/款/项 sub-parts (`第1085条第2款`). The parser SHALL produce a structured citation: law name hint, article ordinal (normalized to Arabic), and raw sub-part references. It SHALL be deterministic and not require any network access.

#### Scenario: Arabic numeral citation

- **WHEN** the text contains `《民法典》第1085条`
- **THEN** the parser yields law name hint `民法典`, article ordinal 1085

#### Scenario: Chinese numeral citation

- **WHEN** the text contains `民法典第一千零八十五条`
- **THEN** the parser yields law name hint `民法典`, article ordinal 1085

#### Scenario: Citation with paragraph qualifier

- **WHEN** the text contains `第595条第2款`
- **THEN** the parser records article ordinal 595 with the 款 sub-part reference preserved

### Requirement: Article resolution to provision text

For a parsed citation, the system SHALL resolve the law (via the law-catalog name resolution ladder: the law name hint from the citation) to a law_id, fetch the law's full text (via law-api full-text retrieval), and locate the article by matching the article ordinal against article boundaries in the text (第X条 anchoring). The output SHALL be (law_id, article ordinal, article text, law_status at fetch time). Resolution failures at each stage (unresolved name, fetch failure, article number out of range) SHALL be reported distinctly rather than conflated.

#### Scenario: End-to-end article resolution

- **WHEN** resolving `民法典第1085条` where the catalog resolves 民法典 and the law has at least 1085 articles
- **THEN** the result carries law_id, article ordinal 1085, that article's text, and the law's status

#### Scenario: Article number beyond the statute's length

- **WHEN** a citation names 第9999条 of a law with 1260 articles
- **THEN** resolution fails with an explicit out-of-range outcome, not an empty or wrong-article match

#### Scenario: Fetch failure is distinct from parse failure

- **WHEN** the law name resolves but law-api is unreachable
- **THEN** the outcome is a fetch-failure, distinguishable from unresolved-name and out-of-range outcomes

### Requirement: Article-level results extend the citation link layer

Article-level resolution results SHALL be stored as an extension of the law-catalog linking layer (keyed by clause and law, with article ordinals), re-runnable like the name-level pass, and SHALL NOT modify clause bodies or derived `law_refs`. Law identifiers throughout SHALL remain opaque strings where they originate from law-api.

#### Scenario: Re-run after corpus edits

- **WHEN** clause text changes and the article-level pass re-runs
- **THEN** results follow the current citations, and clause bodies / `law_refs` are untouched
