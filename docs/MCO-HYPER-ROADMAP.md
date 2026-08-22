# MCO Hyper Roadmap

> 狀態：**設計契約（Design Contract）**  
> 本文件描述 `mco-hyper` 相對於 upstream MCO 的預定增量。除非另有標示，本文列出的功能均不得視為已實作能力。

## 1. 目的

`mco-hyper` 延續 MCO 的 CLI-first orchestration 模型，並保留一項核心原則：**Lead / Orchestrator 是 Hive、MCO 或其他 runtime 外部既有的 Coding Agent**。Codex、Antigravity CLI、GitHub Copilot CLI、Claude Code 等上層 Agent 應能直接透過 CLI 呼叫 MCO，而不必先被放進 MCO 管理的 PTY 或自建 Agent loop。

本 fork 的主要增量是：

- Provider-native session continuity；
- 同一 repo 內依 topic / workflow scope 隔離 session；
- Antigravity CLI（`agy`）正式 Provider；
- Profile / Connection / BYOK；
- 可觀測的 native session 與 cache / usage metadata；
- 將 provider-specific 差異收斂成可維護的 capability / preset contract。

## 2. Product Invariants

以下原則屬於架構邊界，後續實作不得默默改變：

1. **External Lead remains the orchestrator**  
   MCO 是 Lead 可呼叫的 orchestration runtime，不取代 Lead 的推理、決策與最終收斂角色。

2. **Native CLI remains authoritative**  
   Provider 的官方／原生 CLI 負責登入、模型存取、工具權限、native session 與實際 inference。

3. **Opaque answer contract**  
   Worker 的自然語言回答保持不透明；MCO 不強制轉成 findings、severity、confidence、verdict、consensus 等語意 schema。

4. **Explicit team and explicit scope**  
   MCO 不以 LLM 自動推斷應該派哪個 Provider，也不以 prompt semantic similarity 判斷是否屬於同一 topic。

5. **Native session first**  
   Provider 支援 exact native resume 時，優先延續 native session；只有不支援或無法取得 native session 時，才允許使用 synthetic-history fallback。

6. **No inference proxy**  
   MCO 不成為 LLM API proxy/router。BYOK traffic 仍由 native harness 直接送往使用者指定的 endpoint。

7. **Profile is part of identity**  
   Provider 相同但 connection、model 或重要參數不同時，不得默默共用同一個 native session。

## 3. Upstream Baseline：不是本 fork 的新增功能

以下能力由 upstream MCO 提供，原則上直接保留，不重做第二套：

- `mco run` / `mco review` CLI；
- explicit Provider / model team selection；
- parallel dispatch、chain、divide、debate 等既有 orchestration；
- adapter contract：detect / run / poll / cancel / transport decode；
- raw answer / artifact preservation；
- read-only / write / yolo execution mode；
- JSON / JSONL / Markdown 等既有輸出；
- 一個 Provider invocation 失敗時保留其他成功結果；
- custom agent / ACP 等既有擴充點。

除非新增功能確實需要，Roadmap 不以重寫上述能力為目標。

---

## 4. P0 — Native Session Foundation

### 4.1 Native Session Runtime

新增 provider-native session lifecycle：

- capture native session ID；
- exact native resume；
- `reuse` / `fresh` / `explicit` session mode；
- native session 不可用時才 fallback 到 synthetic history；
- transient provider failure 不得自動等同「native session 已失效」；
- native session metadata 與 worker answer 分離保存；
- 保持既有 raw output / opaque-answer contract。

目標行為：

```text
turn 1 -> native session S
turn 2 -> resume S
turn 3 -> resume S
```

而不是把主要 continuity 建立在：

```text
turn 1 -> one-shot CLI
turn 2 -> synthetic history + new prompt -> new one-shot CLI
```

### 4.2 Topic Scope / Session Identity

新增穩定且顯式的 `scope`。

Canonical session identity：

```text
canonical repo
+ scope
+ provider
+ profile identity / fingerprint
-> native session
```

要求：

- 同 repo、不同 topic / issue 必須隔離；
- 同 repo + scope + provider + profile 可 reuse；
- profile / connection / model 的相容性邊界改變時不得錯誤 resume 舊 session；
- 不用 prompt hash 或語意相似度推導 scope；
- Lead 應能使用穩定識別，例如 `issue-42`、`ble-gatt`、`gcp-auth`、`pr-184`。

預定 CLI 介面：

```bash
mco run --scope ble-gatt ...
mco review --scope pr-184 ...
```

### 4.3 Antigravity CLI Provider

新增正式 `agy` Provider，至少涵蓋：

