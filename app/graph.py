from langgraph.graph import StateGraph, END
from app.state import SQLAgentState
from app import nodes


def build_graph():
    graph = StateGraph(SQLAgentState)

    graph.add_node("detect_intent", nodes.detect_intent)
    graph.add_node("generate_sql", nodes.generate_sql)
    graph.add_node("validate", nodes.validate)
    graph.add_node("execute", nodes.execute)
    graph.add_node("repair_sql", nodes.repair_sql)
    graph.add_node("give_up", nodes.give_up)
    graph.add_node("interpret_results", nodes.interpret_results)
    graph.add_node("generate_chart", nodes.generate_chart)
    graph.add_node("generate_followups", nodes.generate_followups)

    graph.set_entry_point("detect_intent")

    # Ambiguity detection short-circuits the whole pipeline
    graph.add_conditional_edges(
        "detect_intent",
        lambda s: "clarify" if s.get("needs_clarification") else "proceed",
        {"clarify": END, "proceed": "generate_sql"},
    )

    graph.add_edge("generate_sql", "validate")
    graph.add_edge("validate", "execute")

    graph.add_conditional_edges(
        "execute",
        nodes.execution_router,
        {"success": "interpret_results", "fail": "repair_sql"},
    )

    graph.add_conditional_edges(
        "repair_sql",
        nodes.retry_router,
        {"retry": "validate", "give_up": "give_up"},
    )

    graph.add_edge("give_up", END)
    
    # Validation step post-execution
    graph.add_conditional_edges(
        "interpret_results",
        nodes.interpretation_router,
        {"repair": "repair_sql", "proceed": "generate_chart"}
    )
    
    graph.add_edge("generate_chart", "generate_followups")
    graph.add_edge("generate_followups", END)

    return graph.compile()


# Compiled once, reused across requests
compiled_graph = build_graph()
