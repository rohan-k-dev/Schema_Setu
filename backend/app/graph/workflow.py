"""
LangGraph workflow construction — Phase 5 multi-agent architecture.

Graph topology (§238, §281):
    START → profile_agent → completeness_agent
        → [incomplete/conflict] → question_agent → END
        → [complete] → query_rewriter
            → [needs_clarification] → question_agent → END
            → [clear] → retrieval_agent → eligibility_agent
                → recommendation_agent → response_formatter → END

Routing logic is imported from routing.py.
Agent functions are imported from agents/ modules.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings
from app.graph.state import SchemeSetuState
from app.graph.routing import route_after_completeness, route_after_query_rewrite
from app.agents.profile_agent import profile_agent_node
from app.agents.completeness_agent import completeness_agent_node
from app.agents.question_agent import question_agent_node
from app.agents.query_rewriter import query_rewriter_node
from app.agents.retrieval_agent import retrieval_agent_node
from app.agents.eligibility_agent import eligibility_agent
from app.agents.recommendation_agent import recommendation_agent
from app.agents.response_formatter import response_formatter_node

class BoundedMemorySaver(MemorySaver):
    """
    In-memory checkpointer with a session cap and a constant-cost repr.

    Phase 7 BUG-025: LangChain's tracing serialises the compiled graph with
    repr() on every request; the stock MemorySaver repr includes every stored
    conversation, so request latency grew with the number of sessions since
    start-up and memory was never released. This saver keeps at most
    `max_threads` conversations (least recently written evicted first).
    """

    max_threads: int = 1000

    def put(self, config, checkpoint):
        thread_id = config["configurable"]["thread_id"]
        result = super().put(config, checkpoint)
        # re-insert to mark as most recently used (dicts keep insertion order)
        self.storage[thread_id] = self.storage.pop(thread_id)
        while len(self.storage) > self.max_threads:
            oldest = next(iter(self.storage))
            del self.storage[oldest]
        return result

    # pydantic-v1 __eq__ compares .dict() — i.e. every stored conversation.
    # LangGraph compares the checkpointer several times per request, which made
    # request cost grow linearly with stored sessions. Identity is the right notion.
    def __eq__(self, other) -> bool:
        return self is other

    __hash__ = object.__hash__

    def __repr__(self) -> str:
        return f"BoundedMemorySaver(threads={len(self.storage)}, max_threads={self.max_threads})"

    def __repr_args__(self):
        return [("threads", len(self.storage)), ("max_threads", self.max_threads)]


# In-memory checkpointer for multi-turn conversation state
# Isolated per thread_id (§56, §97)
memory = BoundedMemorySaver(max_threads=settings.MAX_SESSIONS)

# --- Build the graph ---
workflow = StateGraph(SchemeSetuState)

# Add nodes (§150–152, §238)
workflow.add_node("profile_agent", profile_agent_node)
workflow.add_node("completeness_agent", completeness_agent_node)
workflow.add_node("question_agent", question_agent_node)
workflow.add_node("query_rewriter", query_rewriter_node)
workflow.add_node("retrieval_agent", retrieval_agent_node)
workflow.add_node("eligibility_agent", eligibility_agent)
workflow.add_node("recommendation_agent", recommendation_agent)
workflow.add_node("response_formatter", response_formatter_node)

# Define the flow (§8, §201, §281)
workflow.set_entry_point("profile_agent")
workflow.add_edge("profile_agent", "completeness_agent")

# Conditional routing after completeness check
workflow.add_conditional_edges(
    "completeness_agent",
    route_after_completeness,
    {
        "question_agent": "question_agent",
        "query_rewriter": "query_rewriter",
    }
)

# Conditional routing after query rewrite
workflow.add_conditional_edges(
    "query_rewriter",
    route_after_query_rewrite,
    {
        "question_agent": "question_agent",
        "retrieval_agent": "retrieval_agent",
    }
)

# Linear edges — Phase 5 adds eligibility + recommendation between retrieval and response
workflow.add_edge("retrieval_agent", "eligibility_agent")
workflow.add_edge("eligibility_agent", "recommendation_agent")
workflow.add_edge("recommendation_agent", "response_formatter")

# Terminal edges — graph pauses after question or response
workflow.add_edge("question_agent", END)
workflow.add_edge("response_formatter", END)

# Compile the agent with memory checkpointing (§97)
kisan_agent = workflow.compile(checkpointer=memory)