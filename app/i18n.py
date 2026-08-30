"""Interface strings in the four supported languages.

Every string a resident can see lives here, including error messages,
validation failures and the security notices. Section 3 requires all of it to
be localised, and a German error message on a French page is exactly the kind
of half-finished localisation that makes a public service feel unreliable.

German is first in every table because it is the official language of the
Canton of Zug and the language most sources are published in.
"""

from __future__ import annotations

from app.config import SUPPORTED_LANGUAGES

DEFAULT_LANGUAGE = "de"

# The unofficial-prototype notice required by section 22. Kept as one block so
# a translator sees the whole statement rather than fragments, and so no
# language can quietly lose a clause.
STRINGS: dict[str, dict[str, str]] = {
    "notice.title": {
        "de": "Inoffizieller KI-Prototyp",
        "en": "Unofficial AI prototype",
        "fr": "Prototype d'IA non officiel",
        "it": "Prototipo di IA non ufficiale",
    },
    "notice.body": {
        "de": (
            "Dies ist ein inoffizieller KI-Prototyp. Er wird nicht vom Kanton Zug "
            "betrieben oder unterstützt. Antworten können unvollständig oder "
            "veraltet sein. Bitte prüfen Sie wichtige Angaben anhand der zitierten "
            "offiziellen Quellen. Geben Sie keine persönlichen, vertraulichen, "
            "medizinischen, rechtlichen, steuerlichen oder fallbezogenen Angaben ein."
        ),
        "en": (
            "This is an unofficial AI prototype. It is not operated or endorsed by "
            "the Canton of Zug. Responses may be incomplete or outdated. Please "
            "verify important information using the cited official sources. Do not "
            "enter personal, confidential, medical, legal, tax or case-specific "
            "information."
        ),
        "fr": (
            "Ceci est un prototype d'IA non officiel. Il n'est ni exploité ni "
            "approuvé par le canton de Zoug. Les réponses peuvent être incomplètes "
            "ou obsolètes. Veuillez vérifier les informations importantes auprès "
            "des sources officielles citées. N'entrez aucune information "
            "personnelle, confidentielle, médicale, juridique, fiscale ou relative "
            "à un dossier."
        ),
        "it": (
            "Questo è un prototipo di IA non ufficiale. Non è gestito né approvato "
            "dal Cantone di Zugo. Le risposte possono essere incomplete o non "
            "aggiornate. Verifichi le informazioni importanti consultando le fonti "
            "ufficiali citate. Non inserisca dati personali, riservati, medici, "
            "legali, fiscali o relativi a un caso specifico."
        ),
    },
    "answer.insufficient_evidence": {
        "de": (
            "Ich konnte dazu keine gesicherten Angaben in den offiziellen Seiten "
            "des Kantons Zug finden. Bitte wenden Sie sich an die zuständige "
            "Stelle oder suchen Sie direkt auf zug.ch."
        ),
        "en": (
            "I could not find verified information about this in the Canton of "
            "Zug's official pages. Please contact the responsible office or search "
            "directly on zug.ch."
        ),
        "fr": (
            "Je n'ai pas trouvé d'informations vérifiées à ce sujet dans les pages "
            "officielles du canton de Zoug. Veuillez contacter le service compétent "
            "ou effectuer une recherche directement sur zug.ch."
        ),
        "it": (
            "Non ho trovato informazioni verificate in merito nelle pagine "
            "ufficiali del Cantone di Zugo. La preghiamo di contattare l'ufficio "
            "competente o di cercare direttamente su zug.ch."
        ),
    },
    "answer.unavailable": {
        "de": (
            "Der Assistent ist im Moment nicht erreichbar. Bitte versuchen Sie es "
            "später erneut oder nutzen Sie die Suche auf zug.ch."
        ),
        "en": (
            "The assistant is currently unavailable. Please try again later or use "
            "the search on zug.ch."
        ),
        "fr": (
            "L'assistant n'est pas disponible pour le moment. Veuillez réessayer "
            "plus tard ou utiliser la recherche sur zug.ch."
        ),
        "it": (
            "L'assistente non è al momento disponibile. La preghiamo di riprovare "
            "più tardi o di utilizzare la ricerca su zug.ch."
        ),
    },
    "answer.qualified": {
        "de": "Bitte prüfen Sie diese Angaben bei der zitierten Stelle.",
        "en": "Please confirm this with the cited office.",
        "fr": "Veuillez confirmer ces informations auprès du service cité.",
        "it": "La preghiamo di confermare queste informazioni presso l'ufficio citato.",
    },
    "answer.high_risk": {
        "de": (
            "Dies ist keine Rechts-, Steuer- oder Gesundheitsberatung und keine "
            "verbindliche Auskunft. Für Ihren konkreten Fall wenden Sie sich bitte "
            "an die zuständige Stelle."
        ),
        "en": (
            "This is not legal, tax or health advice and is not a binding "
            "statement. For your own situation, please contact the responsible "
            "office."
        ),
        "fr": (
            "Ceci ne constitue pas un conseil juridique, fiscal ou médical, ni une "
            "information contraignante. Pour votre situation, veuillez contacter le "
            "service compétent."
        ),
        "it": (
            "Questa non è consulenza legale, fiscale o sanitaria e non è "
            "un'informazione vincolante. Per il suo caso specifico, contatti "
            "l'ufficio competente."
        ),
    },
    "answer.emergency": {
        "de": (
            "Bei einem Notfall wählen Sie sofort 112 (allgemeiner Notruf), "
            "117 (Polizei), 118 (Feuerwehr) oder 144 (Ambulanz). "
            "Beratung: 143 (Die Dargebotene Hand), 147 (für Kinder und Jugendliche)."
        ),
        "en": (
            "In an emergency call 112 (general emergency), 117 (police), "
            "118 (fire) or 144 (ambulance) immediately. "
            "Support: 143 (helpline), 147 (for children and young people)."
        ),
        "fr": (
            "En cas d'urgence, appelez immédiatement le 112 (urgence générale), "
            "117 (police), 118 (pompiers) ou 144 (ambulance). "
            "Soutien : 143 (La Main Tendue), 147 (pour enfants et jeunes)."
        ),
        "it": (
            "In caso di emergenza chiami subito il 112 (emergenza generale), "
            "117 (polizia), 118 (pompieri) o 144 (ambulanza). "
            "Sostegno: 143 (Telefono Amico), 147 (per bambini e giovani)."
        ),
    },
    "answer.sources": {
        "de": "Quellen",
        "en": "Sources",
        "fr": "Sources",
        "it": "Fonti",
    },
    "answer.source_language_note": {
        "de": "Quelle auf",
        "en": "Source in",
        "fr": "Source en",
        "it": "Fonte in",
    },
    "answer.last_checked": {
        "de": "zuletzt geprüft",
        "en": "last checked",
        "fr": "dernière vérification",
        "it": "ultima verifica",
    },
    "chat.skip_to_content": {
        "de": "Zum Inhalt springen",
        "en": "Skip to content",
        "fr": "Aller au contenu",
        "it": "Vai al contenuto",
    },
    "chat.your_question": {
        "de": "Ihre Frage",
        "en": "Your question",
        "fr": "Votre question",
        "it": "La sua domanda",
    },
    "chat.answer_from_dumi": {
        "de": "Antwort von Dumi",
        "en": "Answer from Dumi",
        "fr": "Réponse de Dumi",
        "it": "Risposta di Dumi",
    },
    "chat.opens_new_tab": {
        "de": "öffnet in neuem Tab",
        "en": "opens in a new tab",
        "fr": "ouvre dans un nouvel onglet",
        "it": "si apre in una nuova scheda",
    },
    "chat.transcript": {
        "de": "Gesprächsverlauf",
        "en": "Conversation",
        "fr": "Conversation",
        "it": "Conversazione",
    },
    "chat.placeholder": {
        "de": "Stellen Sie eine Frage",
        "en": "Ask a question",
        "fr": "Posez une question",
        "it": "Faccia una domanda",
    },
    "chat.send": {
        "de": "Senden",
        "en": "Send",
        "fr": "Envoyer",
        "it": "Invia",
    },
    "chat.thinking": {
        "de": "Dumi sucht in den offiziellen Seiten",
        "en": "Dumi is searching the official pages",
        "fr": "Dumi cherche dans les pages officielles",
        "it": "Dumi sta cercando nelle pagine ufficiali",
    },
    "chat.stop": {
        "de": "Antwort stoppen",
        "en": "Stop the answer",
        "fr": "Arrêter la réponse",
        "it": "Interrompi la risposta",
    },
    "chat.language": {
        "de": "Sprache",
        "en": "Language",
        "fr": "Langue",
        "it": "Lingua",
    },
    "error.too_many_requests": {
        "de": "Zu viele Anfragen. Bitte warten Sie einen Moment.",
        "en": "Too many requests. Please wait a moment.",
        "fr": "Trop de requêtes. Veuillez patienter un instant.",
        "it": "Troppe richieste. Attenda un momento.",
    },
    "error.question_too_long": {
        "de": "Die Frage ist zu lang. Bitte kürzen Sie sie.",
        "en": "That question is too long. Please shorten it.",
        "fr": "Cette question est trop longue. Veuillez la raccourcir.",
        "it": "La domanda è troppo lunga. La accorci.",
    },
    "error.question_empty": {
        "de": "Bitte geben Sie eine Frage ein.",
        "en": "Please enter a question.",
        "fr": "Veuillez saisir une question.",
        "it": "Inserisca una domanda.",
    },
    # Password policy messages, returned as keys by app.security.passwords.
    "password.too_short": {
        "de": "Das Passwort muss mindestens 12 Zeichen lang sein.",
        "en": "The password must be at least 12 characters long.",
        "fr": "Le mot de passe doit comporter au moins 12 caractères.",
        "it": "La password deve contenere almeno 12 caratteri.",
    },
    "password.too_long": {
        "de": "Das Passwort ist zu lang.",
        "en": "The password is too long.",
        "fr": "Le mot de passe est trop long.",
        "it": "La password è troppo lunga.",
    },
    "password.known_weak": {
        "de": "Dieses Passwort ist bekannt und unsicher. Bitte wählen Sie ein anderes.",
        "en": "This password is known and unsafe. Please choose another.",
        "fr": "Ce mot de passe est connu et non sécurisé. Veuillez en choisir un autre.",
        "it": "Questa password è nota e non sicura. Ne scelga un'altra.",
    },
    "password.contains_email": {
        "de": "Das Passwort darf Ihre E-Mail-Adresse nicht enthalten.",
        "en": "The password must not contain your email address.",
        "fr": "Le mot de passe ne doit pas contenir votre adresse e-mail.",
        "it": "La password non deve contenere il suo indirizzo e-mail.",
    },
    "password.too_repetitive": {
        "de": "Das Passwort besteht aus zu wenigen verschiedenen Zeichen.",
        "en": "The password uses too few different characters.",
        "fr": "Le mot de passe utilise trop peu de caractères différents.",
        "it": "La password utilizza troppi pochi caratteri diversi.",
    },
    "password.sequential": {
        "de": "Das Passwort enthält eine einfache Zeichenfolge.",
        "en": "The password contains a simple sequence.",
        "fr": "Le mot de passe contient une séquence simple.",
        "it": "La password contiene una sequenza semplice.",
    },
}


