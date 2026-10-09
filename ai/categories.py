"""Standard academic categories, domain ontology, and regex keyword knowledge bases.
"""

import re
from typing import Dict, List, Set, Tuple, Pattern

STANDARD_CATEGORIES: List[str] = [
    "Mathematik",
    "Physik & Astronomie",
    "Chemie",
    "Biologie & Lebenswissenschaften",
    "Geowissenschaften & Geologie",
    "Informatik & Programmierung",
    "Medizin & Pharmazie",
    "Psychologie & Soziologie",
    "Wirtschaftswissenschaften",
    "Rechtswissenschaften & Jura",
    "Ingenieurwissenschaften & Technik",
    "Geschichte & Politik",
    "Philosophie & Religion",
    "Pädagogik & Schule",
    "Sprach- & Literaturwissenschaft",
    "Sonstiges",
]

METAPHOR_STOPWORDS: Set[str] = {
    "höhlenmenschen", "dummies", "kinder", "anfänger", "abenteuer",
    "streifzüge", "einfach", "alltag", "spaß", "kompakt", "handbuch",
    "taschenbuch", "lehrbuch", "einführung", "grundlagen", "basiswissen",
    "skript", "vorlesung", "leitfaden", "band", "teil", "auflage",
    "springer", "spektrum", "verlag", "wiley", "pearson", "de gruyter",
    "utb", "nomos", "vahlen", "c.h.beck", "oldenbourg"
}

