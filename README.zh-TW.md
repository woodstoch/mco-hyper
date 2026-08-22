<p align="center">
  <img src="https://raw.githubusercontent.com/mco-org/mco/main/docs/assets/brand/mco-cover-starry.jpg" alt="MCO——十條 Agent 路徑在星空下匯聚穿過宏偉的 M" width="100%" />
</p>

<h1 align="center">MCO</h1>

<p align="center"><strong>編排 AI Coding Agent，比較多方視角，更有把握地行動。</strong></p>

<p align="center">
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/v/@tt-a1i/mco?style=flat-square&color=cb3837&logoColor=white&logo=npm" alt="npm version" /></a>
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/dm/@tt-a1i/mco?style=flat-square&color=cb3837" alt="npm downloads" /></a>
  <a href="https://github.com/mco-org/mco/stargazers"><img src="https://img.shields.io/github/stars/mco-org/mco?style=flat-square&color=f59e0b" alt="GitHub stars" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
</p>

<p align="center"><a href="./README.md">English</a> · 繁體中文</p>

MCO 是一個輕量、CLI 優先的 AI Coding Agent 編排層。把同一個任務交給你明確選擇的 Agent 和模型，平行執行，比較原始回答，再決定下一步。

它適合程式碼審查、功能實作、架構分析、CI 檢查，以及任何需要減少單一模型盲區的工作流程。

既可以直接從終端使用，也可以由 Claude Code、Codex、Cursor、Copilot、Pi 或 OpenClaw 等上層 Agent 呼叫。

