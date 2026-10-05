# voice2text – plan do wersji 1.0 (open source)

## 1. Ustalenia

| Obszar | Decyzja |
|---|---|
| Platforma 1.0 | **Windows 10/11** (rdzeń pozostaje wieloplatformowy, Linux/macOS później) |
| Forma | **Aplikacja w zasobniku**: ikona, globalny skrót, małe okienko z podglądem szkicu |
| Start dyktowania | **Skrót klawiszowy** – mikrofon otwarty tylko w trakcie dyktowania |
| Wysyłka | Po **bezpiecznym haśle** tekst jest **wpisywany w aktywne okno** |
| Podgląd | **Szkic na żywo**, bez kroku zatwierdzania; poprawki skrótem „popraw ostatni” |
| Język | **Polski z angielskimi wtrąceniami** (żargon IT, nazwy własne) |
| Sprzęt | Nieznany/różny → **autodetekcja** (GPU NVIDIA albo CPU) i dobór modelu |
| Uczenie | Poprawki słów i nazw, tempo pauz, **styl tekstu** |
| Intencje | **Lokalny LLM domyślnie**, chmura jako świadoma, jawnie oznaczona opcja |
| Stack | **Python + PySide6**, faster-whisper, PyInstaller + Inno Setup |
| Licencja | **MIT** |

Zasada nadrzędna: **zero fałszywych wysyłek**. Lepiej raz nie zareagować na hasło
(powtórzysz), niż wpisać tekst w złe miejsce.

## 2. Architektura

```
┌──────────────── aplikacja Windows (PySide6) ────────────────┐
│ tray + ustawienia │ globalny skrót │ okienko szkicu (overlay) │
│ TargetWindow: zapamiętuje okno z chwili startu i sprawdza je │
│ przed wpisaniem │ Typer: SendInput (Unicode) / wklejanie      │
└──────────────┬───────────────────────────────────────────────┘
               │ zdarzenia (Qt signals, osobny wątek audio)
┌──────────────▼──────────── rdzeń (bez GUI, testowalny) ──────┐
│ audio  →  VAD (Silero)  →  STT (faster-whisper)               │
│                     ↓ słowa + znaczniki czasu                 │
│ gate (hasło/anuluj) → composer (pauzy, komendy, cofanie)       │
│        → reguły (config + nauczone) → intent (LLM, opcjonalnie)│
│ learning: zamiany słów, progi pauz, przykłady stylu           │
└──────────────────────────────────────────────────────────────┘
```

Rdzeń (`src/voice2text/`) już istnieje w prototypie i zostaje niezależny od GUI.
Warstwa Windows trafia do `src/voice2text/app/`, a kod specyficzny dla systemu do
`src/voice2text/platform/windows.py` (żeby później dodać `linux.py`/`macos.py`).

### Kluczowe decyzje techniczne

- **Wpisywanie**: `SendInput` z `KEYEVENTF_UNICODE` (polskie znaki bez zależności od
  układu klawiatury). Dla długich tekstów (> ~400 znaków) wklejanie przez schowek
  z przywróceniem poprzedniej zawartości.
- **Okno docelowe**: przy naciśnięciu skrótu zapamiętujemy `HWND` aktywnego okna.
  Jeśli przy haśle aktywne jest inne okno – **nie wpisujemy**, tylko pokazujemy
  powiadomienie „Tekst w schowku / kliknij, by wpisać”.
- **Okno z uprawnieniami admina** (UIPI blokuje wpisywanie): wykrywamy i przechodzimy
  na schowek z komunikatem, zamiast „cichej porażki”.
- **Globalny skrót**: `RegisterHotKey` przez ctypes (bez hooków klawiatury, które
  wyglądają podejrzanie dla antywirusów). Domyślnie `Ctrl+Alt+Spacja`, konfigurowalny.
  Ten sam skrót w trakcie dyktowania = przerwij (bez wysyłania).
- **VAD**: Silero (ONNX, już w zależnościach faster-whisper) zamiast obecnego
  progu energii – odporny na wentylator, klawiaturę, muzykę.
- **Podgląd na żywo**: co ~0,5 s transkrypcja bieżącego fragmentu (wynik tymczasowy,
  szary w okienku), a po pauzie wynik finalny (czarny). Hasło sprawdzamy **tylko na
  wyniku finalnym**.
- **Model**: GPU NVIDIA → `large-v3-turbo` (float16); CPU → `small` lub `medium`
  w int8 zależnie od pomiaru prędkości przy pierwszym uruchomieniu (krótki benchmark).
