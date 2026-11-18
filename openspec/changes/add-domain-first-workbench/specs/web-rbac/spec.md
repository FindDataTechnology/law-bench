# web-rbac Specification（delta）

## Purpose

导航模型换形：从「全局条目 + 每域两条链接」改为「域优先」。权限判定规则本身不变——平台 scope 来自 Logto、域角色来自成员记录、双闸先 scope 后域角色、fail-closed 全部保持原样；本次只改**渲染什么、在哪渲染**，以及导航所表达的信息架构。

## MODIFIED Requirements

### Requirement: Permission-aware navigation

The workbench UI SHALL hide the navigation entries and actions that the current identity is
not permitted to use, and SHALL show them to identities that are permitted. Navigation
filtering SHALL be a usability layer only; it MUST NOT replace server-side enforcement.

Navigation SHALL be rendered for the **current context** rather than as a single global list:
on the domain list the navigation SHALL carry the brand (pointing at the domain list), the
language switch, the identity block, and the platform gate (only for the `admin` platform
scope); on any domain page it SHALL carry the current-domain indicator, the domain switcher
(only domains in which the identity holds an active membership), the language switch, the
identity block, and the platform gate (only for `admin`). Global asset entries that are not
scoped to the current domain SHALL NOT be rendered on every page.

#### Scenario: Navigation is filtered for a read-only identity

- **WHEN** an identity holding only `content:read` opens the workbench
- **THEN** navigation entries requiring the `content:write` or `admin` scope are not rendered

#### Scenario: Navigation is complete for an admin

- **WHEN** an identity holding the `admin` scope opens the workbench
- **THEN** all navigation entries the wildcard scope permits are rendered

#### Scenario: Global asset entries are not repeated on every page

- **WHEN** an identity opens any domain page
- **THEN** the header does not render the full global asset link list; those entries are reached through the domain's own areas and the global asset pool instead

### Requirement: Permission-aware navigation covers the domain surface

The workbench navigation SHALL render domain entries by effective permission: an identity
SHALL see only domains where it holds an active membership; the platform administration
gate (templates, all-domain membership, invitations) SHALL render only for identities
holding the `admin` platform scope. Unauthorized entries SHALL NOT be rendered rather than
rendered and denied.

Domain entries SHALL be presented domain-first: the domain list (`/d`) SHALL be the primary
navigation surface for choosing a domain, and inside a domain the navigation SHALL expose only
that domain's areas, filtered by the identity's role **in that domain**. The current domain
SHALL be resolved server-side from the path and re-validated against membership on every
request; a client-supplied domain indicator MUST NOT be trusted. Platform-level entries SHALL
NOT appear inside any domain's area navigation.

#### Scenario: Navigation is filtered by domain membership

- **WHEN** an identity whose only membership is domain A views the navigation
- **THEN** the navigation shows domain A's entry and common platform items; domain B and the administration gate do not appear

#### Scenario: Domain areas are filtered by the role in that domain

- **WHEN** an identity is `lead` in domain A and `annotator` in domain B opens domain B's page
- **THEN** domain B's navigation exposes only the areas an `annotator` may use in domain B, even though the same identity may use more areas in domain A

#### Scenario: Platform entries never leak into a domain area

- **WHEN** an identity holding the `admin` platform scope opens a domain page
- **THEN** template management, opening a domain, and cross-domain invitations appear only under the platform gate, not inside the domain's area navigation
