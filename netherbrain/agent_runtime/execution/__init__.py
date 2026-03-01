"""Execution pipeline for the agent runtime.

This package contains the core execution components:

- **resolver**: Config resolution (preset + override + workspace -> ResolvedConfig)
- **environment**: Environment setup (project paths, shell mode)
- **adapter**: SDK integration (ResolvedConfig -> create_agent)
- **events**: Event processing (SDK events -> protocol events)
- **transport**: Event delivery (SSE, Redis Stream)
- **coordinator**: Execution orchestration (setup -> run -> finalize)
"""