- binary detect / auth preflight；
- model selection；
- effort / reasoning level（依 CLI 實際支援）；
- permission mapping；
- structured output transport；
- capture `conversation_id`；
- exact resume：`--conversation <conversation_id>`；
- 不以 workspace-most-recent 的 `agy -c` 作為 topic-aware session 機制。

### 4.4 Codex Native Session

強化 Codex adapter / session runtime：

- capture native `thread_id`；
- exact thread resume；
- same scope -> same compatible thread；
- `fresh` -> new thread；
- transient failure 後，在沒有證據顯示 thread 無效時保留 pointer；
- synthetic history 降級為 fallback，而非主要 continuity mechanism。

### 4.5 GitHub Copilot Native Session

強化既有 Copilot adapter：

- exact `--session-id`；
- same scope + compatible profile -> same session；
- new scope -> different session；
- `fresh` -> independent session；
- 不使用可能跨 topic / cwd fallback 的全域 `--continue` 作為核心機制；
- 保留 upstream read-only / write / yolo permission mapping。

---

## 5. P1 — Generic Compatibility & Profile Layer

### 5.1 Generic Session Preset Contract

建立 provider-neutral contract，使 session 行為不散落在 orchestration core 的條件判斷中。

概念欄位：

```text
command
args
env
session_capture
resume_args
model_args
permission_args
capabilities
```

具體實作可以是 typed Python contract、Provider descriptor 或其他適合 upstream 架構的形式；Roadmap 不預先綁死儲存格式。

### 5.2 Profile

定義：

```text
Profile = Provider + Connection + Model + Provider Parameters
```

目標：

- 同一 Provider 可以同時存在多個 profile；
- role 可映射到 profile，但 role 不取代 profile identity；
- profile 參與 session identity；
- model / connection 改變後不誤 resume 不相容的 native session。

範例：

```text
copilot-native
copilot-deepseek
copilot-glm
codex-sol-high
agy-gemini-high
```

### 5.3 Connection / BYOK

第一階段至少支援：

- native account；
- GitHub Copilot CLI BYOK；
- OpenAI-compatible endpoint；
- provider type / base URL / model 等非敏感設定；
- secret reference（environment / OS credential store 等），而不是把 API key 明文塞進普通 repo config；
- MCO 不代理 inference traffic。

預期 traffic：

```text
MCO
 -> native Copilot CLI
 -> configured BYOK endpoint
```

### 5.4 Session Management CLI

提供可檢查、可控制，而不是黑箱的 session lifecycle。

預定能力：

```text
mco session list
mco session inspect
mco session clear
mco session fresh / fork
mco session resume <native-id>
```

至少能顯示：

- repo；
- scope；
- provider；
- profile；
- native session ID；
- native / synthetic-fallback 類型；
- last-used timestamp。

實際 CLI 命名可在 M1/M2 完成後依現有 MCO CLI structure 收斂。

### 5.5 Cache / Usage Telemetry

MCO 只保存 provider 能實際回報的資料，不自行猜測 cache hit。

可用時保存：

- native session ID；
- `reused=true/false`；
- model / profile；
- input / output token usage；
- Codex cached input tokens；
- AGY cache read tokens；
- Copilot / BYOK backend 提供的 cache usage。

缺少 provider evidence 時，欄位應為 unavailable / null，而不是估算。

### 5.6 External Lead UX

外部 Agent 必須能繼續直接使用：

```bash
mco run ...
mco review ...
mco session ...
```

Skill / calling-agent guidance 應明確要求：

- 同一 engineering thread 維持相同 scope；
- 不同 topic 使用不同 scope；
- independent second opinion 使用 `fresh`；
- Lead 負責比較 worker output、決策與最終 convergence。

---

## 6. P2 — Compatibility Cleanup & Capability Discovery

### 6.1 `mco-agent-compat` 瘦身

`mco-agent-compat` 不得演化成第二套 orchestration runtime。

長期只保留無法合理 generic 化的 harness-specific compatibility：

```text
profile / BYOK environment resolution
provider-specific session quirks
compatibility probes
short-lived CLI-version workarounds
```

能以穩定 generic contract 實作的能力，優先進入 `mco-hyper` core。

### 6.2 Provider Capability Metadata

Provider 應能宣告並由 `doctor --json` 等介面觀測：

```text
supports_native_session
supports_session_capture
supports_explicit_resume
supports_model_override
supports_byok
supports_cached_usage
```

Runtime 不應靠 provider 名稱 hardcode 猜 capability。

---

## 7. Non-goals

本專案目前**不做**：

- LLM semantic router；
- 由 LLM 自動選下一個 worker；
- semantic result normalization；
- 強制 findings / verdict / action / confidence schema；
- provider API traffic proxy；
- 自建 reasoning loop；
- Hive browser UI；
- Hive PTY team protocol；
- 強迫 Lead / Orchestrator 在 MCO runtime 內執行；
- 因為新增 native session 而改變 worker answer 的 opaque contract。

