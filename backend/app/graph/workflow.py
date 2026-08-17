from langgraph.graph import StateGraph, END
from .state import KisanState
from langgraph.checkpoint.memory import MemorySaver
from .nodes import (
    profile_extractor_node, 
    completeness_checker_node, 
    question_generator_node,
    eligibility_filter_node
)

memory = MemorySaver()

def route_based_on_completeness(state: KisanState) -> str:
    """Conditional routing: If fields are missing, ask user. If complete, find schemes."""
    if state.get("missing_fields") and len(state["missing_fields"]) > 0:
        return "ask_user" 
    return "filter_schemes"

# Initialize the graph
workflow = StateGraph(KisanState)

# Add all nodes
workflow.add_node("extract_profile", profile_extractor_node)
workflow.add_node("check_completeness", completeness_checker_node)
workflow.add_node("ask_user", question_generator_node)
workflow.add_node("filter_schemes", eligibility_filter_node)

# Define the flow
workflow.set_entry_point("extract_profile")
workflow.add_edge("extract_profile", "check_completeness")

# Add conditional routing
workflow.add_conditional_edges(
    "check_completeness",
    route_based_on_completeness,
    {
        "ask_user": "ask_user",
        "filter_schemes": "filter_schemes"
    }
)

# When we ask the user a question, the graph pauses and waits for their next input.
# So, 'ask_user' leads to END for this current execution cycle.
workflow.add_edge("ask_user", END)

# After filtering schemes, the process is complete.
workflow.add_edge("filter_schemes", END)

# Compile the final agent
kisan_agent = workflow.compile(checkpointer=memory)