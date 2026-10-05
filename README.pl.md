# dictAItor

*Ty dyktujesz. On czeka na rozkaz.*

[English → README.md](README.md)

Lokalne dyktowanie, które:

- **nie wysyła niczego, dopóki nie powiesz bezpiecznego hasła** (domyślnie „wyślij teraz”);
- **rozumie pauzy**: pauza po „i”, „że”, „w”… to zastanawianie się, a nie koniec zdania;
  dłuższa pauza to przecinek, długa to kropka;
- **uczy się Twoich zasad** z poprawek: zamiany słów (np. „postgres” → „PostgreSQL”, imiona)
  i Twojego tempa mówienia (progi pauz);
- **działa w 100% lokalnie**: Whisper na Twoim komputerze, bez kont, bez telemetrii,
  audio tylko w pamięci RAM (nigdy nie trafia na dysk).

## Instalacja

**Windows, bez wpisywania komend:** zobacz [docs/START-WINDOWS.md](docs/START-WINDOWS.md) · [English: README.md](README.md).

Ręcznie:

```bash
pip install -e ".[listen]"      # faster-whisper, mikrofon, schowek
pip install -e ".[type]"        # opcjonalnie: wpisywanie w aktywne okno
dictaitor init                        # tworzy ~/.config/dictaitor/config.toml
dictaitor listen
```

Przy pierwszym uruchomieniu model Whispera jest pobierany jednorazowo z Hugging Face.
Potem możesz pracować całkowicie offline: `export HF_HUB_OFFLINE=1`.

Na Linuksie schowek wymaga `xclip` albo `wl-clipboard`
(lub ustaw `output.mode = "command"` z `command = "wl-copy"`).

## Jak się tego używa

```
Spotkanie jest w środę … i … w czwartek. [długa pauza]
Kto przyjdzie? nowa linia Pozdrawiam
wyślij teraz [pauza]
```

→ do schowka trafia:

```
Spotkanie jest w środę i w czwartek. Kto przyjdzie?
Pozdrawiam.
```

| Mówisz | Efekt |
|---|---|
| **„wyślij teraz”** + pauza | wysyła szkic (hasło jest wycinane z tekstu) |
| „anuluj wszystko” + pauza | kasuje szkic, nic nie jest wysyłane |
| „cofnij” / „skreśl to” | usuwa fragment od ostatniej pauzy |
| „wyczyść wszystko” | czyści szkic, słuchanie trwa dalej |
| „kropka”, „przecinek”, „znak zapytania”, „wykrzyknik”, „dwukropek”, „średnik”, „myślnik” | interpunkcja |
| „nowa linia”, „nowy akapit” | łamanie wiersza |
| „yyy”, „eee”, „hmm” | usuwane |

### Dlaczego hasło nie wyśle się przypadkiem

- Liczy się tylko, gdy jest **na końcu wypowiedzi i po nim zamilkniesz**
  („powiedz mu wyślij teraz ten raport” nie wysyła).
- Gdy fragment został ucięty z powodu długości (a nie ciszy), hasło jest ignorowane.
- Przerwanie programu (Ctrl+C) niczego nie wysyła – szkic jest tylko pokazywany w terminalu.
- Hasło ustawiasz sam w `[gate] send_phrase` – wybierz coś, czego nie mówisz w treści,
  np. „zatwierdzam bez zmian”. Dopasowanie toleruje drobne przekręcenia Whispera
  (`match_threshold`).

## Uczenie się Twoich zasad

1. **Stałe reguły** – w `config.toml`:
   ```toml
   [rules]
   replacements = { "kubernetis" = "Kubernetes", "ej pi aj" = "API" }
   vocabulary = ["Kubernetes", "Marcin"]   # pomaga Whisperowi i zachowuje wielkie litery
   ```
2. **Uczenie z poprawek** – włącz `[review] enabled = true`. Po haśle otwiera się `$EDITOR`
   z tekstem; to, co zapiszesz, zostaje wysłane, a narzędzie porównuje to ze szkicem:
   - ta sama poprawka słowa 2× (`learning.min_occurrences`) → odtąd robi ją samo;
   - imię poprawione z małej na wielką literę w środku zdania → zapamiętane;
   - gdzie zostawiłeś kropkę/przecinek, a gdzie usunąłeś → progi pauz dopasowują się
     do Twojego tempa (np. jeśli mówisz wolno, 1,2 s przestaje kończyć zdanie).
   - pusty plik = anulowanie.
3. **Ręcznie**: `dictaitor learn "ajfon" "iPhone"`, `dictaitor forget "ajfon"`.
4. Podgląd wszystkiego: `dictaitor rules`.

Nauczone dane leżą w `~/.config/dictaitor/learned.json` (zwykły JSON, możesz go edytować
lub usunąć). Katalog zmienisz zmienną `DICTAITOR_HOME`.

## Intencje – porządkowanie przez AI (opcjonalnie)

Heurystyki pauz nie złapią np. „w poniedziałek… nie, we wtorek”. Do tego jest opcjonalny
krok przez model językowy (`[intent]` w `config.toml` albo **Ustawienia…** w aplikacji):