---

## 8. Milestones

### M1 — Native Session Foundation

範圍：

- session identity contract；
- explicit scope；
- native session metadata store；
- capture / resume provider contract；
- `reuse` / `fresh` / `explicit` semantics；
- synthetic-history fallback policy。

驗收條件：

1. 同 repo 不同 scope 會產生不同 session identity。
2. 同 scope + provider + compatible profile 可解析到相同 native session。
3. `fresh` 不覆寫 canonical reusable pointer。
4. Provider 不支援 native session 時可明確 fallback，且 metadata 可辨識。
5. 不改變 MCO 原有 opaque answer contract。
6. 有 deterministic unit tests 覆蓋 identity、reuse、fresh、fallback、invalid/transient failure semantics。

### M2 — AGY + Codex + Copilot Native E2E

範圍：

- `agy` 正式 Provider；
- Codex thread capture/resume；
- Copilot session-id reuse；
- 三家 provider 的 native session E2E。

驗收條件：

1. 每家 Provider 首次執行都能建立／擷取 native ID（若 CLI contract 支援）。
2. 第二次相同 scope 能證明使用 exact native resume。
3. 同 repo 換 scope 不會串 session。
4. `fresh` 不污染 canonical reusable session。
5. transient failure 不會在沒有 invalid-session evidence 時破壞有效 pointer。
6. 原始 provider output 與 MCO artifacts 仍完整保留。

### M3 — Profile / Connection / BYOK

範圍：

- Profile contract；
- Connection contract；
- native / BYOK separation；
- Copilot BYOK first-class path；
- profile fingerprint / compatibility boundary。

驗收條件：

1. 同 Provider 可同時設定多個不同 model/profile。
2. 同 scope 但不同 incompatible profile 不共用 session。
3. Native Copilot 與 BYOK Copilot 可明確切換。
4. API key 不寫入 repo config、run artifact 或普通 session metadata。
5. BYOK traffic 仍由 native harness 直接送至 endpoint。

### M4 — Management / Telemetry / Compatibility Cleanup

範圍：

- session management CLI；
- capability discovery；
- usage/cache metadata；
- `mco-agent-compat` 瘦身；
- public documentation promotion。

驗收條件：

1. 使用者能列出、檢查與清除 native session mapping。
2. `doctor --json` 能反映主要 native-session/profile capability。
3. cache telemetry 只呈現 provider 實際回報資料。
4. compatibility layer 不再重複 core orchestration/session infrastructure。
5. README 僅宣告已完成且已驗證的能力。

---

## 9. Core 與 Compatibility Layer 的責任分界

| 能力 | `mco-hyper` core | `mco-agent-compat` |
|---|---:|---:|
| orchestration / parallel dispatch | ✅ | ❌ |
| artifacts / raw answer | ✅ | ❌ |
| generic native session lifecycle | ✅ | ❌ |
| scope / session identity | ✅ | ❌ |
| generic profile contract | ✅ | ❌ |
| Provider capability contract | ✅ | ❌ |
| provider-specific transient workaround | ⚠️ 優先 generic 化 | ✅ 必要時 |
| BYOK secret/environment resolution | generic contract | ✅ harness-specific |
| short-lived CLI version quirks | ❌ | ✅ |

原則：如果一項能力能以 provider-neutral contract 表達，就不應永久留在 compatibility wrapper。

## 10. Hive Reference Policy

Hive 可作為**行為與架構概念參考**，例如：

- native session capture / resume；
- command preset abstraction；
- persistent agent/session recovery 的失敗案例。

但 Hive 目前採用 Business Source License 1.1。`mco-hyper` 不直接複製、搬移或改寫 Hive source code 後納入 MIT fork；相關能力應根據公開 CLI contract、觀察到的行為與本專案需求獨立實作。

## 11. Documentation Promotion Policy

在實作開始前：

- 原 upstream `README.md` 維持 baseline 產品說明；
- 原 `AGENTS.md` / agent instruction 維持 baseline 開發契約；
- 本文件是 fork 增量的唯一 roadmap/design contract。

後續文件更新順序：

1. Roadmap 定義目標與 acceptance criteria；
2. 完成 milestone implementation；
3. deterministic tests / E2E 驗證；
4. architecture contract 穩定後再更新 `AGENTS.md`；
5. 只有真正可用且驗證完成的能力才 promotion 到 `README.md`。

這可避免 coding agent 把「規劃中」誤認為「已實作」，也讓 fork baseline 與 Hyper 增量在 Git history 中保持清楚。
