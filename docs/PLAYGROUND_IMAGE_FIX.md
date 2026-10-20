# Playground and Qwen Image Verification

Date: 2026-10-19

## Scope

This change repairs image generation and replaces the Playground Chat tab with
a conversational interface. It does not claim a complete redesign or audit of
the other six management pages.

No database migration, credential changes, authentication redesign, or Redis
schema change was made. Existing response fields remain compatible; an optional
image URL list was added to the unified LLM response.

## Root causes and fixes

1. The image client only parsed the legacy `output.results[].url` response.
   Real qwen-image-3.0 synchronous responses used
   `output.choices[].message.content[].image`. Both formats are now supported,
   and an empty image list is reported as an error rather than a successful reply.
2. Auto could return an old text cache hit before routing a generation request.
   Explicit image requests now bypass the text cache; image outputs are not
   inserted into that cache, because their URLs expire and are not text answers.
3. The local intent check missed phrases with subject words between "generate"
   and "image", including the user's Chinese example. It now handles those
   phrases, examines the latest user turn, and excludes common negations and
   explanatory questions. Ambiguous intent still uses the existing classifier.
4. The frontend only rendered answer text. It now renders the explicit images
   list, with an original-image link and a load/expiry error state.
5. Chat-compatible base URLs are normalized to the native image API endpoint.
   Image read timeout is at least 180 seconds; the Chat browser wait is 240 seconds
   because Auto may select image generation.
6. Playground now has a scrollable question/answer timeline, bottom composer,
   multi-turn text context, per-account local drafts and conversation storage,
   fullscreen controls, settings, route preview, copy/download, request details,
   visible failures, explicit retry and stop-waiting controls.
7. Existing Raw Request, Routing Preview and Batch Test tabs remain available.
   Old Chat rendering code and unused Chat fullscreen/layout overrides were removed.
8. Request IDs in response context now match the persisted history request ID.

## Files changed

| File | Change |
| --- | --- |
| app/clients/qwen_image_client.py | Simplified native client, correct image extraction, URL normalization, prompt extraction, actionable failures. |
| app/providers/qwen_image_provider.py | Populate the unified response's image list. |
| app/providers/factory.py | Image client receives a minimum 180-second read timeout. |
| app/schemas/llm_response.py | Add backward-compatible images list with an empty-list default. |
| app/config/settings.py | Correct default image base URL to native DashScope /api/v1. |
| app/routing/modality_router.py | Recognize Chinese/English image-generation intent from the latest user turn. |
| app/routing/model_router.py | Routing explanations no longer falsely attribute local detection to a classifier call. |
| app/gateway.py | Isolate images from text cache; align context and history request IDs. |
| frontend/js/app.js | Remove obsolete Chat implementation; support caller cancellation in the shared API helper. |
| frontend/js/playground-chat.js | New conversational UI and state handling. |
| frontend/css/app.css | Remove obsolete Chat-specific layout and fullscreen styles. |
| frontend/css/playground.css | Scoped desktop/mobile chat layout, scrolling, images, Markdown and fullscreen presentation. |
| frontend/pages/playground.html | Load the new Chat assets and local Markdown dependencies. |
| frontend/assets/icons/arrow-up.svg | Lucide send icon. |
| frontend/assets/icons/copy.svg | Lucide copy icon. |
| frontend/assets/icons/download.svg | Lucide response export icon. |
| frontend/assets/icons/maximize-2.svg | Lucide expand icon. |
| frontend/assets/icons/minimize-2.svg | Lucide exit-fullscreen icon. |
| frontend/assets/icons/plus.svg | Lucide new-conversation icon. |
| frontend/assets/icons/route.svg | Lucide routing-preview icon. |
| frontend/assets/icons/sliders-horizontal.svg | Lucide settings icon. |
| frontend/assets/icons/square.svg | Lucide stop-waiting icon. |
| frontend/assets/icons/x.svg | Lucide dialog-close icon. |
| frontend/assets/icons/LICENSE | Lucide 0.468.0 license. |
| frontend/vendor/marked.umd.js | Vendored Marked 15.0.12 Markdown parser, no runtime CDN request. |
| frontend/vendor/marked.LICENSE | Marked license. |
| frontend/vendor/purify.min.js | Vendored DOMPurify 3.4.17 HTML sanitizer. |
| frontend/vendor/dompurify.LICENSE | DOMPurify license. |
| tests/test_image_generation.py | Image client, intent, cache isolation and error-path regressions. |
| tests/test_model_routing.py | Make existing text-routing unit tests deterministic and offline. |
| tests/playground.browser.cjs | Browser interactions, responsive layout, security checks and opt-in real generation tests. |
| .gitignore | Exclude local screenshots/logs that may contain account and conversation data. |
| docs/PLAYGROUND_IMAGE_FIX.md | This change record and verification instructions. |

