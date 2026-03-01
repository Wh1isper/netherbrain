"""Execution pipeline for the agent runtime.

This package contains the core execution components:

- **resolver**: Config resolution (preset + override + workspace -> ResolvedConfig)
- **environment**: Environment setup (project paths, virtual workspace, SDK Environment factory)
- **runtime**: SDK adapter (ResolvedConfig -> create_agent -> AgentRuntime)
- **input**: Input mapping (InputPart -> SDK UserPrompt)
- **prompt**: System prompt rendering (Jinja2 templates)
- **coordinator**: Execution orchestration (setup -> run -> finalize)
- **events**: Event processing (SDK events -> protocol events) [Phase 4]
- **transport**: Event delivery (SSE, Redis Stream) [Phase 4]
"""