def normalise_language(value: str | None) -> str:
    """Return a supported language code, falling back to German.

    Accepts "de-CH" and "DE" as German. An unsupported language falls back
    rather than raising: a resident whose browser asks for Romansh should get
    a usable page, not an error.
    """
    if not value:
        return DEFAULT_LANGUAGE
    candidate = value.strip().lower().replace("_", "-").split("-")[0]
    return candidate if candidate in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def negotiate_language(accept_language: str | None) -> str:
    """Pick a language from an Accept-Language header.

    Quality values are honoured, so a browser preferring French over German
    gets French. Malformed headers fall back rather than raising.
    """
    if not accept_language:
        return DEFAULT_LANGUAGE

    candidates: list[tuple[float, str]] = []
    for part in accept_language.split(",")[:20]:
        piece = part.strip()
        if not piece:
            continue
        quality = 1.0
        if ";" in piece:
            piece, _, params = piece.partition(";")
            for param in params.split(";"):
                key, _, value = param.strip().partition("=")
                if key.strip().lower() == "q":
                    try:
                        quality = float(value)
                    except ValueError:
                        quality = 0.0
        language = piece.strip().lower().split("-")[0]
        if language in SUPPORTED_LANGUAGES:
            candidates.append((quality, language))

    if not candidates:
        return DEFAULT_LANGUAGE
    return max(candidates, key=lambda item: item[0])[1]


def t(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Return a localised string.

    A missing translation falls back to German rather than to the key, because
    showing "answer.insufficient_evidence" to a resident is worse than showing
    the German sentence.
    """
    table = STRINGS.get(key)
    if table is None:
        return key
    return table.get(language) or table.get(DEFAULT_LANGUAGE) or key


def missing_translations() -> dict[str, tuple[str, ...]]:
    """Report keys lacking a translation, for the test suite and CI."""
    gaps: dict[str, tuple[str, ...]] = {}
    for key, table in STRINGS.items():
        absent = tuple(lang for lang in SUPPORTED_LANGUAGES if not table.get(lang))
        if absent:
            gaps[key] = absent
    return gaps
