from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import observe_node, reason_node, decide_node, execute_node, broadcast_node


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("observe", observe_node)
    graph.add_node("reason", reason_node)
    graph.add_node("decide", decide_node)
    graph.add_node("execute", execute_node)
    graph.add_node("broadcast", broadcast_node)

    graph.add_edge("observe", "reason")
    graph.add_edge("reason", "decide")
    graph.add_edge("decide", "execute")
    graph.add_edge("execute", "broadcast")
    graph.add_conditional_edges(
        "broadcast",
        lambda s: "observe" if s.get("should_continue", True) else END,
        {"observe": "observe", END: END},
    )

    graph.set_entry_point("observe")
    return graph.compile()
