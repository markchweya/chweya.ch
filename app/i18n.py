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
    "answer.uncited": {
        "de": (
            "Ich habe passende offizielle Seiten gefunden, konnte meine Antwort "
            "aber nicht zuverlässig mit ihnen belegen. Deshalb zeige ich sie "
            "nicht an. Die Quellen unten führen direkt zu den Seiten, die Ihre "
            "Frage behandeln."
        ),
        "en": (
            "I found relevant official pages, but I could not reliably tie my "
            "answer to them, so I am not showing it. The sources below lead "
            "directly to the pages that cover your question."
        ),
        "fr": (
            "J'ai trouvé des pages officielles pertinentes, mais je n'ai pas pu "
            "relier ma réponse à ces pages de manière fiable, donc je ne "
            "l'affiche pas. Les sources ci-dessous mènent directement aux pages "
            "qui traitent de votre question."
        ),
        "it": (
            "Ho trovato pagine ufficiali pertinenti, ma non sono riuscito a "
            "collegare la mia risposta a queste pagine in modo affidabile, "
            "quindi non la mostro. Le fonti qui sotto portano direttamente alle "
            "pagine che trattano la sua domanda."
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
    # Social replies. Fixed strings, never model output: a greeting carries
    # no factual claim, so it needs no evidence, but letting the model chat
    # freely would reopen the door the fail-closed design keeps shut.
    "answer.greeting": {
        "de": (
            "Hallo! Ich bin Dumi und beantworte Fragen zu den Dienstleistungen "
            "des Kantons Zug: Adresse anmelden, Ausweis beantragen, Steuern, "
            "Abfall und mehr. Was möchten Sie wissen?"
        ),
        "en": (
            "Hello! I am Dumi and I answer questions about Canton of Zug "
            "services: registering an address, applying for an ID, taxes, "
            "waste disposal and more. What would you like to know?"
        ),
        "fr": (
            "Bonjour ! Je suis Dumi et je réponds aux questions sur les "
            "prestations du canton de Zoug : annoncer son arrivée, demander "
            "une carte d'identité, les impôts, les déchets et plus encore. "
            "Que souhaitez-vous savoir ?"
        ),
        "it": (
            "Salve! Sono Dumi e rispondo a domande sui servizi del Canton "
            "Zugo: notifica del domicilio, richiesta della carta d'identità, "
            "imposte, rifiuti e altro. Cosa desidera sapere?"
        ),
    },
    "answer.thanks": {
        "de": "Gern geschehen. Wenn Sie noch eine Frage haben, bin ich hier.",
        "en": "You are welcome. If you have another question, I am here.",
        "fr": "Avec plaisir. Si vous avez une autre question, je suis là.",
        "it": "Prego. Se ha un'altra domanda, sono qui.",
    },
    # The self-description. It says plainly what this is and is not: answers
    # come from published official content with sources shown, and personal
    # cases belong with the responsible office.
    "answer.about": {
        "de": (
            "Ich bin Dumi, ein Assistent für Fragen zu den Dienstleistungen "
            "des Kantons Zug. Ich antworte ausschliesslich auf Grundlage "
            "veröffentlichter offizieller Informationen und zeige zu jeder "
            "Antwort die Quellen. Fragen Sie mich zum Beispiel, wie Sie eine "
            "Adresse anmelden, einen Ausweis beantragen oder Sperrgut "
            "entsorgen. Für Auskünfte zu Ihrem persönlichen Fall wenden Sie "
            "sich bitte an die zuständige Stelle."
        ),
        "en": (
            "I am Dumi, an assistant for questions about Canton of Zug "
            "services. I answer only from published official information and "
            "show the sources with every answer. Ask me, for example, how to "
            "register an address, apply for an ID, or dispose of bulky "
            "waste. For questions about your personal case, please contact "
            "the responsible office."
        ),
        "fr": (
            "Je suis Dumi, un assistant pour les questions sur les "
            "prestations du canton de Zoug. Je réponds uniquement sur la "
            "base d'informations officielles publiées et j'indique mes "
            "sources avec chaque réponse. Demandez-moi par exemple comment "
            "annoncer votre arrivée, demander une carte d'identité ou "
            "éliminer des déchets encombrants. Pour votre situation "
            "personnelle, adressez-vous au service compétent."
        ),
        "it": (
            "Sono Dumi, un assistente per le domande sui servizi del Canton "
            "Zugo. Rispondo esclusivamente sulla base di informazioni "
            "ufficiali pubblicate e mostro le fonti con ogni risposta. Mi "
            "chieda ad esempio come notificare il domicilio, richiedere la "
            "carta d'identità o smaltire i rifiuti ingombranti. Per il suo "
            "caso personale si rivolga all'ufficio competente."
        ),
    },
    "answer.sources_inconsistent": {
        "de": (
            "Die offiziellen Quellen zu dieser Frage scheinen sich zu "
            "widersprechen. Die Angaben werden derzeit geprüft. Bitte "
            "verlassen Sie sich nicht auf eine einzelne Angabe und fragen Sie "
            "im Zweifel bei der zuständigen Stelle nach."
        ),
        "en": (
            "The official sources for this question appear to contradict each "
            "other. The information is being reviewed. Please do not rely on "
            "a single figure and check with the responsible office if in "
            "doubt."
        ),
        "fr": (
            "Les sources officielles concernant cette question semblent se "
            "contredire. Les informations sont en cours de vérification. Ne "
            "vous fiez pas à une seule indication et renseignez-vous auprès "
            "du service compétent en cas de doute."
        ),
        "it": (
            "Le fonti ufficiali su questa domanda sembrano contraddirsi. Le "
            "informazioni sono in fase di verifica. Non fate affidamento su "
            "una singola indicazione e in caso di dubbio rivolgetevi "
            "all'ufficio competente."
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
    "auth.invalid_credentials": {
        "de": "E-Mail-Adresse oder Passwort ist falsch.",
        "en": "That email address or password is incorrect.",
        "fr": "Adresse e-mail ou mot de passe incorrect.",
        "it": "Indirizzo e-mail o password non corretti.",
    },
    "auth.locked": {
        "de": "Zu viele Fehlversuche. Das Konto ist vorübergehend gesperrt.",
        "en": "Too many failed attempts. The account is temporarily locked.",
        "fr": "Trop de tentatives échouées. Le compte est temporairement bloqué.",
        "it": "Troppi tentativi falliti. L'account è temporaneamente bloccato.",
    },
    "auth.sign_in": {
        "de": "Anmelden", "en": "Sign in", "fr": "Se connecter", "it": "Accedi",
    },
    "auth.sign_out": {
        "de": "Abmelden", "en": "Sign out", "fr": "Se déconnecter", "it": "Esci",
    },
    "auth.email": {
        "de": "E-Mail-Adresse", "en": "Email address",
        "fr": "Adresse e-mail", "it": "Indirizzo e-mail",
    },
    "auth.password": {
        "de": "Passwort", "en": "Password", "fr": "Mot de passe", "it": "Password",
    },
    "auth.new_password": {
        "de": "Neues Passwort", "en": "New password",
        "fr": "Nouveau mot de passe", "it": "Nuova password",
    },
    "auth.repeat_password": {
        "de": "Passwort wiederholen", "en": "Repeat password",
        "fr": "Répéter le mot de passe", "it": "Ripeta la password",
    },
    "auth.passwords_differ": {
        "de": "Die beiden Passwörter stimmen nicht überein.",
        "en": "The two passwords do not match.",
        "fr": "Les deux mots de passe ne correspondent pas.",
        "it": "Le due password non corrispondono.",
    },
    "auth.must_change_password": {
        "de": "Bitte legen Sie ein neues Passwort fest, bevor Sie fortfahren.",
        "en": "Please set a new password before continuing.",
        "fr": "Veuillez définir un nouveau mot de passe avant de continuer.",
        "it": "Imposti una nuova password prima di continuare.",
    },
    "auth.password_changed": {
        "de": "Passwort geändert. Alle anderen Sitzungen wurden beendet.",
        "en": "Password changed. All other sessions have been ended.",
        "fr": "Mot de passe modifié. Toutes les autres sessions ont été fermées.",
        "it": "Password modificata. Tutte le altre sessioni sono state chiuse.",
    },
    "admin.title": {
        "de": "Verwaltung", "en": "Administration",
        "fr": "Administration", "it": "Amministrazione",
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
    # Careful with wording here: this sentence is rendered on the public
    # page, and the page must not carry the word "official" anywhere. The
    # sources are the canton's pages; saying so names them without it.
    "chat.thinking": {
        "de": "Dumi durchsucht die Seiten des Kantons",
        "en": "Dumi is searching the canton's pages",
        "fr": "Dumi cherche dans les pages du canton",
        "it": "Dumi sta cercando nelle pagine del cantone",
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
    "chat.new_chat": {
        "de": "Neuer Chat",
        "en": "New chat",
        "fr": "Nouveau chat",
        "it": "Nuova chat",
    },
    "chat.intro": {
        "de": (
            "Ich heisse Dumi. Ich beantworte Fragen zu den öffentlichen "
            "Informationen des Kantons Zug."
        ),
        "en": (
            "My name is Dumi. I answer questions about the public "
            "information of the Canton of Zug."
        ),
        "fr": (
            "Je m'appelle Dumi. Je réponds aux questions sur les "
            "informations publiques du canton de Zoug."
        ),
        "it": (
            "Mi chiamo Dumi. Rispondo a domande sulle informazioni "
            "pubbliche del Cantone di Zugo."
        ),
    },
    "chat.suggestions": {
        "de": "Beispielfragen",
        "en": "Example questions",
        "fr": "Exemples de questions",
        "it": "Esempi di domande",
    },
    "chat.suggestion_moving": {
        "de": "Wie melde ich meinen Umzug an?",
        "en": "How do I register a change of address?",
        "fr": "Comment annoncer mon déménagement ?",
        "it": "Come annuncio il mio trasloco?",
    },
    "chat.suggestion_tax": {
        "de": "Wie reiche ich meine Steuererklärung ein?",
        "en": "How do I file my tax return?",
        "fr": "Comment remettre ma déclaration d'impôts ?",
        "it": "Come consegno la dichiarazione d'imposta?",
    },
    "chat.suggestion_id": {
        "de": "Wo erneuere ich Pass oder Identitätskarte?",
        "en": "Where do I renew my passport or identity card?",
        "fr": "Où renouveler mon passeport ou ma carte d'identité ?",
        "it": "Dove rinnovo il passaporto o la carta d'identità?",
    },
    "chat.disclaimer": {
        "de": "Dumi kann Fehler machen. Bitte prüfen Sie wichtige Angaben auf",
        "en": "Dumi can make mistakes. Please verify important information on",
        "fr": "Dumi peut faire des erreurs. Veuillez vérifier les informations importantes sur",
        "it": "Dumi può commettere errori. Verifichi le informazioni importanti su",
    },
    "feedback.up": {
        "de": "Gute Antwort",
        "en": "Good answer",
        "fr": "Bonne réponse",
        "it": "Buona risposta",
    },
    "feedback.down": {
        "de": "Nicht hilfreich",
        "en": "Not helpful",
        "fr": "Pas utile",
        "it": "Non utile",
    },
    "feedback.thanks": {
        "de": "Danke für Ihre Rückmeldung.",
        "en": "Thank you for your feedback.",
        "fr": "Merci pour votre retour.",
        "it": "Grazie per il suo riscontro.",
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
    # --- document uploads --------------------------------------------------
    # Every refusal says what was wrong and, where there is one, what to do
    # instead. "Upload failed" tells the person nothing they can act on.
    "upload.accepted": {
        "de": "Die Datei wurde übernommen. Bitte ergänzen Sie die Metadaten.",
        "en": "The file was accepted. Please supply the metadata.",
        "fr": "Le fichier a été accepté. Veuillez fournir les métadonnées.",
        "it": "Il file è stato accettato. Inserire i metadati.",
    },
    "upload.duplicate_of_existing": {
        "de": "Diese Datei wurde bereits hochgeladen. Sie sehen den bestehenden Eintrag.",
        "en": "This file has already been uploaded. You are looking at the existing entry.",
        "fr": "Ce fichier a déjà été téléversé. Vous voyez l'entrée existante.",
        "it": "Questo file è già stato caricato. State vedendo la voce esistente.",
    },
    "upload.refused.empty_file": {
        "de": "Die Datei ist leer.",
        "en": "The file is empty.",
        "fr": "Le fichier est vide.",
        "it": "Il file è vuoto.",
    },
    "upload.refused.file_too_large": {
        "de": "Die Datei überschreitet die zulässige Grösse.",
        "en": "The file exceeds the permitted size.",
        "fr": "Le fichier dépasse la taille autorisée.",
        "it": "Il file supera la dimensione consentita.",
    },
    "upload.refused.executable": {
        "de": "Die Datei ist ein ausführbares Programm und wird nicht angenommen.",
        "en": "The file is an executable program and is not accepted.",
        "fr": "Le fichier est un programme exécutable et n'est pas accepté.",
        "it": "Il file è un programma eseguibile e non viene accettato.",
    },
    "upload.refused.archive": {
        "de": "Archivdateien werden nicht angenommen. Bitte laden Sie die Dokumente einzeln hoch.",
        "en": "Archive files are not accepted. Please upload the documents individually.",
        "fr": "Les archives ne sont pas acceptées. Veuillez téléverser les documents un par un.",
        "it": "Gli archivi non vengono accettati. Caricare i documenti singolarmente.",
    },
    "upload.refused.refused_legacy_office_document": {
        "de": "Alte Office-Formate (.doc, .xls) werden nicht angenommen. Bitte als PDF oder .docx speichern.",
        "en": "Legacy Office formats (.doc, .xls) are not accepted. Please save as PDF or .docx.",
        "fr": "Les anciens formats Office (.doc, .xls) ne sont pas acceptés. Enregistrez en PDF ou .docx.",
        "it": "I vecchi formati Office (.doc, .xls) non vengono accettati. Salvare in PDF o .docx.",
    },
    "upload.refused.extension_not_allowed": {
        "de": "Dieser Dateityp wird nicht unterstützt. Erlaubt sind PDF, DOCX, TXT, Markdown, CSV und HTML.",
        "en": "This file type is not supported. PDF, DOCX, TXT, Markdown, CSV and HTML are accepted.",
        "fr": "Ce type de fichier n'est pas pris en charge. PDF, DOCX, TXT, Markdown, CSV et HTML sont acceptés.",
        "it": "Questo tipo di file non è supportato. Sono accettati PDF, DOCX, TXT, Markdown, CSV e HTML.",
    },
    "upload.refused.content_does_not_match_extension": {
        "de": "Der Inhalt der Datei entspricht nicht ihrer Endung.",
        "en": "The content of the file does not match its extension.",
        "fr": "Le contenu du fichier ne correspond pas à son extension.",
        "it": "Il contenuto del file non corrisponde alla sua estensione.",
    },
    "upload.refused.declared_type_does_not_match_content": {
        "de": "Der gemeldete Dateityp entspricht nicht dem Inhalt.",
        "en": "The declared file type does not match the content.",
        "fr": "Le type de fichier déclaré ne correspond pas au contenu.",
        "it": "Il tipo di file dichiarato non corrisponde al contenuto.",
    },
    "upload.refused.not_a_word_document": {
        "de": "Die Datei ist kein Word-Dokument.",
        "en": "The file is not a Word document.",
        "fr": "Le fichier n'est pas un document Word.",
        "it": "Il file non è un documento Word.",
    },
    "upload.refused.malformed_zip_container": {
        "de": "Die Datei ist beschädigt und konnte nicht gelesen werden.",
        "en": "The file is damaged and could not be read.",
        "fr": "Le fichier est endommagé et n'a pas pu être lu.",
        "it": "Il file è danneggiato e non è stato possibile leggerlo.",
    },
    "upload.refused.document_contains_macros_or_executables": {
        "de": "Das Dokument enthält Makros oder eingebettete Programme.",
        "en": "The document contains macros or embedded programs.",
        "fr": "Le document contient des macros ou des programmes intégrés.",
        "it": "Il documento contiene macro o programmi incorporati.",
    },
    "upload.refused.zip_suspicious": {
        "de": "Der Aufbau der Datei ist auffällig und wird nicht angenommen.",
        "en": "The structure of the file is suspicious and is not accepted.",
        "fr": "La structure du fichier est suspecte et n'est pas acceptée.",
        "it": "La struttura del file è sospetta e non viene accettata.",
    },
    "upload.refused.infected": {
        "de": "Die Virenprüfung hat einen Fund gemeldet. Die Datei wurde gelöscht.",
        "en": "The malware scan reported a detection. The file was deleted.",
        "fr": "L'analyse antivirus a signalé une détection. Le fichier a été supprimé.",
        "it": "La scansione antivirus ha segnalato un rilevamento. Il file è stato eliminato.",
    },
    "upload.refused.scan_failed": {
        "de": "Die Virenprüfung konnte nicht abgeschlossen werden. Die Datei bleibt in Quarantäne.",
        "en": "The malware scan could not be completed. The file stays in quarantine.",
        "fr": "L'analyse antivirus n'a pas pu aboutir. Le fichier reste en quarantaine.",
        "it": "La scansione antivirus non è stata completata. Il file resta in quarantena.",
    },
    "upload.refused.extraction_failed": {
        "de": "Aus der Datei liess sich kein Text gewinnen. Ein gescanntes PDF benötigt eine Texterkennung.",
        "en": "No text could be extracted from the file. A scanned PDF needs text recognition first.",
        "fr": "Aucun texte n'a pu être extrait du fichier. Un PDF scanné nécessite une reconnaissance de texte.",
        "it": "Non è stato possibile estrarre testo dal file. Un PDF scansionato richiede il riconoscimento del testo.",
    },
    "upload.metadata.title_required": {
        "de": "Bitte geben Sie einen Titel an.",
        "en": "Please enter a title.",
        "fr": "Veuillez saisir un titre.",
        "it": "Inserire un titolo.",
    },
    "upload.metadata.department_required": {
        "de": "Bitte geben Sie die zuständige Stelle an.",
        "en": "Please name the responsible office.",
        "fr": "Veuillez indiquer le service responsable.",
        "it": "Indicare l'ufficio responsabile.",
    },
    "upload.metadata.language_unsupported": {
        "de": "Diese Sprache wird nicht unterstützt.",
        "en": "This language is not supported.",
        "fr": "Cette langue n'est pas prise en charge.",
        "it": "Questa lingua non è supportata.",
    },
    "upload.metadata.publication_state_invalid": {
        "de": "Der gewählte Veröffentlichungsstatus ist ungültig.",
        "en": "The selected publication state is not valid.",
        "fr": "L'état de publication sélectionné n'est pas valide.",
        "it": "Lo stato di pubblicazione selezionato non è valido.",
    },
    "upload.metadata.validity_reversed": {
        "de": "Das Enddatum liegt vor dem Startdatum.",
        "en": "The end date is before the start date.",
        "fr": "La date de fin précède la date de début.",
        "it": "La data di fine precede la data di inizio.",
    },
    "upload.metadata.no_document": {
        "de": "Zu diesem Upload gibt es kein Dokument.",
        "en": "There is no document for this upload.",
        "fr": "Aucun document n'est associé à ce téléversement.",
        "it": "Non esiste alcun documento per questo caricamento.",
    },
    "upload.approve.wrong_state": {
        "de": "Dieser Upload kann im aktuellen Zustand nicht freigegeben werden.",
        "en": "This upload cannot be approved in its current state.",
        "fr": "Ce téléversement ne peut pas être approuvé dans son état actuel.",
        "it": "Questo caricamento non può essere approvato nello stato attuale.",
    },
    "upload.approve.no_document": {
        "de": "Zu diesem Upload gibt es kein Dokument.",
        "en": "There is no document for this upload.",
        "fr": "Aucun document n'est associé à ce téléversement.",
        "it": "Non esiste alcun documento per questo caricamento.",
    },
    "upload.approve.not_public_state": {
        "de": "Entwürfe und interne Dokumente gelangen nicht in den öffentlichen Index.",
        "en": "Drafts and internal documents do not enter the public index.",
        "fr": "Les brouillons et les documents internes n'entrent pas dans l'index public.",
        "it": "Le bozze e i documenti interni non entrano nell'indice pubblico.",
    },
    "upload.withdraw.wrong_state": {
        "de": "Dieser Upload kann im aktuellen Zustand nicht zurückgezogen werden.",
        "en": "This upload cannot be withdrawn in its current state.",
        "fr": "Ce téléversement ne peut pas être retiré dans son état actuel.",
        "it": "Questo caricamento non può essere ritirato nello stato attuale.",
    },
    "upload.withdraw.reason_required": {
        "de": "Bitte geben Sie einen Grund an.",
        "en": "Please give a reason.",
        "fr": "Veuillez indiquer un motif.",
        "it": "Indicare un motivo.",
    },
    "upload.withdraw.no_document": {
        "de": "Zu diesem Upload gibt es kein Dokument.",
        "en": "There is no document for this upload.",
        "fr": "Aucun document n'est associé à ce téléversement.",
        "it": "Non esiste alcun documento per questo caricamento.",
    },
    "upload.replace.no_document": {
        "de": "Dieser Upload hat kein Dokument, das ersetzt werden könnte.",
        "en": "This upload has no document that could be replaced.",
        "fr": "Ce téléversement n'a aucun document à remplacer.",
        "it": "Questo caricamento non ha un documento da sostituire.",
    },
    "upload.delete.reason_required": {
        "de": "Bitte geben Sie einen Grund an.",
        "en": "Please give a reason.",
        "fr": "Veuillez indiquer un motif.",
        "it": "Indicare un motivo.",
    },
    # --- sources and crawling ----------------------------------------------
    "source.created": {
        "de": "Die Quelle wurde angelegt. Sie können sie jetzt crawlen.",
        "en": "The source was created. You can crawl it now.",
        "fr": "La source a été créée. Vous pouvez la parcourir maintenant.",
        "it": "La fonte è stata creata. Ora può avviare la scansione.",
    },
    "source.name_required": {
        "de": "Bitte geben Sie einen Namen an.",
        "en": "Please enter a name.",
        "fr": "Veuillez saisir un nom.",
        "it": "Inserire un nome.",
    },
    "source.invalid_url": {
        "de": "Die Adresse ist ungültig. Sie muss mit https:// beginnen.",
        "en": "The address is not valid. It must start with https://.",
        "fr": "L'adresse n'est pas valide. Elle doit commencer par https://.",
        "it": "L'indirizzo non è valido. Deve iniziare con https://.",
    },
    "source.host_not_allowed": {
        "de": (
            "Dieser Host steht nicht auf der Liste der erlaubten Websites. "
            "Die Liste wird in der Konfiguration festgelegt, nicht hier."
        ),
        "en": (
            "This host is not on the list of allowed sites. The list is set "
            "in the configuration, not here."
        ),
        "fr": (
            "Cet hôte ne figure pas dans la liste des sites autorisés. La "
            "liste est définie dans la configuration, pas ici."
        ),
        "it": (
            "Questo host non è nell'elenco dei siti consentiti. L'elenco è "
            "definito nella configurazione, non qui."
        ),
    },
    "source.duplicate": {
        "de": "Eine Quelle mit dieser Adresse existiert bereits.",
        "en": "A source with this address already exists.",
        "fr": "Une source avec cette adresse existe déjà.",
        "it": "Una fonte con questo indirizzo esiste già.",
    },
    "crawl.started": {
        "de": (
            "Der Crawl läuft im Hintergrund. Laden Sie diese Seite neu, um "
            "den Fortschritt zu sehen."
        ),
        "en": (
            "The crawl is running in the background. Reload this page to see "
            "its progress."
        ),
        "fr": (
            "L'exploration s'exécute en arrière-plan. Rechargez cette page "
            "pour suivre la progression."
        ),
        "it": (
            "La scansione è in corso in background. Ricaricare questa pagina "
            "per vedere i progressi."
        ),
    },
    "crawl.already_running": {
        "de": "Für diese Quelle läuft bereits ein Crawl.",
        "en": "A crawl is already running for this source.",
        "fr": "Une exploration est déjà en cours pour cette source.",
        "it": "Una scansione è già in corso per questa fonte.",
    },
    "crawl.source_paused": {
        "de": "Diese Quelle ist pausiert und wird nicht gecrawlt.",
        "en": "This source is paused and will not be crawled.",
        "fr": "Cette source est en pause et ne sera pas explorée.",
        "it": "Questa fonte è in pausa e non verrà scansionata.",
    },
    # --- contradiction review ----------------------------------------------
    "review.unknown_outcome": {
        "de": "Diese Entscheidung gibt es nicht.",
        "en": "That is not one of the available decisions.",
        "fr": "Cette décision n'existe pas.",
        "it": "Questa decisione non esiste.",
    },
    "review.already_decided": {
        "de": "Dieser Befund wurde bereits entschieden.",
        "en": "This finding has already been decided.",
        "fr": "Ce constat a déjà été tranché.",
        "it": "Questo caso è già stato deciso.",
    },
    "review.not_open": {
        "de": "Dieser Befund ist nicht offen.",
        "en": "This finding is not open.",
        "fr": "Ce constat n'est pas ouvert.",
        "it": "Questo caso non è aperto.",
    },
    "review.note_required": {
        "de": (
            "Bitte begründen Sie die Entscheidung. Wenn Inhalte aus dem Index "
            "entfernt werden, muss der Grund festgehalten sein."
        ),
        "en": (
            "Please give a reason. A decision that removes content from the "
            "index must have its reason on record."
        ),
        "fr": (
            "Veuillez motiver la décision. Le retrait de contenus de l'index "
            "doit être justifié par écrit."
        ),
        "it": (
            "Motivare la decisione. La rimozione di contenuti dall'indice "
            "richiede una motivazione registrata."
        ),
    },
    "review.detection_completed": {
        "de": "Die Prüfung ist abgeschlossen. Neue Befunde stehen in der Liste.",
        "en": "Detection has finished. New findings appear in the list.",
        "fr": "La détection est terminée. Les nouveaux constats figurent dans la liste.",
        "it": "Il rilevamento è terminato. I nuovi casi compaiono nell'elenco.",
    },
    "upload.delete.already_deleted": {
        "de": "Dieser Upload wurde bereits gelöscht.",
        "en": "This upload has already been deleted.",
        "fr": "Ce téléversement a déjà été supprimé.",
        "it": "Questo caricamento è già stato eliminato.",
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
