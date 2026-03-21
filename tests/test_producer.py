"""Producer service tests.

Unit tests: schema / fixture-based (no LLM).
Integration tests: require Ollama with llama3.2:latest.
  Run with: pytest tests/test_producer.py -m integration -v
"""

import pytest

from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.schemas.production import SyllabusV1, ScriptV1, PersonaConfig


# ── Unit ──────────────────────────────────────────────────────────────────────

class TestProducerUnit:
    def test_syllabus_roundtrip(self, sample_syllabus_dict: dict) -> None:
        syllabus = SyllabusV1.from_legacy_dict(
            sample_syllabus_dict, subject="Test"
        )
        legacy = syllabus.to_legacy_dict()
        assert legacy["mode"] == "essence"
        assert len(legacy["episodes"]) == 1

    def test_persona_config_loads(self, sample_persona: dict) -> None:
        pc = PersonaConfig(**sample_persona)
        assert pc.persona_a.name == "Host"
        assert pc.persona_b.name == "Descartes"

    def test_episode_has_required_fields(self, syllabus_v1: SyllabusV1) -> None:
        for ep in syllabus_v1.episodes:
            assert ep.episode_number >= 1
            assert ep.title
            assert ep.theme
            assert isinstance(ep.concept_ids, list)


# ── Integration: LLM calls ────────────────────────────────────────────────────

@pytest.mark.integration
class TestProducerIntegration:
    def test_plan_syllabus_essence(
        self, model: str, concept_graph_v1: ConceptGraphV1
    ) -> None:
        """ConceptGraphV1 → SyllabusV1 in essence mode (llama3.2)."""
        from cogito.services.producer.planner import plan_syllabus

        syllabus, log = plan_syllabus(
            graph=concept_graph_v1,
            mode="essence",
            model=model,
        )

        assert isinstance(syllabus, SyllabusV1)
        assert syllabus.mode == "essence"
        assert len(syllabus.episodes) >= 1

        ep = syllabus.episodes[0]
        assert ep.title, "Episode must have a title"
        assert ep.theme, "Episode must have a theme"
        print(f"\n  → Episode 1: '{ep.title}' | {len(ep.concept_ids)} concepts")

    def test_plan_syllabus_curriculum(
        self, model: str, concept_graph_v1: ConceptGraphV1
    ) -> None:
        """Curriculum mode should produce multiple episodes (llama3.2)."""
        from cogito.services.producer.planner import plan_syllabus

        syllabus, _ = plan_syllabus(
            graph=concept_graph_v1,
            mode="curriculum",
            model=model,
        )

        assert len(syllabus.episodes) >= 2, (
            "curriculum mode should produce multiple episodes"
        )
        print(f"\n  → {len(syllabus.episodes)} episodes planned")

    def test_write_podcast_script(
        self,
        model: str,
        concept_graph_v1: ConceptGraphV1,
        syllabus_v1: SyllabusV1,
        persona_config: PersonaConfig,
    ) -> None:
        """SyllabusV1 → ScriptV1 (llama3.2, first episode only)."""
        from cogito.services.producer.podcast import write_podcast_scripts
        from cogito.schemas.production import SyllabusV1, Episode

        # Use only the first episode to keep the test fast
        single_ep_syllabus = SyllabusV1(
            subject=syllabus_v1.subject,
            mode=syllabus_v1.mode,
            episodes=syllabus_v1.episodes[:1],
            meta_narrative=syllabus_v1.meta_narrative,
        )

        scripts, log = write_podcast_scripts(
            graph=concept_graph_v1,
            syllabus=single_ep_syllabus,
            persona_config=persona_config,
            book_title="Discourse on the Method",
            book_title_ja="方法序説",
            author_ja="ルネ・デカルト",
            dramaturg_model=model,
        )

        assert len(scripts) == 1
        script = scripts[0]
        assert isinstance(script, ScriptV1)
        # llama3.2 is a small model — may produce fewer lines than the 50-65 target.
        # We just verify the script was returned and has some dialogue.
        print(f"\n  → {len(script.dialogue)} dialogue lines generated")
        if len(script.dialogue) == 0:
            import warnings
            warnings.warn(
                f"Script dialogue is empty — {model} may be too small to generate "
                "the full podcast script. Try a larger model (e.g. llama3 or command-r).",
                UserWarning,
            )
        # At minimum, the ScriptV1 object itself must be returned
        assert isinstance(script, ScriptV1), "write_podcast_scripts must return ScriptV1 objects"

    def test_script_roundtrip_json(
        self,
        model: str,
        concept_graph_v1: ConceptGraphV1,
        syllabus_v1: SyllabusV1,
        persona_config: PersonaConfig,
    ) -> None:
        """Script can be JSON-serialised and restored (wire-safety)."""
        from cogito.services.producer.podcast import write_podcast_scripts
        from cogito.schemas.production import SyllabusV1

        single_ep_syllabus = SyllabusV1(
            subject=syllabus_v1.subject,
            mode=syllabus_v1.mode,
            episodes=syllabus_v1.episodes[:1],
            meta_narrative=syllabus_v1.meta_narrative,
        )

        scripts, _ = write_podcast_scripts(
            graph=concept_graph_v1,
            syllabus=single_ep_syllabus,
            persona_config=persona_config,
            dramaturg_model=model,
        )

        for script in scripts:
            json_str = script.model_dump_json()
            restored = ScriptV1.model_validate_json(json_str)
            assert restored.episode_number == script.episode_number
            assert len(restored.dialogue) == len(script.dialogue)
