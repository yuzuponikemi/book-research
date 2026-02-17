"""Phoenix local tracing setup."""

import phoenix as px
from openinference.instrumentation.langchain import LangChainInstrumentor


def setup_tracing():
    """Launch local Phoenix and instrument LangChain."""
    session = px.launch_app()
    LangChainInstrumentor().instrument()
    print(f"  Phoenix UI: {session.url}")
    return session