- **Mieszany PL/EN**: `language="pl"` na sztywno (autodetekcja na krótkich fragmentach
  myli się) + słownik użytkownika jako `hotwords`/`initial_prompt` + reguły zamian.
- **Halucynacje Whispera** na ciszy („Dziękuję za obejrzenie”, „Napisy…”): filtr
  znanych fraz + odrzucanie segmentów o niskim `avg_logprob`/wysokim `no_speech_prob`.

## 3. Bezpieczne hasło – wymagania

1. Hasło liczy się tylko **na końcu wypowiedzi i po pauzie** (już działa).
2. Fragment ucięty z powodu długości nie może wysłać (już działa).
3. Konfigurowalne hasło + **test hasła** w ustawieniach: aplikacja prosi o
   wypowiedzenie go 3× i ostrzega, gdy Whisper je przekręca albo jest za krótkie.
4. Okienko wyraźnie pokazuje stan: *słucham* / *hasło rozpoznane – wpisuję*.
5. Opcjonalne „okno na rozmyślenie się” (np. 0,8 s, Esc przerywa) – **do decyzji**.
6. Wyjście z aplikacji, utrata fokusu, błąd = szkic **nigdy** nie jest wysyłany;
   zostaje do odzyskania z historii (lokalnie, z opcją wyłączenia historii).

## 4. Uczenie się

| Co | Skąd sygnał | Jak |
|---|---|---|
| Słowa i nazwy | edycja w „popraw ostatni” lub edycja szkicu przed hasłem | diff słów → reguła po N powtórzeniach (jest w prototypie) |
| Słownik | nauczone nazwy | automatycznie trafiają do `hotwords` Whispera |
| Tempo pauz | te same edycje | dopasowanie progów przecinka/kropki (jest w prototypie) |
| Styl | profile + Twoje poprawki | instrukcje stylu + kilka ostatnich par „szkic → wersja ostateczna” jako przykłady dla LLM |

„**Popraw ostatni**” (skrót, np. `Ctrl+Alt+Z`): otwiera ostatnio wysłany tekst w okienku.
Poprawiasz, zapisujesz – aplikacja uczy się z różnicy (i opcjonalnie wpisuje poprawioną
wersję jeszcze raz). Dzięki temu nie ma kroku zatwierdzania przy każdej wysyłce.

