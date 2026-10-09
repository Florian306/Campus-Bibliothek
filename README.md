# 📚 Buchsortierer AI (mit Ollama & Gemini)

Eine moderne Desktop-Anwendung in Python mit elegantem Windows 11 Dark-Theme (**CustomTkinter**), die einen Ordner mit unsortierten Fachbuch-PDFs mithilfe von **lokaler KI (Ollama)** oder der **Google Gemini API** analysiert, intelligent umbenennt und automatisch in thematische Fachordner sortiert.

---

## 🌟 Features

1. **Dual AI-Engine (Lokal oder Cloud)**:
   - **🦙 Ollama (100% lokal, kostenlos, ohne API-Key & offline):** Erkennt automatisch alle lokal installierten Modelle (z. B. `llama3.2:1b`, `qwen2.5vl:latest`, `mathstral:latest`) und nutzt Structured Outputs via JSON Schema.
   - **✨ Google Gemini 2.5 Flash (Cloud):** Schnelle Analyse über die Gemini API mit verschlüsselt speicherbarem API-Key.

2. **Modernes Dashboard-Design (Windows 11 Dark)**:
   - Abgerundetes UI im modernen Slate/Zinc-Stil mit `customtkinter`.
   - Modus-Umschalter per Klick zwischen Ollama und Gemini.
   - Schnelle Verzeichnisauswahl mit automatischem PDF-Zähler.

3. **Optionen & Flexibilität**:
   - **Dateien automatisch umbenennen:** Format `[Autor] - [Titel].pdf`.
   - **Bestehende Ordnerstruktur bevorzugen:** Erkennt bereits vorhandene Ordner (z. B. `Mathematik`, `Physik`, `Informatik`) und weist sie bevorzugt zu.
   - **Trockenlauf (Dry Run):** Ermöglicht die risikolose Voransicht aller Umbenennungen und Zielpfade, ohne Dateien anzutasten.

4. **Multi-Threading & Kollisionsschutz**:
   - Analyse und Dateiverschiebung laufen in separaten Hintergrund-Threads.
   - **Konfliktschutz:** Vorhandene Zieldateien erhalten automatisch ein Suffix (`..._1.pdf`).
   - Modaler Sicherheitsdialog vor dem Verschieben.

---

## 🚀 Ausführen

### Als eigenständige `.exe` starten
Doppelklick auf:
`dist/Buchsortierer.exe`

### Aus dem Quellcode starten
```bash
pip install -r requirements.txt
python main.py
```
