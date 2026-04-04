# Release History & Next Steps

## v0.5.0 -- Extract, Scrape & Proxy (Current)

- [x] `extract` command -- LLM-powered structured data extraction with JSON Schema validation
- [x] `scrape` command -- HTML-to-markdown/text/html conversion with main content extraction
- [x] Proxy support -- `--proxy` flag on discover/run/extract/scrape, ProxyConfig class
- [x] `--format` flag on `run` -- json/markdown/text output
- [x] `content` optional dependency -- markdownify for HTML conversion
- [x] 60 new tests (test_content_converter, test_extract, test_proxy)
- [x] Documentation updated (README, CLAUDE.md, PLAN.md)
- [x] PyPI release

## v0.4.0 -- OAuth & Orchestration (Complete)

- [x] OAuth device flow (RFC 8628) -- GitHub, Google, Microsoft
- [x] Multi-site orchestration -- YAML/JSON pipelines with JSONPath data flow
- [x] Pipeline management -- orchestrate run/list/delete with error policies

## Future

- [ ] Trained endpoint classifier (replace heuristics)
- [ ] WebSocket traffic capture
- [ ] Streaming response support
- [ ] Extract/scrape demo GIFs for README