> MCO 正在持續維護。如果你需要持久 Agent 身分、共享任務圖和瀏覽器工作台，可以搭配使用 [Hive](https://hivehq.dev)。

## 快速開始

安裝 CLI 和內建 `mco-cli` Skill：

```bash
npx @tt-a1i/mco@latest install
```

檢查本機可用的 Agent：

```bash
mco doctor --json
```

執行一次唯讀的多 Agent 審查：

```bash
mco review \
  --repo . \
  --prompt "審查這個儲存庫中的高風險 bug。" \
  --providers claude,codex,pi
```

執行允許修改工作區的編碼任務：

```bash
mco run \
  --repo . \
  --prompt "實作需求並執行相關測試。" \
  --providers codex,pi \
  --execution-mode write
```

MCO 不會根據偵測到的二進位檔案推斷 Provider/模型團隊。缺少 `--providers` 和 `--agent` 時，設定檔頂層的 `providers` 會作為已儲存預設值生效；如果也沒有該預設值，就必須明確選擇團隊。呼叫方 Agent 在執行前仍應向使用者展示並確認最終解析出的 Provider/模型團隊。

## 為什麼使用 MCO

一個 Agent 只提供一個視角。MCO 把你選中的 Agent 組織成審查或執行團隊：

1. **選擇** — 明確指定本次任務的 Agent。
2. **分發** — 平行執行、串行挑戰，或按範圍分工。
3. **比較** — 保留每個 invocation 的完整原始回答和執行狀態。
4. **決策** — 檢查證據、分歧和失敗，再採取行動。

MCO 將回答正文視為不透明內容，不會從自然語言中推斷 finding、嚴重度、信心度、共識或自動決策。

需要明確協調審查時，可用 `--perspectives-json` 為 Provider 新增 prompt 側重點；`--divide files` 會排除 ignored、本機狀態和建置目錄，再將剩餘的儲存庫檔案按宣告順序輪轉分配且不重疊，`--divide dimensions` 會按宣告順序輪轉審查維度且不改變 target paths。這些選擇會在 dry-run 中顯示，只改變 prompt 或作用域，傳回的 invocation 回答仍保持原始內容。

## 內建 Provider

| Provider | CLI | Provider ID |
|----------|-----|-------------|
| Claude Code | `claude` | `claude` |
| Codex CLI | `codex` | `codex` |
| Gemini CLI | `gemini` | `gemini` |
| OpenCode | `opencode` | `opencode` |
| Qwen Code | `qwen` | `qwen` |
| GitHub Copilot CLI | `copilot` | `copilot` |
| Hermes | `hermes` | `hermes` |
| Pi | `pi` | `pi` |
| [Grok Build](https://docs.x.ai/build/overview) | `grok` | `grok` |
| [Cursor CLI](https://cursor.com/docs/cli/overview) | `cursor` / `agent` | `cursor` |

各 Provider CLI 仍然獨立負責安裝、認證、模型權限和原生沙箱行為。

## 常用工作流程

| 目標 | 命令 |
|------|------|
| 通用多 Agent 任務 | `mco run --providers claude,codex --prompt "..."` |
| 原始回答程式碼審查 | `mco review --providers claude,codex --prompt "..."` |
| 比較多個模型 | `mco run --agent fast=pi:model-a --agent careful=pi:model-b --prompt "..."` |
| 只預覽、不執行 | `mco review --providers claude,pi --dry-run --json` |
| 即時終端進度 | `mco review --providers claude,codex --stream live` |
| 機器可讀事件流 | `mco review --providers claude,codex --stream jsonl` |
| 檔案化 chain | `mco run --agent first=pi:model-a --agent next=pi:model-b --chain --result-mode artifact` |
| debate 與 synthesis | `mco review --providers claude,codex --debate --synthesize --result-mode both` |
| 查看 Provider 模型 | `mco agent models --providers codex,pi --json` |

僅為本次執行固定模型，不修改 Provider CLI 的預設設定：

```bash
mco review \
  --providers codex,pi \
  --provider-models-json '{"codex":"gpt-5.4","pi":{"provider":"seal","model":"deepseek-v4-pro"}}' \
  --prompt "審查這個儲存庫中的 bug。"
```

## 權限與安全

MCO 會把統一執行檔位轉換成各 Provider 的原生參數：

| 檔位 | 用途 | 預設場景 |
|------|------|----------|
| `read_only` | 唯讀檢查和審查 | `mco review` |
| `write` | 新增和編輯工作區檔案 | `mco run` |
| `yolo` | 使用 Provider 最寬的繞過權限 | 僅明確選擇 |

重要邊界：

- `--allow-paths` 只驗證 MCO 請求的作用域，不是作業系統級沙箱。
- 實際沙箱強度取決於底層 Provider CLI。
- Hermes oneshot 會繞過審批，因此必須明確使用 `--execution-mode yolo`。
- ACP terminal 屬於可信 Agent 能力；不可信 Agent 或提示詞應在隔離環境中執行。
- MCO 不建立或管理 worktree。使用者明確選擇平行寫入時，應透過不重疊的 `--target-paths` 劃分範圍，並提前提示編輯衝突風險。

完整映射見 [Provider 與權限參考](./docs/reference/providers.md)。

## 由其他 Agent 呼叫 MCO

MCO CLI 是自描述的。呼叫方 Agent 可以讀取 `mco -h`，解析已儲存預設值，向使用者確認 Provider/模型團隊，預覽策略，然後執行任務。

> 「使用 MCO，讓 Claude 和 Codex 做安全審查，讓 Pi 做架構審查。」

安裝器與執行階段存在兩個不同的選擇：

- 安裝器 `--agent` 決定把 MCO Skill 安裝給哪些呼叫方 Agent。
- 執行階段 `--providers`、已儲存的 `providers` 設定或執行階段 `--agent` 宣告共同決定本次任務的 invocation。

```bash
npx @tt-a1i/mco@latest install --agent codex --agent claude-code --yes
mco doctor --skill-health --json
```

## 運作原理

```text
使用者或呼叫方 Agent
        │
        ▼
  mco run / review
        │
        ├── Claude ──┐
        ├── Codex    │
        ├── Gemini   ├──► 原始回答 / 檔案化階段 ──► 輸出
        ├── Pi       │
        └── ...   ───┘
                              │
                       文字 · JSON · JSONL · Markdown 產物
```

Provider 程序統一封裝在 adapter contract 後：detect、run、poll、cancel、transport decode。單一 invocation 失敗不會丟棄其他 Provider 的成功回答。

## 文件

| 主題 | 文件 |
|------|------|
| 安裝、首次執行和常見工作流程 | [工作流程指南](./docs/guides/workflows.md) |
| Provider、模型與權限映射 | [Provider 參考](./docs/reference/providers.md) |
| CLI 參數、輸出、產物與退出碼 | [CLI 參考](./docs/reference/cli.md) |
| 設定檔與自訂 Agent | [設定參考](./docs/reference/configuration.md) |
| 機器可讀錯誤契約 | [錯誤契約](./docs/contracts/errors-v0.1.x.md) |
| Invocation 與 artifact 契約 | [Invocation 契約](./docs/contracts/invocation-runtime-v1.md) |
| Provider 權限契約 | [權限契約](./docs/contracts/provider-permissions-v0.1.x.md) |
| 發布流程 | [RELEASING.md](./RELEASING.md) |
| 版本歷史 | [CHANGELOG.md](./CHANGELOG.md) |

執行 `mco <command> --help` 查看目前安裝版本的權威參數列表。

## 開發

```bash
git clone https://github.com/mco-org/mco.git
cd mco
python3 -m pip install -e .
python3 -m unittest discover -s tests -p 'test_*.py'
npm test
```

## 授權條款

MIT — 見 [LICENSE](./LICENSE)。
