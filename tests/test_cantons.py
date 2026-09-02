"""The canton registry and the strings built from it.

One interface serves several cantons. These tests pin the two guarantees
that make that safe: every canton carries every phrase in every supported
language, so no canton ever renders a half-translated sentence, and the
string table completes its placeholders for whichever canton is asked.
"""

from app.cantons import CANTONS, get_canton, normalise_canton
from app.config import SUPPORTED_LANGUAGES
from app.i18n import STRINGS, t


class TestRegistry:
    def test_zug_and_uri_are_configured(self) -> None:
        assert "zug" in CANTONS
        assert "uri" in CANTONS

    def test_an_unknown_canton_falls_back_to_the_default(self) -> None:
        assert normalise_canton("geneva") == "zug"
        assert normalise_canton(None) == "zug"
        assert normalise_canton(" URI ") == "uri"

    def test_every_canton_carries_every_phrase_in_every_language(self) -> None:
        """A missing phrase would surface as a German fragment inside a
        French sentence, which is the localisation failure the project
        forbids."""
        for canton in CANTONS.values():
            for language in SUPPORTED_LANGUAGES:
                assert canton.names.get(language), (canton.slug, language)
                assert canton.of_phrases.get(language), (canton.slug, language)
                assert canton.by_phrases.get(language), (canton.slug, language)
            assert canton.portal_label
            assert canton.portal_url.startswith("https://")
            assert canton.hosts
            assert canton.accent_rgb

    def test_the_french_genitive_differs_between_cantons(self) -> None:
        """The reason phrases are stored whole: "de Zoug" but "d'Uri"."""
        assert "de Zoug" in get_canton("zug").of_phrase("fr")
        assert "d'Uri" in get_canton("uri").of_phrase("fr")


class TestCantonStrings:
    def test_the_refusal_names_the_selected_canton_and_portal(self) -> None:
        text = t("answer.insufficient_evidence", "de", canton=get_canton("uri"))
        assert "des Kantons Uri" in text
        assert "uri.ch" in text
        assert "Zug" not in text

    def test_the_default_canton_is_zug(self) -> None:
        text = t("answer.insufficient_evidence", "de")
        assert "des Kantons Zug" in text
        assert "zg.ch" in text

    def test_no_string_leaks_a_placeholder(self) -> None:
        """Every placeholder in every string must be one t() completes."""
        for canton in CANTONS.values():
            for key in STRINGS:
                for language in SUPPORTED_LANGUAGES:
                    text = t(key, language, canton=canton)
                    assert "{canton" not in text, (key, language)
                    assert "{portal" not in text, (key, language)

    def test_no_string_hardcodes_a_canton(self) -> None:
        """A sentence naming Zug must come from the registry, not the string
        table, or the Uri deployment would speak about Zug."""
        for key, table in STRINGS.items():
            for language, text in table.items():
                for marker in ("Zug", "Zoug", "Zugo", "zg.ch", "zug.ch"):
                    assert marker not in text, (key, language, marker)
