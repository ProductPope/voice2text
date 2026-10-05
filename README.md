# voice2text

Lokalne dyktowanie, które:

- **nie wysyła niczego, dopóki nie powiesz bezpiecznego hasła** (domyślnie „wyślij teraz”);
- **rozumie pauzy**: pauza po „i”, „że”, „w”… to zastanawianie się, a nie koniec zdania;
  dłuższa pauza to przecinek, długa to kropka;
- **uczy się Twoich zasad** z poprawek: zamiany słów (np. „postgres” → „PostgreSQL”, imiona)
  i Twojego tempa mówienia (progi pauz);
- **działa w 100% lokalnie**: Whisper na Twoim komputerze, bez kont, bez telemetrii,
  audio tylko w pamięci RAM (nigdy nie trafia na dysk).

## Instalacja

```bash
pip install -e ".[listen]"      # faster-whisper, mikrofon, schowek
pip install -e ".[type]"        # opcjonalnie: wpisywanie w aktywne okno
v2t init                        # tworzy ~/.config/voice2text/config.toml
v2t listen
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
3. **Ręcznie**: `v2t learn "ajfon" "iPhone"`, `v2t forget "ajfon"`.
4. Podgląd wszystkiego: `v2t rules`.

Nauczone dane leżą w `~/.config/voice2text/learned.json` (zwykły JSON, możesz go edytować
lub usunąć). Katalog zmienisz zmienną `VOICE2TEXT_HOME`.

## Intencje (opcjonalnie, lokalny LLM)

Heurystyki pauz nie złapią np. „w poniedziałek… nie, we wtorek”. Do tego jest opcjonalny
krok przez **lokalny** model w [Ollama](https://ollama.com):

```toml
[polish]
enabled = true
model = "llama3.1"
instructions = "Pisz zwięźle, bez wykrzykników."
```

Wysyłka do adresu innego niż `localhost` jest zablokowana, dopóki jawnie nie ustawisz
`allow_remote = true`. Poprawki LLM-a nie uczą reguł – uczą tylko Twoje własne edycje.

## Testowanie bez mikrofonu

`[1.2]` oznacza 1,2 s ciszy:

```bash
v2t simulate --output stdout "Zrobimy to w [2.0] poniedziałek [1.0] wyślij teraz"
# Zrobimy to w poniedziałek.
```

```bash
pip install -e ".[dev]" && pytest
```

## Strojenie

| Ustawienie | Domyślnie | Kiedy zmienić |
|---|---|---|
| `pauses.split_silence` | 0.6 s | po ilu sekundach ciszy fragment idzie do transkrypcji (nie do wysłania) |
| `pauses.comma_gap` | 0.7 s | próg przecinka (uczony z poprawek) |
| `pauses.sentence_gap` | 1.5 s | próg końca zdania (uczony z poprawek) |
| `general.model` | `small` | `medium`/`large-v3` lepiej rozumie polski, ale wolniej |
| `audio.energy_threshold` | auto | ustaw np. `0.02`, jeśli szum tła jest brany za mowę |
| `text.continuations` | spójniki, przyimki | słowa, po których pauza nigdy nie kończy zdania |

`v2t listen --debug` pokazuje surowe słowa Whispera z czasami – przydatne do strojenia.

## Struktura

```
src/voice2text/
  audio.py        mikrofon + podział na fragmenty po ciszy
  transcriber.py  faster-whisper (lokalnie)
  gate.py         bezpieczne hasło / anulowanie
  composer.py     pauzy → interpunkcja, komendy, wypełniacze, cofanie
  learning.py     uczenie zamian słów i progów pauz
  polish.py       opcjonalny lokalny LLM
  session.py      spina wszystko; wysyła tylko po haśle
  output.py       schowek / wpisywanie / plik / stdout / komenda
```