## Verification results

- Python: 13 test methods passed, including the existing 18 text-routing
  benchmark prompts and new image-intent variants.
- Direct Qwen HTTP request with existing credentials: HTTP 200, one image, 62.3 s.
- Browser Auto image request: HTTP 200, qwen_image / qwen-image-3.0,
  image decoded successfully, 62.55 s.
- Browser manual image request: HTTP 200, qwen_image / qwen-image-3.0,
  image decoded successfully, 80.33 s.
- Browser text request following images: DeepSeek reply succeeded, 1.85 s.
- Latest backend on port 8000: another real DeepSeek request returned OK;
  lookup of its returned request ID in history returned HTTP 200.
- Browser checks passed for settings validation, drafts across tabs/navigation/
  reload, both fullscreen controls, Auto routing preview, copy, export,
  request details, image conversation restoration, scrolling at 1440x960 and
  390x844, errors/retry, cancellation, new conversation, and empty-submit handling.
- Markdown formatting and HTML/script-injection regression passed.
- No uncaught browser JavaScript errors in the verification runs.
- Error and cancellation tests use intercepted test-only responses, not fake
  production data. Long-text layout tests use clearly isolated fixtures.

Artifacts:

- test-results/playground/results.json: live-generation run.
- test-results/playground-regression/results.json: latest non-billable UI regression.
- Screenshots in those directories include actual generated images and desktop/
  mobile layouts. These artifacts are ignored by Git.

## Configuration and startup

Existing Qwen credentials and model worked in live tests. No additional SDK,
model download, new key, or account change was needed on this machine.
For another installation, set QWEN_IMAGE_API_KEY, QWEN_IMAGE_MODEL and
QWEN_IMAGE_BASE_URL for the same DashScope region/account.

From the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Open http://127.0.0.1:8000/pages/playground.html. Restart any already-running
backend after changing Python files. The current verified service was started
on port 8000; avoid starting a second instance on that port.

Browser tests require Node, Playwright and Microsoft Edge (or BROWSER_CHANNEL).
Set GATEWAY_URL to the local running server and run
`node tests/playground.browser.cjs`. A verified local development account is
required; the test uses the project's token helper without logging the token.
`LIVE_IMAGES=1` enables two billable image calls and one text call; it is off by
default. The image-history display test expects a previous successful image
request whose provider URL has not expired.

## Boundaries

- Stop waiting cancels the browser wait, not an already-running upstream job.
  Navigating away during generation prompts for confirmation. Interrupted turns
  remain visible, with a link to Requests; the UI does not silently resubmit them.
- Drafts and the current conversation are stored per account in this browser.
  They are not cross-device chat synchronization. Persisted gateway history is
  still available separately in Requests.
- Image URLs have provider-controlled expiry. This change does not download or
  permanently host generated images.
- Image billing is not derived from text token prices. The image detail panel
  shows pricing as unconfigured rather than claiming the generation was free.
- The HTTP response is still non-streaming; a real waiting status is displayed
  until completion. Image generation time varies with the upstream service.
- Existing image understanding/editing and arbitrary custom-provider image
  protocols are not added by this change.

API reference checked:
https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference
