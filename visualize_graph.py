"""Visualize the current LangGraph topology."""

from src.graph import build_graph

def main():
    graph = build_graph()
    
    # Generate Mermaid source
    print("Generating Mermaid graph...")
    try:
        mermaid_png = graph.get_graph().draw_mermaid_png()
        output_path = "langgraph_topology.png"
        with open(output_path, "wb") as f:
            f.write(mermaid_png)
        print(f"Graph saved to {output_path}")
        
        # Also print the ASCII representation for quick check
        print("\nASCII Representation:")
        graph.get_graph().print_ascii()
        
    except Exception as e:
        print(f"Error visualizing graph: {e}")
        print("Make sure you have `langgraph` and `grandalf` (for ascii) installed.")

if __name__ == "__main__":
    main()