FACULTY_KNOWLEDGE: Dict[str, Dict[str, List[str]]] = {
    "Mathematik": {
        "anchors": [
            r"\balgebra\b", r"\banalysis\b", r"\bgeometrie\b", r"\bgeometry\b", r"\bstochastik\b",
            r"\btopologie\b", r"\btopology\b", r"\bdifferentialgleichung(en)?\b", r"\bdifferential equations?\b",
            r"\bintegralrechnung\b", r"\bcalculus\b", r"\bvektorraum\b", r"\bvector space\b",
            r"\blineare algebra\b", r"\blinear algebra\b", r"\bnumerik\b", r"\bnumerical analysis\b",
            r"\bmathematik\b", r"\bmathematics\b", r"\bwahrscheinlichkeitsrechnung\b", r"\bprobability theory\b",
            r"\bfunktionentheorie\b", r"\bzahlentheorie\b", r"\bnumber theory\b",
            r"\bdiskrete mathematik\b", r"\bdiscrete mathematics\b", r"\boptimierung\b",
            r"\bhöhere mathematik\b", r"\bhochschulmathematik\b", r"\bschulmathematik\b",
            r"\bwirtschaftsmathematik\b", r"\bstatistik\b", r"\bstatistics\b"
        ],
        "keywords": [
            r"\bvektor(en)?\b", r"\bmatrix\b", r"\bmatrizen\b", r"\bdifferential\b",
            r"\bintegral\b", r"\bgrenzwerte?\b", r"\bkonvergenz\b", r"\beigenwert(e)?\b",
            r"\bableitung(en)?\b", r"\bkurvenintegral\b", r"\bpolynom(e)?\b", r"\baxiom(e)?\b"
        ]
    },
    "Physik & Astronomie": {
        "anchors": [
            r"\bphysik\b", r"\bphysics\b", r"\bquantenmechanik\b", r"\bquantum mechanics\b",
            r"\bthermodynamik\b", r"\bthermodynamics\b", r"\belektrodynamik\b", r"\belectrodynamics\b",
            r"\bastronomie\b", r"\bastronomy\b", r"\bastrophysik\b", r"\bastrophysics\b",
            r"\brelativitätstheorie\b", r"\btheory of relativity\b", r"\batomphysik\b", r"\batomic physics\b",
            r"\bkernphysik\b", r"\bnuclear physics\b", r"\bteilchenphysik\b", r"\bparticle physics\b",
            r"\bfestkörperphysik\b", r"\bsolid state physics\b", r"\bkosmologie\b", r"\bcosmology\b",
            r"\bexperimentalphysik\b", r"\btheoretische physik\b", r"\btheoretical physics\b",
            r"\burknall\b", r"\boptik\b", r"\boptics\b"
        ],
        "keywords": [
            r"\bmechanik\b", r"\bwellen(lehre)?\b", r"\bmagnetismus\b",
            r"\beigenfrequenz\b", r"\bquanten\b", r"\blaser\b", r"\bschwingung(en)?\b",
            r"\bkinematik\b", r"\bdynamik\b", r"\bhochenergie\b", r"\bgravitation\b"
        ]
    },
    "Chemie": {
        "anchors": [
            r"\bchemie\b", r"\bchemistry\b", r"\bbiochemie\b", r"\bbiochemistry\b",
            r"\bchemisch(e|er|es)?\b", r"\bchemical\b", r"\borganische chemie\b", r"\borganic chemistry\b",
            r"\banorganische chemie\b", r"\binorganic chemistry\b", r"\bphysikalische chemie\b", r"\bphysical chemistry\b",
            r"\bperiodensystem\b", r"\bperiodic table\b", r"\bstöchiometrie\b", r"\bstoichiometry\b",
            r"\bmolekülstruktur\b", r"\bmolecular structure\b", r"\bpolymerchemie\b", r"\bpolymer chemistry\b",
            r"\banalytische chemie\b", r"\banalytical chemistry\b", r"\bchemical reactions?\b", r"\breaktionsmechanismus\b"
        ],
        "keywords": [
            r"\batombau\b", r"\bbindungslehre\b", r"\breaktionskinetik\b", r"\bsäuren?\b",
            r"\bbasen?\b", r"\belektrochemie\b", r"\bkatalyse\b", r"\bspektroskopie\b",
            r"\bkomplexchemie\b", r"\bradikal(e)?\b", r"\blösungsmittel\b", r"\bsynthese\b"
        ]
    },
    "Biologie & Lebenswissenschaften": {
        "anchors": [
            r"\bbiologie\b", r"\bbiology\b", r"\bzellbiologie\b", r"\bcell biology\b",
            r"\bgenetik\b", r"\bgenetics\b", r"\bgenom\b", r"\bgenomik\b", r"\bgenomics\b",
            r"\bmikrobiologie\b", r"\bmicrobiology\b", r"\bzoologie\b", r"\bzoology\b",
            r"\bbotanik\b", r"\bbotany\b", r"\bevolution(sbiologie)?\b", r"\bevolutionary biology\b",
            r"\bmolekularbiologie\b", r"\bmolecular biology\b", r"\bökologie\b", r"\becology\b",
            r"\bpflanzenphysiologie\b", r"\bplant physiology\b", r"\bmikroorganismen\b", r"\bmicroorganisms\b",
            r"\bbakteri(en|ologie)\b", r"\bneurobiologie\b", r"\bneurobiology\b",
            r"\bbioinformatik\b", r"\bbioinformatics\b",
            r"\btiermedizin(isch(e|er|es)?)?\b", r"\bveterinärmedizin\b", r"\bveterinary medicine\b",
            r"\bkynologie\b", r"\btierhaltung\b", r"\bhundeerziehung\b", r"\btiertraining\b",
            r"\bparasitologie\b", r"\bpflanzenwissenschaft(en)?\b", r"\bverhaltensbiologie\b"
        ],
        "keywords": [
            r"\bzelle(n)?\b", r"\bcytoplasma\b", r"\bmitochondri(en|um)\b", r"\bmembran(en)?\b",
            r"\bprotein(e)?\b", r"\bdna\b", r"\brna\b", r"\bribosom(en)?\b",
            r"\bphotosynthese\b", r"\bparasit(en)?\b", r"\bpilze\b", r"\bzellteilung\b",
            r"\brasse(n)?\b", r"\bhaustier(e)?\b", r"\bwelpe(n)?\b", r"\bhund(e|en)?\b"
        ]
    },
    "Geowissenschaften & Geologie": {
        "anchors": [
            r"\bgeologie\b", r"\bgeology\b", r"\bgeowissenschaft(en)?\b", r"\bearth sciences?\b", r"\bgeosciences?\b",
            r"\bmineralogie\b", r"\bmineralogy\b", r"\bplattentektonik\b", r"\bplate tectonics\b",
            r"\bvulkanismus\b", r"\bvolcanology\b", r"\bsedimentologie\b", r"\bsedimentology\b",
            r"\bgeographie\b", r"\bgeography\b", r"\bphysische geographie\b", r"\bphysical geography\b",
            r"\berdbeben\b", r"\bseismology\b", r"\bpetrologie\b", r"\bpetrology\b",
            r"\bozeanographie\b", r"\boceanography\b", r"\bgletscherkunde\b", r"\bglaziologie\b", r"\bglaciology\b",
            r"\bpolarforschung\b", r"\bmeereis\b", r"\bklimawandel\b", r"\bclimate change\b",
            r"\bklimatologie\b", r"\bclimatology\b", r"\bsystem erde\b", r"\berdoberfläche\b",
            r"\berdkruste\b", r"\beiszeitalter\b", r"\bmeteorologie\b", r"\bmeteorology\b",
            r"\bpaläontologie\b", r"\bpaleontology\b", r"\bgeophysik\b", r"\bgeophysics\b",
            r"\bkartographie\b", r"\bcartography\b", r"\bgeoarchäologie\b"
        ],
        "keywords": [
            r"\bgestein(e)?\b", r"\bminerale?\b", r"\bmagma\b", r"\blava\b", r"\berdmantel\b",
            r"\bfossil(ien)?\b", r"\bsedimentgestein\b", r"\berdgeschichte\b", r"\beiszeit\b", r"\bbodenkunde\b",
            r"\bvulkan(e)?\b", r"\bgletscher\b"
        ]
    },
    "Informatik & Programmierung": {
        "anchors": [
            r"\binformatik\b", r"\bcomputer science\b", r"\bwirtschaftsinformatik\b",
            r"\bprogrammierung\b", r"\bprogramming\b", r"\bsoftware engineering\b",
            r"\balgorithmen?\b", r"\balgorithms?\b", r"\bdatenstrukturen?\b", r"\bdata structures?\b",
            r"\bdatenbank(en)?\b", r"\bdatabase systems?\b", r"\bdatenbankentwicklung\b",
            r"\bkünstliche intelligenz\b", r"\bartificial intelligence\b",
            r"\bmachine learning\b", r"\bdeep learning\b",
            r"\bcomputernetzwerk(e)?\b", r"\bcomputer networks?\b",
            r"\bbetriebssystem(e)?\b", r"\boperating systems?\b",
            r"\bcompiler\b", r"\bcompiler construction\b",
            r"\bcybersecurity\b", r"\bcybersicherheit\b", r"\bdatensicherheit\b", r"\bnetzwerksicherheit\b",
            r"\btheoretische informatik\b", r"\btheoretical computer science\b",
            r"\bweb development\b", r"\bwebdesign\b"
        ],
        "keywords": [
            r"\bpython\b", r"\bjava\b", r"\bc\+\+\b", r"\bc#\b", r"\brust\b", r"\blinux\b", r"\btcp/ip\b",
            r"\bjavascript\b", r"\bhtml5?\b", r"\bcss3?\b", r"\bsql\b", r"\bcloud\b",
            r"\bobjektorientiert\b", r"\bmultithreading\b"
        ]
    },
    "Medizin & Pharmazie": {
        "anchors": [
            r"\bmedizin\b", r"\bmedicine\b", r"\banatomie\b", r"\banatomy\b",
            r"\bpathologie\b", r"\bpathology\b", r"\bpharmakologie\b", r"\bpharmacology\b",
            r"\bpharmazie\b", r"\bpharmacy\b", r"\bchirurgie\b", r"\bsurgery\b",
            r"\bneurologie\b", r"\bneurology\b", r"\bkardiologie\b", r"\bcardiology\b",
            r"\bhumanmedizin\b", r"\binnere medizin\b", r"\binternal medicine\b",
            r"\bimmunologie\b", r"\bimmunology\b", r"\bhistologie\b", r"\banästhesie\b",
            r"\binfektionskrankheit(en)?\b", r"\binfectious diseases?\b", r"\binfektionsschutz\b",
            r"\bepidemiologie\b", r"\bepidemiology\b", r"\bvirologie\b", r"\bvirology\b",
            r"\bpandemie(n)?\b", r"\bpandemic\b", r"\bepidemie(n)?\b",
            r"\bimpfstoff(e)?\b", r"\bvaccine(s)?\b", r"\bimpfung(en)?\b",
            r"\bpublic health\b", r"\bgesundheitswesen\b", r"\bgesundheitswissenschaft(en)?\b",
            r"\bhuman physiology\b", r"\bkörper des menschen\b", r"\bdiagnostik\b"
        ],
        "keywords": [
            r"\bpatient(en)?\b", r"\bkrankheit(en)?\b", r"\bsymptom(e)?\b", r"\barznei(mittel)?\b",
            r"\bwirkstoff(e)?\b", r"\borgan(e)?\b", r"\bherz\b", r"\blunge\b", r"\bblutdruck\b",
            r"\bklinisch(e|er|es)?\b", r"\bviren\b", r"\bvirus\b", r"\berreger\b", r"\btherapie\b",
            r"\bklinik\b"
        ]
    },
    "Psychologie & Soziologie": {
        "anchors": [
            r"\bpsychologie\b", r"\bpsychology\b", r"\bsoziologie\b", r"\bsociology\b",
            r"\bpsychiatrie\b", r"\bpsychiatry\b", r"\bpsychotherapie\b", r"\bpsychotherapy\b",
            r"\bsozialpsychologie\b", r"\bsocial psychology\b",
            r"\bkognitionspsychologie\b", r"\bcognitive psychology\b",
            r"\bentwicklungspsychologie\b", r"\bdevelopmental psychology\b",
            r"\bklinische psychologie\b", r"\bclinical psychology\b",
            r"\bpersönlichkeitspsychologie\b", r"\bpersonality psychology\b",
            r"\bgesellschaftswissenschaft(en)?\b", r"\bsozialstruktur\b", r"\bsozialisation\b",
            r"\bneurowissenschaft(en)?\b", r"\bneuropsychologie\b", r"\bneuropsychology\b"
        ],
        "keywords": [
            r"\bkognition\b", r"\bwahrnehmung\b", r"\bgedächtnis\b", r"\bemotion(en)?\b",
            r"\bverhalten\b", r"\bpsyche\b", r"\bmotivation\b", r"\bbewusstsein\b",
            r"\bpersönlichkeit\b", r"\binteraktion\b", r"\btrauma\b",
            r"\bgesellschaft(en)?\b", r"\bsozialer wandel\b"
        ]
    },
    "Wirtschaftswissenschaften": {
        "anchors": [
            r"\bwirtschaftswissenschaft(en)?\b", r"\beconomics\b",
            r"\bbetriebswirtschaft(slehre)?\b", r"\bbusiness administration\b",
            r"\bvolkswirtschaft(slehre)?\b", r"\bbwl\b", r"\bvwl\b",
            r"\bmikroökonomie\b", r"\bmicroeconomics\b",
            r"\bmakroökonomie\b", r"\bmacroeconomics\b",
            r"\bfinanzierung\b", r"\bcorporate finance\b",
            r"\brechnungswesen\b", r"\bfinancial accounting\b", r"\bcontrolling\b",
            r"\bmarketing\b", r"\bunternehmensführung\b", r"\bwirtschaftspolitik\b",
            r"\bgeldpolitik\b"
        ],
        "keywords": [
            r"\bbilanzen?\b", r"\binflation\b", r"\bkapitalmarkt\b", r"\binvestition(en)?\b",
            r"\bkostenrechnung\b", r"\bwertschöpfung\b", r"\barbeitsmarkt\b", r"\bsteuern?\b",
            r"\bmanagement\b"
        ]
    },
    "Rechtswissenschaften & Jura": {
        "anchors": [
            r"\bjura\b", r"\brechtswissenschaft(en)?\b", r"\blaw\b", r"\bjurisprudence\b",
            r"\bbgb\b", r"\bstgb\b", r"\bgrundgesetz\b", r"\bzivilrecht\b", r"\bcivil law\b",
            r"\bstrafrecht\b", r"\bcriminal law\b", r"\böffentliches recht\b", r"\bpublic law\b",
            r"\bverfassungsrecht\b", r"\bconstitutional law\b", r"\bschuldrecht\b", r"\bsachenrecht\b",
            r"\bverwaltungsrecht\b", r"\beuroparecht\b", r"\beuropean law\b",
            r"\bhandelsrecht\b", r"\bcommercial law\b", r"\bgesellschaftsrecht\b", r"\bcorporate law\b"
        ],
        "keywords": [
            r"\bgesetz(e)?\b", r"\bparagraph(en)?\b", r"\bjuristisch(e|er|es)?\b", r"\bgutachtenstil\b",
            r"\banspruchsgrundlage\b", r"\bvertrag(srecht)?\b", r"\bschadensersatz\b",
            r"\bklage\b", r"\bgericht(shof)?\b", r"\brechtsordnung\b"
        ]
    },
    "Ingenieurwissenschaften & Technik": {
        "anchors": [
            r"\bingenieu(r|rwissenschaften)?\b", r"\bengineering\b",
            r"\bmaschinenbau\b", r"\bmechanical engineering\b",
            r"\belektrotechnik\b", r"\belectrical engineering\b",
            r"\bmechatronik\b", r"\bmechatronics\b",
            r"\bwerkstoffkunde\b", r"\bmaterials science\b",
            r"\bkonstruktionslehre\b", r"\bverfahrenstechnik\b", r"\bchemical engineering\b",
            r"\bfestigkeitslehre\b", r"\bmaschinenelemente\b",
            r"\bregelungstechnik\b", r"\bcontrol engineering\b",
            r"\bfahrzeugtechnik\b", r"\bautomotive engineering\b",
            r"\brobotik\b", r"\brobotics\b"
        ],
        "keywords": [
            r"\bkonstruktion\b", r"\bwerkstoff(e)?\b", r"\bstatik\b", r"\bbauteil(e)?\b",
            r"\bgetriebe\b", r"\bmotor(en)?\b", r"\bschaltkreis(e)?\b", r"\bsignalverarbeitung\b",
            r"\bhydraulik\b", r"\bpneumatik\b", r"\belektronik\b"
        ]
    },
    "Geschichte & Politik": {
        "anchors": [
            r"\bgeschichtswissenschaft\b", r"\bpolitikwissenschaft\b", r"\bpolitical science\b",
            r"\bzeitgeschichte\b", r"\bcontemporary history\b",
            r"\bweltgeschichte\b", r"\bworld history\b",
            r"\bweltkrieg(e|es|en)?\b", r"\bworld war\b",
            r"\bweimarer republik\b", r"\bnationalsozialismus\b", r"\bdrittes reich\b", r"\bthird reich\b",
            r"\bholocaust\b", r"\bshoah\b", r"\bjudenverfolgung\b",
            r"\bkalte(r)? krieg\b", r"\bcold war\b",
            r"\brömisches reich\b", r"\broman empire\b",
            r"\bantike geschichte\b", r"\bancient history\b",
            r"\bmittelalterliche geschichte\b", r"\bmedieval history\b",
            r"\bneuere geschichte\b", r"\bmodern history\b",
            r"\bquellenedition\b", r"\bquellenkunde\b",
            r"\bkonzentrationslager\b", r"\bauschwitz\b", r"\bmauthausen\b",
            r"\bmilitärgeschichte\b", r"\bmilitary history\b",
            r"\bpolitisches system\b", r"\bpolitical system\b",
            r"\bextremismusforschung\b", r"\bislamismus\b",
            r"\beuropäische union\b", r"\barchäologie\b", r"\barchaeology\b",
            r"\bburgenkunde\b", r"\bburgenbuch\b"
        ],
        "keywords": [
            r"\bhistorisch(e|er|es)?\b", r"\bgeschichte\b", r"\bpolitik\b", r"\bverfassung\b",
            r"\bdiplomatie\b", r"\breich\b", r"\bkaiser(reich)?\b", r"\bkonflikt(e)?\b",
            r"\bepoche\b", r"\brevolution\b", r"\bideologie\b", r"\bbesatzung\b",
            r"\bdeportation(en)?\b", r"\barchiv(e)?\b"
        ]
    },
    "Philosophie & Religion": {
        "anchors": [
            r"\bphilosophie\b", r"\bphilosophy\b", r"\bethik\b", r"\bethics\b",
            r"\berkenntnistheorie\b", r"\bepistemology\b", r"\bmetaphysik\b", r"\bmetaphysics\b",
            r"\btheologie\b", r"\btheology\b", r"\breligionswissenschaft\b", r"\breligious studies\b",
            r"\bbibelkunde\b", r"\bchristentum\b", r"\bchristianity\b",
            r"\bevangelium\b", r"\bglaubenslehre\b"
        ],
        "keywords": [
            r"\bgott\b", r"\bgöttlich(e|er|es)?\b", r"\bglaube(n)?\b", r"\bmoral\b",
            r"\berlösung\b", r"\bkirche\b", r"\bontologie\b", r"\bexistenz\b"
        ]
    },
    "Pädagogik & Schule": {
        "anchors": [
            r"\bpädagogik\b", r"\bpedagogy\b", r"\berziehungswissenschaft(en)?\b", r"\beducational science\b",
            r"\bdidaktik\b", r"\bdidactics\b", r"\bschulpädagogik\b",
            r"\bunterrichtsgestaltung\b", r"\blehrplan\b", r"\blernpsychologie\b",
            r"\bbildungswissenschaft(en)?\b", r"\bschuldidaktik\b",
            r"\bwissenschaftlich(es)? arbeiten\b"
        ],
        "keywords": [
            r"\blernen\b", r"\bkompetenz(en)?\b", r"\blehrer\b", r"\bschüler\b",
            r"\bförderung\b", r"\bmethodik\b", r"\bunterrichten\b", r"\bschule\b"
        ]
    },
    "Sprach- & Literaturwissenschaft": {
        "anchors": [
            r"\blinguistik\b", r"\blinguistics\b", r"\bsprachwissenschaft\b",
            r"\bliteraturwissenschaft\b", r"\bliterary studies\b",
            r"\bgermanistik\b", r"\banglistik\b", r"\bromanistik\b",
            r"\bphonetik\b", r"\bphonetics\b", r"\bsyntax\b", r"\bsemantik\b",
            r"\bgrammar\b", r"\bgrammatik\b", r"\bsprachkurs\b",
            r"\bbusiness english\b", r"\benglish for everyone\b", r"\bfremdsprache\b"
        ],
        "keywords": [
            r"\btextanalyse\b", r"\brhetorik\b", r"\blyrik\b",
            r"\bprosa\b", r"\bdrama\b", r"\bwortschatz\b", r"\bsprache\b"
        ]
    }
}

KEYWORD_MAP = {
    cat: [
        p.replace(r"\b", "").replace("?", "").replace("(en)", "").replace("(e)", "").replace("(um)", "")
        for p in data["anchors"] + data["keywords"]
    ]
    for cat, data in FACULTY_KNOWLEDGE.items()
}

# Pre-compile patterns once at module load for speedup
COMPILED_FACULTY_KNOWLEDGE: Dict[str, Dict[str, List[Tuple[str, Pattern]]]] = {
    faculty: {
        "anchors": [(p, re.compile(p, re.IGNORECASE)) for p in data.get("anchors", [])],
        "keywords": [(p, re.compile(p, re.IGNORECASE)) for p in data.get("keywords", [])],
    }
    for faculty, data in FACULTY_KNOWLEDGE.items()
}

# Union regexes for fast-reject checks
COMPILED_FACULTY_UNION: Dict[str, Pattern] = {
    faculty: re.compile(
        "|".join(f"(?:{p})" for p in data.get("anchors", []) + data.get("keywords", [])),
        re.IGNORECASE
    )
    for faculty, data in FACULTY_KNOWLEDGE.items()
}

