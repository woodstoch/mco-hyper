---
on:
  workflow_dispatch:

permissions:
  contents: read

models:
  default-ai-credits-pricing:
    input: 0.000001
    output: 0.000001

engine:
  id: copilot
  env:
    COPILOT_PROVIDER_BASE_URL: "https://llm-share.duotify.com/v1"
    COPILOT_PROVIDER_API_KEY: ${{ secrets.LLMSHARE_API_KEY }}
    COPILOT_PROVIDER_TYPE: "openai"
    COPILOT_PROVIDER_WIRE_API: "completions"
    COPILOT_MODEL: "deepseek-v4-flash:0731"

network:
  allowed:
    - defaults
    - llm-share.duotify.com

tools:
  bash: []

---

# BYOK Smoke Test

This is a read-only connectivity test.

Do not modify any files.
Do not create issues, pull requests, comments, commits, or branches.
Do not execute shell commands.

Respond with a short result containing:

1. The exact model name you believe you are using.
2. The text `BYOK_SMOKE_OK`.
3. One short sentence saying that you successfully received these instructions.

Keep the response under 100 words.