Okienko „Czego się nauczyłem”: lista reguł z licznikami, możliwość usunięcia/edycji.
Wszystko w `%APPDATA%\voice2text\` jako czytelne pliki (TOML/JSON), z eksportem/importem.

## 5. Intencje (LLM)

- Zadanie: usuwanie autopoprawek („w poniedziałek, nie, we wtorek” → „we wtorek”),
  powtórzeń, porzuconych fragmentów, zastosowanie stylu. **Nigdy** dodawanie treści.
- **Lokalnie** (domyślnie, jeśli dostępny): dowolny serwer zgodny z OpenAI API na
  `localhost` (Ollama, LM Studio, llama.cpp server). Rekomendowany mały model
  (3–8 B) – lista przetestowanych modeli w README.
- **Chmura** (opcjonalnie): ten sam interfejs (OpenAI-compatible + Anthropic), klucz
  w Menedżerze poświadczeń Windows (`keyring`), **czerwona ikona w trayu** gdy aktywne,
  osobna zgoda przy włączeniu, możliwość włączenia tylko dla wybranych profili.
- Strażnik: jeśli wynik LLM odbiega od szkicu bardziej niż próg (np. dodane zdania)
  → używamy szkicu bez LLM i logujemy lokalnie.
- Bez LLM wszystko działa (reguły + heurystyki pauz) – LLM to dodatek.
- Budżet opóźnienia: ≤ 1,5 s od hasła do wpisania z LLM, ≤ 0,5 s bez.

## 6. Prywatność (deklaracja w README i SECURITY.md)

- Audio tylko w RAM, nigdy na dysku (opcjonalny tryb debug zapisuje – wyraźnie oznaczony).
- Zero telemetrii, zero kont. Jedyny ruch sieciowy: pobranie modelu (z sumą
  kontrolną) i – tylko jeśli włączysz – zapytania do chmurowego LLM.
- Tryb offline wymuszony po pobraniu modelu (`HF_HUB_OFFLINE`).
- Logi bez treści dyktowanej (domyślnie).
- Test CI sprawdzający, że rdzeń nie otwiera połączeń sieciowych w trybie offline.

## 7. Jakość i testy

- **Testy jednostkowe** rdzenia (są: 27) + testy GUI (`pytest-qt`).
- **Zestaw ewaluacyjny**: ~30–50 Twoich nagrań z wzorcowym tekstem (lokalnie, nie
  w repo) + syntetyczny zestaw publiczny. Metryki: WER, F1 interpunkcji,
  **liczba fałszywych wysyłek (musi być 0)**, pominięte hasła, opóźnienie.
  Skrypt `v2t eval` porównuje wersje i modele.
- **CI (GitHub Actions)**: testy na `windows-latest` i `ubuntu-latest`, ruff, mypy;
  build instalatora na tagu.

## 8. Dystrybucja

- PyInstaller (onedir) + Inno Setup → `voice2text-setup.exe`. Model pobierany przy
  pierwszym uruchomieniu z paskiem postępu (instalator ~150–250 MB bez modelu).
- „Pakiet GPU” (biblioteki CUDA ~1 GB) jako osobne, opcjonalne pobranie.
- Podpis kodu przez **SignPath.io** (darmowy dla OSS) – inaczej SmartScreen straszy.
- Później: `winget`, Scoop. Autostart z Windows jako opcja.

## 9. Open source

- Repo: README (EN + PL), LICENSE (MIT), CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md,
  szablony zgłoszeń, CHANGELOG, wersjonowanie SemVer.
- UI i komunikaty: angielski + polski (Qt `tr`), komendy głosowe per język
  (domyślne PL i EN) – żeby projekt był użyteczny poza Polską.
- Nazwa: „voice2text” jest bardzo ogólna i prawdopodobnie zajęta na PyPI/winget –
  **do decyzji** przed publikacją.

## 10. Kamienie milowe

| # | Zakres | Gotowe, gdy |
|---|---|---|
| M0 ✅ | Prototyp rdzenia (CLI): hasło, pauzy, komendy, uczenie | 27 testów, `v2t simulate` |
| M1 | Rdzeń produkcyjny: Silero VAD, podgląd na żywo, filtr halucynacji, hotwords, autodobór modelu, `v2t eval`, refaktor configu (walidacja, `%APPDATA%`) | testy + zestaw ewaluacyjny, 0 fałszywych wysyłek |
| M2 | Aplikacja Windows MVP: tray, skrót, okienko szkicu, wpisywanie w zapamiętane okno, ustawienia, test hasła | dyktujesz do Slacka/przeglądarki na co dzień |
| M3 | Uczenie w UI: „popraw ostatni”, ekran reguł, profile stylu, eksport/import | reguły powstają bez edytowania plików |
| M4 | Intencje: lokalny LLM + opcjonalna chmura, strażnik zmian, budżet opóźnień | autopoprawki rozumiane poprawnie w zestawie ewaluacyjnym |
| M5 | Wydanie 0.9 beta: instalator, podpis, CI, dokumentacja EN/PL, nazwa | instalacja na czystym Windows bez Pythona |
| M6 | 1.0: poprawki z bety, `winget`, przewodnik dla kontrybutorów | 2–3 tygodnie stabilnego użycia przez testerów |

## 11. Ryzyka

| Ryzyko | Ograniczenie |
|---|---|
| Wolny CPU → duże opóźnienia | benchmark przy instalacji, mniejszy model, podgląd tymczasowy |
| Whisper przekręca hasło | test hasła w ustawieniach, dopasowanie rozmyte, rekomendacja 2–3 wyrazowych haseł |
| Wpisanie w złe okno | zapamiętany `HWND`, fallback do schowka |
| Antywirus/SmartScreen | `RegisterHotKey` zamiast hooków, podpis kodu |
| Rozmiar instalatora (CUDA) | pakiet GPU osobno |
| Brak możliwości testu na Windows w chmurze | CI na `windows-latest` + Twoje testy ręczne na każdym kamieniu |

## 12. Otwarte pytania

1. Nazwa projektu (i sprawdzenie dostępności na GitHub/PyPI/winget).
2. Czy chcesz „okno na rozmyślenie się” (0,8 s z Esc) po haśle?
3. Domyślny skrót klawiszowy.
4. Dostawca chmury dla intencji (Anthropic / OpenAI / dowolny zgodny z OpenAI).
5. Czy CLI zostaje jako oficjalny interfejs (dla Linuksa i zaawansowanych)?
