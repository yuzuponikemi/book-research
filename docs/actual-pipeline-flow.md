# Actual Pipeline Flow (as implemented in main.py)

This diagram represents the *actual* execution flow currently orchestrated by `main.py`. This is richer than the `src/graph.py` definition because `main.py` manually calls additional modules.

```mermaid
1graph TD
    Start([Start]) --> Ingest[<b>1. Ingest</b><br>Load & Chunk Text]
    Ingest --> Analyze[<b>2. Analyze Chunks</b><br>Extract Concepts per Chunk]
    Analyze --> Synthesize[<b>3. Synthesize</b><br>Build Unified Concept Graph]

    subgraph Research Loop [Optional Research Stage]
        Synthesize -->|if not skip_research| Research[<b>3b. Research</b><br>Web Search & Ref Summary]
        Research --> Critique[<b>3c. Critique</b><br>Generate Criticisms]
        Critique --> Enrich[<b>3d. Enrich</b><br>Create Context Narratives]
        Enrich --> ReadingMat[<b>3e. Reading Material</b><br>Write Study Guide]
    end

    Synthesize -->|skip_research| Plan
    Enrich --> Plan[<b>4. Plan</b><br>Create Syllabus]
    
    Plan --> Script[<b>5. Write Scripts</b><br>Generate Dialogue]
    
    Script -->|if not skip_audio| Audio[<b>6. Audio Synthesis</b><br>VOICEVOX]
    Script -->|skip_audio| Translate
    Audio --> Translate
    
    Translate[<b>7. Translate</b><br>Translate Intermediate Files to JA] --> End([End])

    %% Data dependencies
    ReadingMat -.->|uses| Enrich
    Script -.->|uses| Enrich
    Script -.->|uses| Plan
```

## Key Differences from `src/graph.py`

*   **Research Loop**: The steps `Research` -> `Critique` -> `Enrich` -> `Reading Material` are executed conditionally in `main.py` but are not part of the formal `StateGraph` in `src/graph.py`.
*   **Translation**: The translation step is a post-processing utility called at the end, not a graph node.
*   **Audio**: Audio synthesis is also a conditional step in `main.py`.

To fully leverage LangGraph features (checkpointing, human-in-the-loop, conditional routing), these steps should eventually be moved into `src/graph.py`.
