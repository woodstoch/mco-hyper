---
on:
  workflow_call:
    inputs:
      payload:
        description: "Reserved gh-aw worker payload."
        type: string
        required: false

      review_id:
        description: "Stable review session identifier."
        type: string
        required: true

      repository:
        description: "Repository in owner/name form."
        type: string
        required: true

      pr_number:
        description: "Pull request number."
        type: number
        required: true

      base_sha:
        description: "Frozen base commit SHA."
        type: string
        required: true

      head_sha:
        description: "Frozen head commit SHA."
        type: string
        required: true

      diff_sha256:
        description: "SHA-256 of the frozen diff."
        type: string
        required: true

      packet_sha256:
        description: "SHA-256 identity of the Review Packet."
        type: string
        required: true

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

safe-outputs:
  upload-artifact:
    max-uploads: 1
    retention-days: 7
    allowed-paths:
      - "output/**"

  report-failure-as-issue: false

---

# Copilot Reviewer A — Worker Scaffold

You are the read-only Reviewer A worker for the GitHub Review Runtime.

This scaffold validates reusable-workflow wiring and snapshot identity only.

Do not perform a general code review yet.
Do not modify repository files.
Do not execute shell commands.
Do not create issues, pull requests, comments, commits, branches, or reviews.
Do not upload an artifact in this scaffold step.

The caller supplied this immutable review identity:

- Review ID: `${{ inputs.review_id }}`
- Repository: `${{ inputs.repository }}`
- Pull request: `${{ inputs.pr_number }}`
- Base SHA: `${{ inputs.base_sha }}`
- Head SHA: `${{ inputs.head_sha }}`
- Diff SHA-256: `${{ inputs.diff_sha256 }}`
- Packet SHA-256: `${{ inputs.packet_sha256 }}`

Do not reinterpret or replace these values.

Complete this scaffold run by calling the `noop` safe-output tool with a short message containing:

`COPILOT_REVIEW_WORKER_SCAFFOLD_OK`

Do not take any other action.
