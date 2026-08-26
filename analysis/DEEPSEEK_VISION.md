# DeepSeek Vision & Model Capability — current knowledge

## Does DeepSeek accept images?

**Yes, DeepSeek has vision capability** — with a specific caveat about the hosted
API.

### What exists
- Open-source vision model: [DeepSeek-VL](https://github.com/deepseek-ai/deepseek-vl)
  and paper https://arxiv.org/html/2403.05525v2 (since March 2024).
- Current V-series line includes vision-capable variants (e.g., a "DeepSeek V4
  Flash Vision" build — third-party source:
  https://chat-deep.ai/models/deepseek-v4-flash-vision-exp/).
- Official [DeepSeek-V3.1](https://huggingface.co/deepseek-ai/DeepSeek-V3.1) has
  multimodal variants.

## The caveat: hosted API image-input
- The thing to confirm before building is whether the **hosted API** accepts image
  input (an `image_url` part in `content`).
- Authoritative source: https://api-docs.deepseek.com/api/create-chat-completion
  and the change log https://api-docs.deepseek.com/updates
- Historically the July 2025 API upgrade
  (https://api-docs.deepseek.com/news/news0725) covered text tools (JSON output,
  function calling, FIM); vision support has been rolling out around/after that.

## Current agent limitation
- The model running this session (deepseek-v4-flash:cloud) **does not accept
  images yet**. This means the "feed meta screenshots to the agent" idea cannot be
  tested on *this* agent right now.

## Implications for the coach
- The eventual coach agent should use a **vision-capable model** OR the hosted API
  (if it accepts images).
- Until then, the immediate work (parsing `Power.log`) does **not** require vision.

## Design consequence (legibility)
Whichever vision model is used, meta screenshots are dense with small text. Verify
the model actually reads them correctly: scale/crop dense text and pair images with
a short text caption as a reliable fallback (breakoutBot verification discipline).