| `mode` | Gdzie trafia tekst |
|---|---|
| `off` (domyślnie) | nigdzie |
| `local` | do modelu na **Twoim komputerze** – [Ollama](https://ollama.com), LM Studio, llama.cpp (API zgodne z OpenAI). Adresy spoza komputera są blokowane, dopóki nie ustawisz `allow_remote = true`. |
| `claude` | do **Claude API** (chmura) – tylko po świadomym włączeniu; klucz w Menedżerze poświadczeń Windows, nie w plikach |

Model dostaje Twoje zasady stylu (`instructions`, a dla konkretnych aplikacji `[profiles]`,
np. inne dla Slacka, inne dla Outlooka) i kilka Twoich ostatnich poprawek z Ctrl+Alt+K jako
przykłady. **Strażnik** porównuje wynik ze szkicem: jeśli model dopisze treść albo zmieni
za dużo słów, wysyłany jest tekst bez zmian. Błąd lub przekroczony czas (`timeout`)
również kończą się wysłaniem szkicu – dyktowanie nigdy nie przepada przez AI.
Poprawki modelu nie uczą reguł – uczą tylko Twoje własne edycje.

## Testowanie bez mikrofonu

`[1.2]` oznacza 1,2 s ciszy:

```bash
dictaitor simulate --output stdout "Zrobimy to w [2.0] poniedziałek [1.0] wyślij teraz"
# Zrobimy to w poniedziałek.
```

```bash
pip install -e ".[dev]" && pytest
```

## Mierzenie jakości na własnym głosie

Nagraj kilkanaście typowych wiadomości (razem z hasłem) i zmierz, jak sobie radzi:

```bash
dictaitor record nagrania zakupy        # nagrywa do nagrania/zakupy.wav, pyta o oczekiwany tekst
dictaitor eval nagrania                 # WER, interpunkcja, fałszywe wysyłki, opóźnienie
dictaitor eval nagrania --model small --model large-v3-turbo   # porównanie modeli
```

W pliku `.txt` jest to, co powinno zostać wysłane; kilka wysyłek oddziel linią `---`,
a `#nosend` oznacza „nic nie może zostać wysłane” (np. hasło powiedziane w środku zdania).
`record` to jedyna komenda, która zapisuje dźwięk na dysk – nagrania zostają u Ciebie.

## Strojenie

| Ustawienie | Domyślnie | Kiedy zmienić |
|---|---|---|
| `pauses.split_silence` | 0.6 s | po ilu sekundach ciszy fragment idzie do transkrypcji (nie do wysłania) |
| `pauses.comma_gap` | 0.7 s | próg przecinka (uczony z poprawek) |
| `pauses.sentence_gap` | 1.5 s | próg końca zdania (uczony z poprawek) |
| `general.model` | `auto` | `large-v3-turbo` na GPU NVIDIA lub CPU z 8+ rdzeniami, inaczej `small`; porównaj przez `dictaitor eval --model` |
| `audio.vad` | `auto` | `silero` (sieć neuronowa, odporna na szum) albo `energy` (próg głośności) |
| `audio.preview_interval` | 1.0 s | jak często pokazywać podgląd tego, co właśnie mówisz; `0` wyłącza (oszczędza CPU) |
| `text.continuations` | spójniki, przyimki | słowa, po których pauza nigdy nie kończy zdania |

`dictaitor listen --debug` pokazuje surowe słowa Whispera z czasami – przydatne do strojenia.

## Aplikacja w zasobniku (Windows)

`dictaitor app` (albo `windows\6-aplikacja.bat`): `Ctrl+Alt+D` zaczyna dyktowanie, `Ctrl+Alt+K` poprawia ostatni tekst (i uczy się z poprawki), hasło wpisuje tekst
w okno, w którym byłeś, po 0,8 s na rozmyślenie się (Esc). Szczegóły w [docs/START-WINDOWS.md](docs/START-WINDOWS.md) · [English: README.md](README.md).

## Struktura

```
src/dictaitor/
  audio.py        mikrofon + wykrywanie mowy (Silero VAD) i podział na fragmenty
  transcriber.py  faster-whisper (lokalnie), dobór modelu, filtr zmyśleń Whispera
  pipeline.py     dźwięk → fragmenty → słowa → sesja, podgląd na żywo
  evaluate.py     `dictaitor eval`: pomiar jakości na Twoich nagraniach
  metrics.py      WER i trafność interpunkcji
  gate.py         bezpieczne hasło / anulowanie
  composer.py     pauzy → interpunkcja, komendy, wypełniacze, cofanie
  learning.py     uczenie zamian słów i progów pauz
  intent.py       porządkowanie przez AI: lokalny model lub Claude, strażnik zmian
  session.py      spina wszystko; wysyła tylko po haśle
  output.py       schowek / wpisywanie / plik / stdout / komenda
  app/            aplikacja w zasobniku: controller (logika), win32 (Windows), ui (Qt)
```
